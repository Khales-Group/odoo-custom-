"""Gemini backend for the in-system AI chat (Settings > MCP Server > Chat
Provider = Gemini).

Same tools, permissions and conversation storage as the Claude backend in
chat.py: turns are persisted in the same Claude-style message format, so a
conversation can carry on whichever provider is selected. Not available
with Gemini: Claude's PDF/Word/Excel/PowerPoint file generation.

The API key is the shared `gemini.api.key` system parameter (also used by
kh_ai_backport); the model is `mcp_server.gemini_model`, else `gemini.model`.
"""

import base64
import json
import logging
import uuid

from .ai_tools import build_tool_definitions, execute_tool
from .chat import (
    CONVERSATION_NAME_LENGTH,
    MAX_TOOL_ITERATIONS,
    TITLE_SYSTEM_PROMPT,
    _build_system_prompt,
    _json_safe,
    _persist,
)

_logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types

    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def get_client_and_model(env):
    params = env["ir.config_parameter"].sudo()
    api_key = params.get_param("gemini.api.key")
    model = (
        params.get_param("mcp_server.gemini_model")
        or params.get_param("gemini.model")
        or DEFAULT_GEMINI_MODEL
    )
    if not api_key:
        return None, model
    return genai.Client(api_key=api_key), model


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _to_schema(js):
    """JSON schema -> types.Schema, for google-genai versions without
    `parameters_json_schema`. Gemini can't declare a free-form object there,
    so such a parameter is taken as a JSON string (decoded in _plain_args)."""
    kind = js.get("type", "string")
    if kind == "object" and not js.get("properties"):
        description = (js.get("description", "") + " (a JSON object, as a string)").strip()
        return types.Schema(type="STRING", description=description)
    kwargs = {"type": kind.upper()}
    if js.get("description"):
        kwargs["description"] = js["description"]
    if js.get("enum"):
        kwargs["enum"] = [str(v) for v in js["enum"]]
    if kind == "array":
        kwargs["items"] = _to_schema(js.get("items") or {"type": "string"})
    if kind == "object":
        kwargs["properties"] = {k: _to_schema(v) for k, v in js["properties"].items()}
        if js.get("required"):
            kwargs["required"] = js["required"]
    return types.Schema(**kwargs)


def _function_declarations(env):
    declarations = []
    for tool in build_tool_definitions(env):
        try:
            declaration = types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters_json_schema=tool["input_schema"],
            )
        except (TypeError, ValueError):  # older google-genai
            declaration = types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=_to_schema(tool["input_schema"]),
            )
        declarations.append(declaration)
    return declarations


def _plain_args(value):
    """Gemini sends every number as a float (5.0 for an id) and, with the
    old-SDK fallback, free-form objects as JSON strings - give the tools
    what they expect."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _plain_args(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_args(v) for v in value]
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            return _plain_args(json.loads(value))
        except ValueError:
            return value
    return value


# ---------------------------------------------------------------------------
# History (stored Claude-style) -> Gemini contents
# ---------------------------------------------------------------------------


def _tool_response(content):
    try:
        return {"result": json.loads(content)}
    except (TypeError, ValueError):
        return {"result": content}


def _history_to_contents(history):
    blocks_per_message = [
        [{"type": "text", "text": m["content"]}] if isinstance(m["content"], str) else m["content"]
        for m in history
    ]
    all_blocks = [b for blocks in blocks_per_message for b in blocks if isinstance(b, dict)]
    # Only pairs Gemini can follow: a call whose result is stored, and a
    # result whose call is still in the (possibly truncated) history.
    answered = {b.get("tool_use_id") for b in all_blocks if b.get("type") == "tool_result"}
    names = {b["id"]: b["name"] for b in all_blocks if b.get("type") == "tool_use" and b.get("id") in answered}

    contents = []
    for message, blocks in zip(history, blocks_per_message):
        parts = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            source = block.get("source") or {}
            if kind == "text" and block.get("text"):
                parts.append(types.Part.from_text(text=block["text"]))
            elif kind in ("image", "document") and source.get("type") == "base64":
                parts.append(types.Part.from_bytes(
                    data=base64.b64decode(source["data"]), mime_type=source["media_type"],
                ))
            elif kind == "tool_use" and block.get("id") in names:
                parts.append(types.Part.from_function_call(name=block["name"], args=block.get("input") or {}))
            elif kind == "tool_result" and block.get("tool_use_id") in names:
                parts.append(types.Part.from_function_response(
                    name=names[block["tool_use_id"]], response=_tool_response(block.get("content")),
                ))
            # anything else (Claude's code-execution blocks...) has no Gemini equivalent
        if parts:
            role = "model" if message["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=parts))
    return contents


# ---------------------------------------------------------------------------
# One chat turn
# ---------------------------------------------------------------------------


def _generate_title(client, model, message, reply_text):
    try:
        response = client.models.generate_content(
            model=model,
            contents=f"User: {message or '(file attachment)'}\n\nAssistant: {reply_text[:500]}",
            config=types.GenerateContentConfig(system_instruction=TITLE_SYSTEM_PROMPT),
        )
        return (response.text or "").strip().strip('"').strip() or None
    except Exception:
        _logger.warning("AI chat (Gemini): failed to generate conversation title", exc_info=True)
        return None


def run_turn(env, user, conversation, is_new_conversation, message, history, client, model):
    """Answer the user's latest message (already in `history` and stored),
    running tool calls until Gemini gives a final answer. Returns the same
    dict as the Claude path in chat.py."""
    config = types.GenerateContentConfig(
        system_instruction=_build_system_prompt(user, can_generate_files=False),
        tools=[types.Tool(function_declarations=_function_declarations(env))],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = _history_to_contents(history)
    tool_activity = []
    reply_text = ""

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            response = client.models.generate_content(model=model, contents=contents, config=config)
            candidate = response.candidates[0] if response.candidates else None
            if candidate is None or candidate.content is None:
                break
            # Appended as received: it carries Gemini's thought signatures,
            # which it requires back with the function calls of this turn.
            contents.append(candidate.content)
            parts = candidate.content.parts or []
            texts = [p.text for p in parts if p.text and not getattr(p, "thought", False)]
            calls = [p.function_call for p in parts if p.function_call]

            blocks = [{"type": "text", "text": text} for text in texts]
            call_ids = [f"gemini_{uuid.uuid4().hex[:24]}" for _call in calls]
            call_args = [_plain_args(dict(call.args or {})) for call in calls]
            blocks += [
                {"type": "tool_use", "id": call_id, "name": call.name, "input": args}
                for call, call_id, args in zip(calls, call_ids, call_args)
            ]
            if blocks:
                _persist(env, user, conversation, "assistant", blocks)
            if texts:
                reply_text = "\n".join(texts).strip()
            if not calls:
                break

            tool_results, response_parts = [], []
            for call, call_id, args in zip(calls, call_ids, call_args):
                result, is_error = execute_tool(env, user, call.name, args)
                tool_activity.append({"name": call.name, "input": args, "is_error": is_error})
                result = _json_safe(result)
                tool_results.append({
                    "type": "tool_result", "tool_use_id": call_id,
                    "content": json.dumps(result), "is_error": is_error,
                })
                response_parts.append(types.Part.from_function_response(name=call.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=response_parts))
            _persist(env, user, conversation, "user", tool_results)
        else:
            _logger.warning("AI chat (Gemini): hit MAX_TOOL_ITERATIONS for user %s", user.id)
    except Exception as exc:  # noqa: BLE001 - surfaced to the chat UI, not raised
        _logger.exception("AI chat: Gemini API call failed")
        return {"error": f"Gemini API error: {exc}"}

    if not reply_text:
        reply_text = (
            "I had to stop after several tool calls without a final answer. "
            "Please try rephrasing your request."
        )
    if is_new_conversation:
        title = _generate_title(client, model, message, reply_text)
        if title:
            conversation.name = title[:CONVERSATION_NAME_LENGTH]

    return {
        "reply": reply_text,
        "tool_calls": tool_activity,
        "conversation_id": conversation.id,
        "files": [],
    }
