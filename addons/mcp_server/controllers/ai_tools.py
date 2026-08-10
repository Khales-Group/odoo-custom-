"""Tool definitions and dispatcher for the in-system AI chat (Claude).

Generic tools (search/create/write/unlink) are auto-generated from whatever
models are switched on in Settings > MCP Server > Enabled Models, so adding a
new capability is normally just enabling a model there - no code needed.

For bespoke, multi-step actions (e.g. "create an RFQ and email the vendor"),
register a custom tool with @register_tool below.
"""

import json
import logging
import re

from odoo.exceptions import AccessError, UserError, ValidationError

from . import utils

_logger = logging.getLogger(__name__)

MAX_LIMIT = 200
DEFAULT_LIMIT = 20

# Every operation (read/create/write/unlink) on every model - including
# accounting, payroll, and POS - is gated by the SAME two checks: an admin
# must explicitly enable the model under Settings > MCP Server > Enabled
# Models, AND the calling user must personally have real Odoo access to it
# for that operation (see _user_can below). Permissions come from the user's
# own Odoo access, not from a blanket ban on the assistant - an accountant
# who can edit invoices in Odoo can do the same through the AI chat.
#
# res.partner.bank is the one exception: bank account numbers/IBANs are
# blocked outright, even for read, regardless of the user's own access.
HARD_BLOCKED_MODELS = {
    "res.partner.bank",  # partner bank account numbers/IBANs - blocked outright, even for read
}


def is_hard_blocked_model(model_name, operation):
    return model_name in HARD_BLOCKED_MODELS


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
    if is_hard_blocked_model(model_name, operation):
        raise ToolError(
            f"Model '{model_name}' is permanently blocked from the AI chat "
            "(bank account/IBAN data), even for read. This cannot be enabled "
            "from Settings - it requires a code change."
        )
    if not utils.check_model_operation_allowed(env, model_name, operation):
        raise ToolError(
            f"Operation '{operation}' on model '{model_name}' is not allowed. "
            "Ask an administrator to enable it under Settings > MCP Server > "
            "Enabled Models."
        )
    if not _user_can(env, model_name, operation):
        raise ToolError(
            f"You personally don't have '{operation}' permission on "
            f"'{model_name}' in Odoo - this is your own access level, not a "
            "chat restriction. Ask your Odoo administrator to grant it if "
            "you need it."
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


def _user_can(env, model_name, operation):
    """Does the CALLING user's own Odoo access rights (not the system-wide
    MCP switch) allow this operation? Uses has_access(), which accounts for
    both model-level access rights and record rules. Fails closed: any
    error is treated as "no access", never "yes"."""
    try:
        return bool(env[model_name].has_access(operation))
    except Exception:  # noqa: BLE001 - unknown model/operation -> treat as blocked
        return False


def _split_search_words(keyword):
    words = [w for w in re.split(r"\s+", (keyword or "").strip()) if len(w) > 1]
    return words or ([keyword.strip()] if keyword and keyword.strip() else [])


def _name_match_score(name, words):
    name_lower = (name or "").lower()
    return sum(1 for w in words if w.lower() in name_lower)


def _fuzzy_name_search(env, model_name, keyword, fields, extra_domain=None, limit=10):
    """Search `model_name` by name, tolerant of extra middle words and
    partial/misspelled matches - e.g. "Tamim Alkindi" finding "Tameim Majed
    Salem Saif Alkindi" (an extra middle name, and no full-phrase match).
    Splits the keyword into words, matches records containing ANY of them
    (not requiring the whole phrase as one contiguous substring), then
    ranks by how many words actually matched so the best guess comes
    first instead of being missed entirely."""
    words = _split_search_words(keyword)
    if not words:
        return []

    if len(words) == 1:
        name_domain = [("name", "ilike", words[0])]
    else:
        name_domain = ["|"] * (len(words) - 1) + [
            ("name", "ilike", w) for w in words
        ]
    domain = (extra_domain or []) + name_domain

    fields = list(dict.fromkeys(list(fields) + ["name"]))
    records = env[model_name].search_read(
        domain, fields=fields, limit=max(limit * 3, 30)
    )
    for r in records:
        r["_match_score"] = _name_match_score(r.get("name"), words)
    records.sort(key=lambda r: r["_match_score"], reverse=True)
    return records[:limit]


def _tool_list_enabled_models(env, user, tool_input):
    """List what THIS user can actually do, not just what's switched on
    system-wide: a model only shows up here if it is both (a) enabled under
    Settings > MCP Server > Enabled Models AND (b) actually readable by the
    calling user's own Odoo permissions - same access they'd have anywhere
    else in Odoo, not broadened by the AI chat."""
    models = []
    for m in utils.get_enabled_models(env):
        model_name = m["model"]
        if model_name in HARD_BLOCKED_MODELS:
            continue
        system_ops = utils.get_model_allowed_operations(env, model_name)
        user_ops = {
            op: allowed and _user_can(env, model_name, op)
            for op, allowed in system_ops.items()
        }
        if any(user_ops.values()):
            models.append(
                {"model": model_name, "name": m["name"], "operations": user_ops}
            )
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


def _ensure_calendar_attendee(values, user):
    """Guarantee the requesting user is an attendee on any calendar.event
    created via the AI chat, so it actually shows up on their calendar -
    regardless of whether the model remembered to add it. Enforced here in
    code, not just asked for in the prompt."""
    values = dict(values)
    partner_id = user.partner_id.id
    partner_ids = values.get("partner_ids")

    if not partner_ids:
        values["partner_ids"] = [(6, 0, [partner_id])]
    elif isinstance(partner_ids, list) and isinstance(partner_ids[0], (list, tuple)):
        # already in Many2many command format - just add a link command
        values["partner_ids"] = list(partner_ids) + [(4, partner_id, 0)]
    elif isinstance(partner_ids, list):
        # a plain list of partner IDs
        ids = {int(i) for i in partner_ids}
        ids.add(partner_id)
        values["partner_ids"] = [(6, 0, list(ids))]
    else:
        values["partner_ids"] = [(6, 0, [partner_id])]

    return values


def _tool_create_record(env, user, tool_input):
    model_name = _require_model_operation(env, tool_input.get("model"), "create")
    values = tool_input.get("values") or {}
    if not isinstance(values, dict):
        raise ToolError("values must be a JSON object.")
    if model_name == "calendar.event":
        values = _ensure_calendar_attendee(values, user)
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


# ---------------------------------------------------------------------------
# Custom tool: project status report
# ---------------------------------------------------------------------------

_CLOSED_STAGE_MARKERS = {"done", "approved", "closed", "cancelled", "canceled"}


@register_tool(
    "project_status_report",
    (
        "Build a status report for a project: finds the project by name, "
        "lists its open tasks (excluding tasks whose stage looks like "
        "Done/Approved/Cancelled), and reads recent chatter/log messages "
        "for context. Use this for any 'what's the status of project X' / "
        "'project situation' request instead of searching multiple models "
        "manually - it is more complete and consistent."
    ),
    {
        "type": "object",
        "properties": {
            "project_keyword": {
                "type": "string",
                "description": "Part of the project's name to search for.",
            },
            "chatter_limit": {
                "type": "integer",
                "description": "Max chatter messages to include (default 20, max 50).",
            },
        },
        "required": ["project_keyword"],
    },
)
def _tool_project_status_report(env, user, tool_input):
    from odoo.tools import html2plaintext

    keyword = (tool_input.get("project_keyword") or "").strip()
    if not keyword:
        raise ToolError("project_keyword is required.")

    _require_model_operation(env, "project.project", "read")
    projects = _fuzzy_name_search(env, "project.project", keyword, ["name"], limit=10)
    if not projects:
        return {"error": f"No project found matching '{keyword}'."}

    top_score = projects[0]["_match_score"]
    tied = [p for p in projects if p["_match_score"] == top_score]
    for p in projects:
        p.pop("_match_score", None)
    if len(tied) > 1:
        return {
            "ambiguous": True,
            "candidates": [p["name"] for p in tied],
            "message": "Multiple projects match equally well - ask the user which one.",
        }

    project_id = projects[0]["id"]
    project_name = projects[0]["name"]

    _require_model_operation(env, "project.task", "read")
    tasks = env["project.task"].search_read(
        [("project_id", "=", project_id)],
        fields=["name", "stage_id", "user_ids", "date_deadline", "priority"],
        limit=200,
    )
    open_tasks = [
        t
        for t in tasks
        if not (
            t.get("stage_id")
            and str(t["stage_id"][1]).strip().lower() in _CLOSED_STAGE_MARKERS
        )
    ]

    chatter = []
    try:
        _require_model_operation(env, "mail.message", "read")
        limit = min(int(tool_input.get("chatter_limit") or 20), 50)
        messages = env["mail.message"].search_read(
            [("model", "=", "project.project"), ("res_id", "=", project_id)],
            fields=["author_id", "date", "body"],
            order="date desc",
            limit=limit,
        )
        for m in messages:
            text = html2plaintext(m.get("body") or "").strip()
            if text:
                chatter.append(
                    {
                        "author": m["author_id"][1] if m.get("author_id") else "",
                        "date": str(m.get("date") or ""),
                        "text": text[:1000],
                    }
                )
    except ToolError:
        pass  # mail.message not enabled - report on tasks only

    return {
        "project": project_name,
        "total_task_count": len(tasks),
        "open_task_count": len(open_tasks),
        "open_tasks": open_tasks,
        "chatter": chatter,
    }


# ---------------------------------------------------------------------------
# Custom tool: find a customer even when the name was typed in a different
# language/script than how it's stored (e.g. Arabic vs. the English name on
# file), by cross-referencing records that store the name bilingually.
# ---------------------------------------------------------------------------


@register_tool(
    "find_customer",
    (
        "Find a customer/contact by name. Always use this tool (instead of "
        "search_records) when looking up a customer/contact by name - it "
        "automatically falls back to cross-referencing linked project "
        "names if a direct match isn't found, which matters because a "
        "customer's name may be on file in a different language/script "
        "than how someone asks for it (e.g. only in English, while a "
        "project referencing them is named bilingually)."
    ),
    {
        "type": "object",
        "properties": {
            "name_keyword": {
                "type": "string",
                "description": "The name (or part of it) to search for, in any language.",
            },
        },
        "required": ["name_keyword"],
    },
)
def _tool_find_customer(env, user, tool_input):
    keyword = (tool_input.get("name_keyword") or "").strip()
    if not keyword:
        raise ToolError("name_keyword is required.")

    _require_model_operation(env, "res.partner", "read")
    partners = _fuzzy_name_search(
        env, "res.partner", keyword, ["name", "email", "phone"], limit=10
    )
    for p in partners:
        p.pop("_match_score", None)
    if partners:
        return {"found_via": "res.partner", "customers": partners}

    # Fallback: project names at this company are sometimes bilingual, or
    # carry extra middle names, e.g. "TAMEIM MAJED SALEM SAIF ALKINDI" for
    # someone searched as "Tamim Alkindi" - a name that doesn't match
    # res.partner directly may still be resolvable through a linked project.
    try:
        _require_model_operation(env, "project.project", "read")
    except ToolError:
        return {"error": f"No customer found matching '{keyword}'."}

    projects = _fuzzy_name_search(
        env,
        "project.project",
        keyword,
        ["name", "partner_id"],
        extra_domain=[("partner_id", "!=", False)],
        limit=5,
    )
    if not projects:
        return {"error": f"No customer found matching '{keyword}', even after checking linked projects."}

    partner_ids = list({p["partner_id"][0] for p in projects if p.get("partner_id")})
    customers = env["res.partner"].browse(partner_ids).read(["name", "email", "phone"])
    return {
        "found_via": "project.project (name match)",
        "matched_project": projects[0]["name"],
        "customers": customers,
    }


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
