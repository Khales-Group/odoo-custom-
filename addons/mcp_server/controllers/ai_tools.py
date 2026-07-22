"""Tool definitions and dispatcher for the in-system AI chat (Claude).

Generic tools (search/create/write/unlink) are auto-generated from whatever
models are switched on in Settings > MCP Server > Enabled Models, so adding a
new capability is normally just enabling a model there - no code needed.

For bespoke, multi-step actions (e.g. "create an RFQ and email the vendor"),
register a custom tool with @register_tool below.
"""

import json
import logging

from odoo.exceptions import AccessError, UserError, ValidationError

from . import utils

_logger = logging.getLogger(__name__)

MAX_LIMIT = 200
DEFAULT_LIMIT = 20


class ToolError(Exception):
    """Raised for tool-input problems that should be reported back to Claude
    (as a tool error) instead of crashing the whole chat request."""


# ---------------------------------------------------------------------------
# Custom tool registry (empty by default - extend here as needed)
# ---------------------------------------------------------------------------

CUSTOM_TOOLS = {}


def register_tool(name, description, input_schema):
    """Decorator to register a custom tool.

    The decorated function receives (env, user, tool_input) and must return
    a JSON-serializable value.

    Example:
        @register_tool(
            "create_rfq",
            "Create a Request for Quotation for a vendor.",
            {
                "type": "object",
                "properties": {
                    "vendor_name": {"type": "string"},
                    "product_names": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["vendor_name", "product_names"],
            },
        )
        def _tool_create_rfq(env, user, tool_input):
            ...
    """

    def decorator(func):
        CUSTOM_TOOLS[name] = {
            "description": description,
            "input_schema": input_schema,
            "handler": func,
        }
        return func

    return decorator


# ---------------------------------------------------------------------------
# Generic CRUD tool schemas
# ---------------------------------------------------------------------------

_GENERIC_TOOLS = {
    "list_enabled_models": {
        "description": (
            "List the Odoo models this assistant is allowed to work with, "
            "and which operations (read/create/write/unlink) are enabled "
            "for each. Call this first if unsure what is available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "search_records": {
        "description": (
            "Search/read records of an enabled Odoo model. Use this for any "
            "'find', 'search', 'show', 'list' style request."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": (
                        "Technical model name, e.g. 'res.partner'. Must be "
                        "one of the enabled models (see list_enabled_models)."
                    ),
                },
                "domain": {
                    "type": "string",
                    "description": (
                        "Optional Odoo domain filter as a JSON string, e.g. "
                        '\'[["name", "ilike", "acme"]]\'. Omit for no filter.'
                    ),
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Fields to return. Omit to get id and display_name only."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": f"Max records to return (default {DEFAULT_LIMIT}, max {MAX_LIMIT}).",
                },
                "order": {
                    "type": "string",
                    "description": "Sort order, e.g. 'create_date desc'.",
                },
            },
            "required": ["model"],
        },
    },
    "create_record": {
        "description": "Create a new record of an enabled Odoo model.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "values": {
                    "type": "object",
                    "description": "Field values for the new record.",
                },
            },
            "required": ["model", "values"],
        },
    },
    "write_record": {
        "description": "Update one or more existing records of an enabled Odoo model.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "integer"}},
                "values": {"type": "object", "description": "Field values to set."},
            },
            "required": ["model", "ids", "values"],
        },
    },
    "unlink_record": {
        "description": (
            "Permanently delete one or more records of an enabled Odoo model. "
            "Only use when the user explicitly asks to delete/remove records."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["model", "ids"],
        },
    },
}


def build_tool_definitions(env):
    """Build the Claude `tools` array: generic CRUD tools + any registered
    custom tools. Generic tools are always declared (even with zero enabled
    models) so the model can discover availability via list_enabled_models."""
    tools = [
        {"name": name, "description": spec["description"], "input_schema": spec["input_schema"]}
        for name, spec in _GENERIC_TOOLS.items()
    ]
    tools += [
        {"name": name, "description": spec["description"], "input_schema": spec["input_schema"]}
        for name, spec in CUSTOM_TOOLS.items()
    ]
    return tools


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def _require_model_operation(env, model_name, operation):
    model_name = utils.sanitize_model_name(model_name)
    if not utils.check_model_operation_allowed(env, model_name, operation):
        raise ToolError(
            f"Operation '{operation}' on model '{model_name}' is not allowed. "
            "Ask an administrator to enable it under Settings > MCP Server > "
            "Enabled Models."
        )
    return model_name


def _parse_domain(domain_str):
    if not domain_str:
        return []
    try:
        domain = json.loads(domain_str)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"Invalid domain JSON: {exc}") from exc
    if not isinstance(domain, list):
        raise ToolError("domain must be a JSON list of triplets.")
    return domain


def _tool_list_enabled_models(env, user, tool_input):
    models = utils.get_enabled_models(env)
    for m in models:
        m["operations"] = utils.get_model_allowed_operations(env, m["model"])
    return {"models": models}


def _tool_search_records(env, user, tool_input):
    model_name = _require_model_operation(env, tool_input.get("model"), "read")
    domain = _parse_domain(tool_input.get("domain"))
    fields = tool_input.get("fields") or ["display_name"]
    limit = min(int(tool_input.get("limit") or DEFAULT_LIMIT), MAX_LIMIT)
    order = tool_input.get("order") or False

    records = env[model_name].search_read(
        domain, fields=fields, limit=limit, order=order
    )
    return {"count": len(records), "records": records}


def _tool_create_record(env, user, tool_input):
    model_name = _require_model_operation(env, tool_input.get("model"), "create")
    values = tool_input.get("values") or {}
    if not isinstance(values, dict):
        raise ToolError("values must be a JSON object.")
    record = env[model_name].create(values)
    return {"id": record.id, "display_name": record.display_name}


def _tool_write_record(env, user, tool_input):
    model_name = _require_model_operation(env, tool_input.get("model"), "write")
    ids = tool_input.get("ids") or []
    values = tool_input.get("values") or {}
    if not isinstance(values, dict):
        raise ToolError("values must be a JSON object.")
    if not ids:
        raise ToolError("ids must be a non-empty list of record IDs.")
    env[model_name].browse(ids).write(values)
    return {"updated_ids": ids}


def _tool_unlink_record(env, user, tool_input):
    model_name = _require_model_operation(env, tool_input.get("model"), "unlink")
    ids = tool_input.get("ids") or []
    if not ids:
        raise ToolError("ids must be a non-empty list of record IDs.")
    env[model_name].browse(ids).unlink()
    return {"deleted_ids": ids}


_GENERIC_HANDLERS = {
    "list_enabled_models": _tool_list_enabled_models,
    "search_records": _tool_search_records,
    "create_record": _tool_create_record,
    "write_record": _tool_write_record,
    "unlink_record": _tool_unlink_record,
}


def execute_tool(env, user, name, tool_input):
    """Run a tool call. Returns (result_dict, is_error).

    `env` must be the requesting user's own environment (not sudo) so
    Odoo's normal access rights and record rules apply on top of the
    MCP Enabled Models allowlist.
    """
    handler = _GENERIC_HANDLERS.get(name)
    operation = None
    model_name = tool_input.get("model") if isinstance(tool_input, dict) else None

    if handler is None:
        custom = CUSTOM_TOOLS.get(name)
        if custom is None:
            return {"error": f"Unknown tool: {name}"}, True
        handler = custom["handler"]

    try:
        result = handler(env, user, tool_input)
        if model_name:
            env["mcp.log"].sudo().log_model_access(
                model_name=model_name,
                operation=name,
                user_id=user.id,
            )
        return result, False
    except ToolError as exc:
        return {"error": str(exc)}, True
    except (AccessError, UserError, ValidationError) as exc:
        env["mcp.log"].sudo().log_permission_denied(
            model_name=model_name or name,
            operation=name,
            user_id=user.id,
            error_message=str(exc),
        )
        return {"error": str(exc)}, True
    except Exception as exc:  # noqa: BLE001 - reported back to Claude, not raised
        _logger.exception("AI chat tool '%s' failed", name)
        env["mcp.log"].sudo().log_error(
            error_message=str(exc),
            model_name=model_name or name,
            operation=name,
            user_id=user.id,
        )
        return {"error": f"Tool execution failed: {exc}"}, True
