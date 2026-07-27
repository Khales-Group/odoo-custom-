"""In-system AI chat controller (Claude), backed by the MCP tool layer.

Conversations are persisted per-user (`mcp.chat.conversation` +
`mcp.chat.message`) so the chat survives page reloads and users can keep
several separate threads, like Claude.ai's chat history sidebar.
"""

import base64
import json
import logging
import os
import tempfile
from urllib.parse import quote

from odoo import fields, http
from odoo.http import request

from . import utils
from .ai_tools import build_tool_definitions, execute_tool
from .rate_limiting import check_rate_limit, get_request_limit, record_api_request

_logger = logging.getLogger(__name__)

try:
    import anthropic

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

MAX_TOOL_ITERATIONS = 8
MAX_TOKENS = 8192
MAX_HISTORY_MESSAGES = 100
CONVERSATION_NAME_LENGTH = 50

# File generation: lets Claude write/run code in an Anthropic-hosted sandbox
# to produce real PDF/Word/Excel/PowerPoint files (the same "Agent Skills"
# capability behind Claude.ai's document creation), not just formatted text.
FILE_GENERATION_BETAS = ["code-execution-2025-08-25", "skills-2025-10-02"]
FILE_GENERATION_TOOLS = [{"type": "code_execution_20260521", "name": "code_execution"}]
FILE_GENERATION_SKILLS = [
    {"type": "anthropic", "skill_id": "pdf"},
    {"type": "anthropic", "skill_id": "docx"},
    {"type": "anthropic", "skill_id": "xlsx"},
    {"type": "anthropic", "skill_id": "pptx"},
]

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_ATTACHMENT_MB = 8
MAX_ATTACHMENT_B64_CHARS = MAX_ATTACHMENT_MB * 1024 * 1024 * 4 // 3
MAX_ATTACHMENTS_PER_MESSAGE = 5

TITLE_MODEL = "claude-haiku-4-5"
TITLE_SYSTEM_PROMPT = (
    "Summarize this chat exchange into a short title (3-6 words, no quotes, "
    "no trailing punctuation), in the same language as the user's message. "
    "Reply with only the title, nothing else."
)

SYSTEM_PROMPT = (
    "You are an AI assistant embedded inside this company's Odoo system. "
    "You can look up, create, update, and delete Odoo records ONLY through "
    "the tools provided - never claim to have done something you didn't do "
    "through a tool call. If a tool call fails or is denied, tell the user "
    "plainly what happened (e.g. permission not enabled) rather than making "
    "up a result. Call list_enabled_models if you are not sure what data you "
    "can access. When looking up a customer/contact by name, use "
    "find_customer rather than a plain search_records call on res.partner - "
    "a name given in Arabic may only be on file in English (or vice versa), "
    "and find_customer knows how to cross-reference that. You CAN generate "
    "real PDF, Word, Excel, and PowerPoint files using the code execution "
    "tool - when asked for a report/document/export, actually create the "
    "file rather than saying you can't; a download link is added for the "
    "user automatically once the file is ready. Reply in the same language "
    "the user's latest message is written in (Arabic or English). Be "
    "concise and to the point."
)


def _get_client_and_model():
    params = request.env["ir.config_parameter"].sudo()
    api_key = params.get_param("mcp_server.anthropic_api_key")
    model = params.get_param("mcp_server.anthropic_model", "claude-opus-4-8")
    if not api_key:
        return None, model
    return anthropic.Anthropic(api_key=api_key), model


def _get_or_create_conversation(env, user, conversation_id, title_hint=""):
    """Return (conversation, is_new)."""
    Conversation = env["mcp.chat.conversation"]
    if conversation_id:
        conv = Conversation.search(
            [("id", "=", conversation_id), ("user_id", "=", user.id)], limit=1
        )
        if conv:
            return conv, False
    name = (title_hint or "New chat").strip()[:CONVERSATION_NAME_LENGTH] or "New chat"
    return Conversation.create({"user_id": user.id, "name": name}), True


def _generate_conversation_title(client, message, reply_text):
    """Ask a small/cheap model to name the conversation from its first
    exchange. Best-effort: any failure just keeps the fallback title."""
    prompt = message or "(file attachment)"
    try:
        resp = client.messages.create(
            model=TITLE_MODEL,
            max_tokens=20,
            system=TITLE_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"User: {prompt}\n\nAssistant: {reply_text[:500]}",
                }
            ],
        )
        title = (
            "".join(block.text for block in resp.content if block.type == "text")
            .strip()
            .strip('"')
            .strip()
        )
        return title or None
    except Exception:
        _logger.warning("AI chat: failed to generate conversation title", exc_info=True)
        return None


def _load_history(env, conversation_id):
    rows = env["mcp.chat.message"].search(
        [("conversation_id", "=", conversation_id)],
        order="id desc",
        limit=MAX_HISTORY_MESSAGES,
    )
    rows = rows[::-1]
    return [{"role": r.role, "content": json.loads(r.content)} for r in rows]


def _persist(env, user, conversation, role, content):
    message = env["mcp.chat.message"].create(
        {
            "user_id": user.id,
            "conversation_id": conversation.id,
            "role": role,
            "content": json.dumps(content),
        }
    )
    conversation.last_message_date = fields.Datetime.now()
    return message


def _build_user_content(message, attachments):
    """Return (content, error). `content` is either a plain string (no
    attachments) or a list of Claude content blocks (attachments + text)."""
    attachments = attachments or []
    if not attachments:
        return message, None

    if len(attachments) > MAX_ATTACHMENTS_PER_MESSAGE:
        return None, f"Too many files (max {MAX_ATTACHMENTS_PER_MESSAGE} per message)."

    blocks = []
    for attachment in attachments:
        filename = attachment.get("filename") or "file"
        mimetype = (attachment.get("mimetype") or "").lower()
        data = attachment.get("data") or ""
        # tolerate a full data: URL if the client forgot to strip the prefix
        if data.startswith("data:") and "," in data:
            data = data.split(",", 1)[1]

        if len(data) > MAX_ATTACHMENT_B64_CHARS:
            return None, f"'{filename}' is too large (max {MAX_ATTACHMENT_MB} MB)."

        if mimetype in SUPPORTED_IMAGE_TYPES:
            blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mimetype, "data": data},
                }
            )
        elif mimetype == "application/pdf":
            blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": data,
                    },
                }
            )
        else:
            return None, (
                f"Unsupported file type for '{filename}' ({mimetype or 'unknown'}). "
                "Only images (PNG/JPEG/GIF/WEBP) and PDF are supported."
            )

    if message:
        text = message
    else:
        names = ", ".join(a.get("filename") or "file" for a in attachments)
        plural = "s" if len(attachments) != 1 else ""
        text = f"(Attached {len(attachments)} file{plural}: {names})"
    blocks.append({"type": "text", "text": text})
    return blocks, None


def _attachment_link(attachment):
    return {
        "filename": attachment.name,
        "url": f"/web/content/{attachment.id}?download=true&filename={quote(attachment.name or 'file')}",
    }


def _rows_to_display(rows):
    """Rebuild display bubbles (role/text/files) from persisted rows,
    matching the live turn's shape: one bubble per assistant text block
    (generated-file attachments riding on the last one), one small 'tool'
    bubble per tool call. Raw tool_result payloads are internal and
    skipped.
    """
    files_by_message = {}
    if rows:
        attachments = rows.env["ir.attachment"].search(
            [("res_model", "=", "mcp.chat.message"), ("res_id", "in", rows.ids)]
        )
        for att in attachments:
            files_by_message.setdefault(att.res_id, []).append(_attachment_link(att))

    messages = []
    for row in rows:
        content = json.loads(row.content)
        if row.role == "user":
            if isinstance(content, str):
                messages.append({"role": "user", "text": content})
            elif isinstance(content, list):
                attachment_count = sum(
                    1
                    for b in content
                    if isinstance(b, dict) and b.get("type") in ("image", "document")
                )
                if attachment_count:
                    text = "\n".join(
                        b["text"]
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                    label = (
                        "📎 attachment"
                        if attachment_count == 1
                        else f"📎 {attachment_count} attachments"
                    )
                    messages.append(
                        {"role": "user", "text": (text + "\n" + label).strip()}
                    )
        elif row.role == "assistant":
            row_files = files_by_message.get(row.id, [])
            text_blocks = [
                b
                for b in content
                if b.get("type") == "text" and b.get("text", "").strip()
            ]
            for b in content:
                if b.get("type") == "tool_use":
                    messages.append(
                        {"role": "tool", "text": f"🔧 {b.get('name')}"}
                    )
            if text_blocks:
                for i, b in enumerate(text_blocks):
                    is_last = i == len(text_blocks) - 1
                    messages.append(
                        {
                            "role": "assistant",
                            "text": b["text"],
                            "files": row_files if is_last else [],
                        }
                    )
            elif row_files:
                messages.append({"role": "assistant", "text": "", "files": row_files})
    return messages


class McpChatController(http.Controller):
    _name = "mcp.chat.controller"

    @http.route("/mcp/chat/conversations", type="json", auth="user")
    def list_conversations(self, **kwargs):
        env = request.env
        conversations = env["mcp.chat.conversation"].search(
            [("user_id", "=", env.user.id)]
        )
        return {
            "conversations": [
                {
                    "id": c.id,
                    "name": c.name,
                    "last_message_date": str(c.last_message_date or ""),
                }
                for c in conversations
            ]
        }

    @http.route("/mcp/chat/conversation/delete", type="json", auth="user")
    def delete_conversation(self, conversation_id=None, **kwargs):
        env = request.env
        if conversation_id:
            env["mcp.chat.conversation"].search(
                [("id", "=", conversation_id), ("user_id", "=", env.user.id)]
            ).unlink()
        return {"ok": True}

    @http.route("/mcp/chat/history", type="json", auth="user")
    def get_history(self, conversation_id=None, **kwargs):
        env = request.env
        if not conversation_id:
            return {"messages": []}
        rows = env["mcp.chat.message"].search(
            [
                ("conversation_id", "=", conversation_id),
                ("user_id", "=", env.user.id),
            ],
            order="id asc",
            limit=MAX_HISTORY_MESSAGES,
        )
        return {"messages": _rows_to_display(rows)}

    @http.route("/mcp/chat/send", type="json", auth="user")
    def send(self, message=None, attachments=None, conversation_id=None, **kwargs):
        env = request.env
        user = env.user

        if not utils.is_mcp_enabled():
            return {"error": "MCP Server is disabled globally."}

        rate_limiting_enabled = (
            env["ir.config_parameter"]
            .sudo()
            .get_param("mcp_server.enable_rate_limiting", "True")
            == "True"
        )
        if (
            rate_limiting_enabled
            and get_request_limit()
            and not check_rate_limit(user.id)
        ):
            env["mcp.log"].sudo().log_rate_limit_exceeded(
                user_id=user.id, endpoint=request.httprequest.path
            )
            return {"error": "Too many requests. Please try again in a moment."}
        if rate_limiting_enabled:
            record_api_request(user.id)

        if (
            env["ir.config_parameter"].sudo().get_param("mcp_server.chat_enabled")
            != "True"
        ):
            return {
                "error": "AI chat is disabled. Enable it under Settings > MCP Server."
            }

        if not HAS_ANTHROPIC:
            return {
                "error": "The 'anthropic' Python package is not installed on the server."
            }

        if not message and not attachments:
            return {"error": "message is required."}

        client, model = _get_client_and_model()
        if client is None:
            return {
                "error": "Anthropic API key is not configured. "
                "Set it under Settings > MCP Server."
            }

        user_content, attachment_error = _build_user_content(message or "", attachments)
        if attachment_error:
            return {"error": attachment_error}

        title_hint = message or ", ".join(
            a.get("filename") or "file" for a in (attachments or [])
        )
        conversation, is_new_conversation = _get_or_create_conversation(
            env, user, conversation_id, title_hint
        )

        history = _load_history(env, conversation.id)
        history.append({"role": "user", "content": user_content})
        _persist(env, user, conversation, "user", user_content)

        tools = build_tool_definitions(env) + FILE_GENERATION_TOOLS
        tool_activity = []
        response_files = []
        response = None

        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                response = client.beta.messages.create(
                    model=model,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=history,
                    betas=FILE_GENERATION_BETAS,
                    container={"skills": FILE_GENERATION_SKILLS},
                )

                iteration_files = _extract_generated_files(client, response)

                assistant_content = _serialize_content(response.content)
                history.append({"role": "assistant", "content": assistant_content})
                assistant_message = _persist(
                    env, user, conversation, "assistant", assistant_content
                )

                for file_info in iteration_files:
                    try:
                        response_files.append(
                            _save_attachment(env, file_info, assistant_message)
                        )
                    except Exception:
                        _logger.exception(
                            "AI chat: failed to save generated file as an attachment"
                        )

                if response.stop_reason == "pause_turn":
                    # server-side tool loop (code execution) hit its
                    # internal iteration cap - resend as-is to resume,
                    # no extra user message needed.
                    continue
                if response.stop_reason != "tool_use":
                    break

                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    result, is_error = execute_tool(
                        env, user, block.name, block.input or {}
                    )
                    tool_activity.append(
                        {"name": block.name, "input": block.input, "is_error": is_error}
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(_json_safe(result)),
                            "is_error": is_error,
                        }
                    )
                history.append({"role": "user", "content": tool_results})
                _persist(env, user, conversation, "user", tool_results)
            else:
                _logger.warning(
                    "AI chat: hit MAX_TOOL_ITERATIONS for user %s", user.id
                )
        except Exception as exc:  # noqa: BLE001 - surfaced to the chat UI, not raised
            _logger.exception("AI chat: Claude API call failed")
            return {"error": f"Claude API error: {exc}"}

        reply_text = "\n".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        if not reply_text:
            reply_text = (
                "I had to stop after several tool calls without a final answer. "
                "Please try rephrasing your request."
            )

        if is_new_conversation:
            title = _generate_conversation_title(client, message, reply_text)
            if title:
                conversation.name = title[:CONVERSATION_NAME_LENGTH]

        return {
            "reply": reply_text,
            "tool_calls": tool_activity,
            "conversation_id": conversation.id,
            "files": response_files,
        }


def _serialize_content(content_blocks):
    """Turn SDK content blocks into plain JSON-safe dicts for storage/replay."""
    blocks = []
    for block in content_blocks:
        if block.type == "text":
            blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
        elif block.type == "thinking":
            continue  # never replay reasoning
        else:
            # Server-tool blocks (code execution, etc.) - keep them so
            # Claude retains context on the next request in this same turn.
            try:
                blocks.append(block.model_dump(mode="json"))
            except Exception:  # noqa: BLE001 - unknown/unserializable block
                continue
    return blocks


def _json_safe(value):
    return json.loads(json.dumps(value, default=str))


def _extract_generated_files(client, response):
    """Download any files Claude created via code execution in this
    response. Best-effort: a download failure just means no link for that
    file, never a broken chat turn."""
    files = []
    for block in getattr(response, "content", []):
        if block.type != "bash_code_execution_tool_result":
            continue
        result = getattr(block, "content", None)
        if result is None or getattr(result, "type", None) != "bash_code_execution_result":
            continue
        for item in getattr(result, "content", None) or []:
            if getattr(item, "type", None) != "bash_code_execution_output":
                continue
            file_id = getattr(item, "file_id", None)
            if not file_id:
                continue
            try:
                metadata = client.beta.files.retrieve_metadata(file_id)
                downloaded = client.beta.files.download(file_id)
                tmp_path = tempfile.mktemp()
                try:
                    downloaded.write_to_file(tmp_path)
                    with open(tmp_path, "rb") as f:
                        data = f.read()
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                files.append(
                    {
                        "filename": metadata.filename,
                        "mimetype": getattr(metadata, "mime_type", None)
                        or "application/octet-stream",
                        "data": data,
                    }
                )
            except Exception:
                _logger.exception(
                    "AI chat: failed to download generated file %s", file_id
                )
    return files


def _save_attachment(env, file_info, message):
    """Save a generated file as an Odoo attachment linked to the specific
    chat message that produced it, so it shows up as a file card in that
    same turn now AND still appears there on a later page reload.

    Uses sudo() only for this create - mcp.chat.message intentionally has
    no write access for regular users (messages are an immutable log), and
    generated-file attachments are system output, not user-authored data.
    Read-time access is still correctly scoped: ir.attachment resolves
    access for a res_model/res_id-linked record through that record's own
    rules, and `rule_mcp_chat_message_user` restricts messages (and so
    their attachments) to their owning user.
    """
    attachment = env["ir.attachment"].sudo().create(
        {
            "name": file_info["filename"],
            "datas": base64.b64encode(file_info["data"]),
            "mimetype": file_info["mimetype"],
            "res_model": "mcp.chat.message",
            "res_id": message.id,
        }
    )
    return _attachment_link(attachment)
