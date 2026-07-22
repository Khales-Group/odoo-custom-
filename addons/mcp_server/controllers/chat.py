"""In-system AI chat controller (Claude), backed by the MCP tool layer."""

import json
import logging

from odoo import http
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
MAX_TOKENS = 4096

SYSTEM_PROMPT = (
    "You are an AI assistant embedded inside this company's Odoo system. "
    "You can look up, create, update, and delete Odoo records ONLY through "
    "the tools provided - never claim to have done something you didn't do "
    "through a tool call. If a tool call fails or is denied, tell the user "
    "plainly what happened (e.g. permission not enabled) rather than making "
    "up a result. Call list_enabled_models if you are not sure what data you "
    "can access. Reply in the same language the user's latest message is "
    "written in (Arabic or English). Be concise and to the point."
)


def _get_client_and_model():
    params = request.env["ir.config_parameter"].sudo()
    api_key = params.get_param("mcp_server.anthropic_api_key")
    model = params.get_param("mcp_server.anthropic_model", "claude-opus-4-8")
    if not api_key:
        return None, model
    return anthropic.Anthropic(api_key=api_key), model


class McpChatController(http.Controller):
    _name = "mcp.chat.controller"

    @http.route("/mcp/chat/send", type="json", auth="user")
    def send(self, message=None, messages=None, **kwargs):
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
        if rate_limiting_enabled and get_request_limit() and not check_rate_limit(
            user.id
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

        if not message:
            return {"error": "message is required."}

        client, model = _get_client_and_model()
        if client is None:
            return {
                "error": "Anthropic API key is not configured. "
                "Set it under Settings > MCP Server."
            }

        history = list(messages or [])
        history.append({"role": "user", "content": message})

        tools = build_tool_definitions(env)
        tool_activity = []
        response = None

        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                response = client.messages.create(
                    model=model,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=history,
                )

                history.append(
                    {
                        "role": "assistant",
                        "content": _serialize_content(response.content),
                    }
                )

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
                            "content": _json_safe(result),
                            "is_error": is_error,
                        }
                    )
                history.append({"role": "user", "content": tool_results})
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

        return {
            "reply": reply_text,
            "messages": history,
            "tool_calls": tool_activity,
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
        # thinking / other block types are intentionally dropped from history
    return blocks


def _json_safe(value):
    return json.loads(json.dumps(value, default=str))
