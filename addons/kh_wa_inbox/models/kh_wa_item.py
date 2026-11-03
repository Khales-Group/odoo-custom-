import base64
import binascii
import hashlib
import uuid
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

from .kh_wa_board import duration_text
from .kh_wa_tools import (
    arabic_age,
    dubai_day_bounds,
    dubai_today,
    mask_vals,
    parse_date,
    parse_utc_datetime,
    phone_index,
    normalize_phone,
    run_batch,
    utc_now,
)

OPEN_STATES = ("open", "waiting")
CLOSED_STATES = ("done", "cancel")
# Once a person changes one of these in Odoo, the bot's later upserts leave
# it alone (the field names are kept in manual_fields).
MANUAL_FIELDS = ("state", "assignee_id", "urgent", "needs_manager", "manager_note")
MASKED_FIELDS = ("source_text", "context_text", "done_note")
LINKABLE_MODELS = ("project.task", "kh.approval.request", "sign.request", "project.site.visit", "crm.lead")
# Values an upsert_items row may carry as they are.
ROW_TEXT_FIELDS = (
    "name", "requester_name", "requester_phone", "done_note",
    "source_text", "context_text", "manager_note",
)
ROW_SELECTION_FIELDS = ("kind", "state", "source_kind")
ROW_BOOLEAN_FIELDS = ("urgent", "needs_manager")
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
DEFAULT_QUICK_DONE_MINUTES = 60
SEARCH_LIMIT = 50
REMIND_DAYS = {"tomorrow": 1, "3days": 3, "next_week": 7}


class KhWaItem(models.Model):
    _name = "kh.wa.item"
    _description = "WhatsApp Notebook Item"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "asked_at desc, id desc"

    name = fields.Char(string="Summary", required=True)
    kind = fields.Selection(
        [
            ("request", "Request"),
            ("decision", "Decision needed"),
            ("deadline", "Deadline"),
            ("alert", "Alert"),
        ],
        default="request",
        required=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("open", "Open"),
            ("waiting", "Waiting for reply"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        default="open",
        required=True,
        index=True,
        tracking=True,
        group_expand="_expand_states",
    )
    urgent = fields.Boolean(index=True)
    needs_manager = fields.Boolean(
        string="Waiting for the Manager", index=True,
        help="Waiting for a decision or reply from the manager.",
    )
    group_id = fields.Many2one(
        "kh.wa.group", string="WhatsApp Group", required=True, ondelete="restrict", index=True,
    )
    group_color = fields.Integer(related="group_id.color", string="Group Color")
    project_id = fields.Many2one("project.project", string="Project", index="btree_not_null")
    partner_id = fields.Many2one("res.partner", string="Contact", index="btree_not_null")
    requester_name = fields.Char(string="Asked By")
    requester_phone = fields.Char(string="Requester Phone", groups="kh_wa_inbox.group_kh_wa_manager")
    requester_user_id = fields.Many2one(
        "res.users", string="Asked By (User)", index="btree_not_null",
        help="The Odoo user who asked, when known. They can see this item.",
    )
    assignee_id = fields.Many2one("res.users", string="Assignee", tracking=True, index="btree_not_null")
    asked_at = fields.Datetime(string="Asked At", required=True, default=fields.Datetime.now, index=True)
    due_date = fields.Date(string="Due Date", index="btree_not_null")
    done_at = fields.Datetime(string="Closed At", index="btree_not_null", copy=False)
    done_note = fields.Char(string="Result", help="One line: what was done.")
    source_msg_id = fields.Char(
        string="Source Message ID", required=True, index=True, copy=False,
        default=lambda self: f"manual-{uuid.uuid4().hex}",
    )
    source_text = fields.Text(string="Original Message")
    context_text = fields.Text(string="Context", help="A few messages around the original one.")
    source_kind = fields.Selection(
        [
            ("text", "Text"),
            ("image", "Image"),
            ("document", "Document"),
            ("voice", "Voice Note"),
        ],
        string="Message Type",
        default="text",
        required=True,
    )
    attachment_ids = fields.Many2many(
        "ir.attachment", "kh_wa_item_attachment_rel", "item_id", "attachment_id", string="Attachments",
    )
    linked_ref = fields.Reference(selection="_selection_linked_ref", string="Linked Record")
    remind_on = fields.Date(string="Remind Me On")
    manager_note = fields.Text(string="Manager Note", groups="kh_wa_inbox.group_kh_wa_manager")
    manual_fields = fields.Char(
        string="Edited in Odoo", readonly=True, copy=False,
        help="Fields changed by a person in Odoo. The bot no longer overwrites them.",
    )
    age_label = fields.Char(string="Age", compute="_compute_age_label")
    is_overdue = fields.Boolean(string="Overdue", compute="_compute_is_overdue", search="_search_is_overdue")

    _source_msg_id_unique = models.Constraint(
        "UNIQUE(source_msg_id)", "This WhatsApp message is already an item in the notebook."
    )

    @api.model
    def _selection_linked_ref(self):
        installed = self.env["ir.model"].sudo().search([("model", "in", LINKABLE_MODELS)])
        names = {m.model: m.name for m in installed}
        return [(model, names[model]) for model in LINKABLE_MODELS if model in names]

    def _expand_states(self, states, domain):
        return [key for key, _label in self._fields["state"].selection]

    def _compute_age_label(self):
        now = utc_now()
        for item in self:
            item.age_label = arabic_age(item.asked_at, now)

    @api.depends("due_date", "state")
    def _compute_is_overdue(self):
        today = dubai_today()
        for item in self:
            item.is_overdue = bool(item.due_date and item.due_date < today and item.state in OPEN_STATES)

    def _search_is_overdue(self, operator, value):
        if operator not in ("in", "not in"):
            return NotImplemented
        today = dubai_today()
        if operator == "in":
            return [("due_date", "<", today), ("state", "in", OPEN_STATES)]
        return ["|", "|", ("due_date", "=", False), ("due_date", ">=", today), ("state", "not in", OPEN_STATES)]

    # ------------------------------------------------------------------
    # CRUD: masking, closing time, edits made by people
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            mask_vals(vals, MASKED_FIELDS)
            if vals.get("state") in CLOSED_STATES and not vals.get("done_at"):
                vals["done_at"] = now
        return super().create(vals_list)

    def write(self, vals):
        vals = mask_vals(dict(vals), MASKED_FIELDS)
        result = super().write(vals)
        if "state" in vals and "done_at" not in vals:
            if vals["state"] in CLOSED_STATES:
                super(KhWaItem, self.filtered(lambda i: not i.done_at)).write({"done_at": fields.Datetime.now()})
            else:
                super(KhWaItem, self.filtered("done_at")).write({"done_at": False})
        touched = {name for name in MANUAL_FIELDS if name in vals}
        if touched and not self.env.context.get("kh_wa_upsert"):
            by_value = defaultdict(lambda: self.browse())
            for item in self:
                by_value[",".join(sorted(item._manual_field_set() | touched))] |= item
            for value, items in by_value.items():
                super(KhWaItem, items).write({"manual_fields": value})
        return result

    def _manual_field_set(self):
        self.ensure_one()
        return {name for name in (self.manual_fields or "").split(",") if name}

    def _is_untouched(self):
        """Nobody has done anything with this item in Odoo yet."""
        self.ensure_one()
        item = self.sudo()
        if item.manual_fields or item.remind_on or item.activity_ids:
            return False
        if self.env["mail.message"].sudo().search_count([
            ("model", "=", self._name), ("res_id", "=", self.id), ("message_type", "in", ("comment", "email")),
        ], limit=1):
            return False
        return not self.env["kh.wa.memo"].sudo().search_count([("item_id", "=", self.id)], limit=1)

    # ------------------------------------------------------------------
    # Buttons (form view and notebook screen)
    # ------------------------------------------------------------------

    def action_done(self, note=None):
        vals = {"state": "done"}
        if note and str(note).strip():
            vals["done_note"] = str(note).strip()
        self.write(vals)
        return True

    def action_waiting(self):
        self.write({"state": "waiting"})
        return True

    def action_reopen(self):
        self.write({"state": "open"})
        return True

    def action_cancel(self):
        self.write({"state": "cancel"})
        return True

    def action_remind(self, when="tomorrow"):
        """Sets remind_on and a To-Do activity for the current user."""
        remind_on = dubai_today() + timedelta(days=REMIND_DAYS.get(when, 1))
        for item in self:
            item.remind_on = remind_on
            item.activity_schedule(
                "mail.mail_activity_data_todo",
                date_deadline=remind_on,
                summary=f"تذكير: {item.name}"[:250],
                user_id=self.env.uid,
            )
        return fields.Date.to_string(remind_on)

    def action_open_linked(self):
        self.ensure_one()
        if not self.linked_ref:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": self.linked_ref._name,
            "res_id": self.linked_ref.id,
            "views": [[False, "form"]],
            "target": "current",
        }

    # ------------------------------------------------------------------
    # XML-RPC API (the WhatsApp bot)
    # ------------------------------------------------------------------

    @api.model
    def _quick_done_minutes(self):
        value = self.env["ir.config_parameter"].sudo().get_param("kh_wa_inbox.quick_done_minutes")
        try:
            return int(value) if value else DEFAULT_QUICK_DONE_MINUTES
        except ValueError:
            return DEFAULT_QUICK_DONE_MINUTES

    @api.model
    def upsert_items(self, rows):
        """Create or update notebook items, keyed by source_msg_id.

        Row: {"source_msg_id"*, "wa_chat_id"* (when new), "name"* (when new),
        "kind", "state", "urgent", "needs_manager", "requester_name",
        "requester_phone", "requester_login", "assignee_login", "asked_at",
        "due_date", "done_at", "done_note", "source_text", "context_text",
        "source_kind", "manager_note", "project_id", "partner_id",
        "linked_ref" ("model,id"), "attachments" ([{"name", "mimetype", "datas"}])}.
        Date-times are UTC ("2026-11-02 06:45:00"), ISO 8601 with an offset,
        or epoch seconds. A key left out is not touched; null clears it.

        A row that is already done, with done_at - asked_at under the
        quick-done threshold (Settings, 60 minutes by default), is not stored:
        it is counted once on its group's day page instead.
        """
        upsert = self.with_context(
            kh_wa_upsert=True,
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
            mail_auto_subscribe_no_notify=True,
        )
        lookup = _RowLookup(self.env)
        threshold = timedelta(minutes=self._quick_done_minutes())
        return run_batch(
            self, rows, lambda row: row.get("source_msg_id"),
            lambda row, warnings: upsert._upsert_item_row(row, warnings, lookup, threshold),
        )

    def _upsert_item_row(self, row, warnings, lookup, threshold):
        key = str(row.get("source_msg_id") or "").strip()
        if not key:
            raise ValueError("source_msg_id is required")
        quick_log = self.env["kh.wa.quick.done"]
        if quick_log.search_count([("source_msg_id", "=", key)], limit=1):
            return False  # already counted as finished within the threshold
        item = self.search([("source_msg_id", "=", key)], limit=1)
        vals = self._row_to_vals(row, warnings, lookup, item)

        asked_at = vals.get("asked_at") or item.asked_at
        done_at = vals.get("done_at")
        quick = (
            vals.get("state") == "done" and asked_at and done_at
            and timedelta(0) <= done_at - asked_at < threshold
        )
        if quick and (not item or item._is_untouched()):
            group = lookup.record_from(vals, "group_id", "kh.wa.group") or item.group_id
            if not group:
                raise ValueError("wa_chat_id is required")
            quick_log._log(key, group, asked_at, done_at)
            item.unlink()
            return False

        attachments = row.get("attachments") or []
        if item:
            manual = item._manual_field_set()
            for name in manual:
                vals.pop(name, None)
            if "state" in manual:
                vals.pop("done_at", None)  # follows the state a person set
            item.write(vals)
        else:
            for name in ("name", "group_id"):
                if not vals.get(name):
                    raise ValueError(f"{'wa_chat_id' if name == 'group_id' else name} is required for a new item")
            group = self.env["kh.wa.group"].browse(vals["group_id"])
            if "project_id" not in vals and group.project_id:
                vals["project_id"] = group.project_id.id
            item = self.create({**vals, "source_msg_id": key})
        if attachments:
            item._attach_files(attachments, warnings)
        return item.id

    def _row_to_vals(self, row, warnings, lookup, item):
        vals = {}
        for name in ROW_TEXT_FIELDS:
            if name in row:
                vals[name] = str(row[name]).strip() if row[name] not in (None, False) else False
        if "name" in vals and not vals["name"]:
            raise ValueError("name can't be empty")
        for name in ROW_SELECTION_FIELDS:
            if name in row:
                if row[name] not in dict(self._fields[name].selection):
                    raise ValueError(f"{name}: unknown value {row[name]!r}")
                vals[name] = row[name]
        for name in ROW_BOOLEAN_FIELDS:
            if name in row:
                vals[name] = bool(row[name])
        for name in ("asked_at", "done_at"):
            if name in row:
                vals[name] = parse_utc_datetime(row[name])
        if "asked_at" in vals and not vals["asked_at"]:
            del vals["asked_at"]  # required: keep what's there (or now, when new)
        if "due_date" in row:
            vals["due_date"] = parse_date(row["due_date"])

        if row.get("wa_chat_id"):
            group = lookup.group(row["wa_chat_id"])
            if not group:
                raise ValueError(f"unknown wa_chat_id {row['wa_chat_id']!r} - send it with upsert_groups first")
            vals["group_id"] = group.id
        if "assignee_login" in row:
            user = lookup.user(row["assignee_login"])
            if user or not row["assignee_login"]:
                vals["assignee_id"] = user.id
            else:
                warnings.append(f"unknown assignee_login {row['assignee_login']!r} - saved without assignee")
        if row.get("requester_login"):
            user = lookup.user(row["requester_login"])
            if user:
                vals["requester_user_id"] = user.id
            else:
                warnings.append(f"unknown requester_login {row['requester_login']!r}")
        # Phone matching is only a fallback for people the bot doesn't know.
        if "requester_user_id" not in vals and not item.requester_user_id and row.get("requester_phone"):
            user = lookup.user_by_phone(row["requester_phone"])
            if user:
                vals["requester_user_id"] = user.id
        for name, model in (("project_id", "project.project"), ("partner_id", "res.partner")):
            if name in row:
                record_id = lookup.existing_id(model, row[name])
                if record_id is None:
                    warnings.append(f"{name} {row[name]!r} not found - left unchanged")
                else:
                    vals[name] = record_id
        if "linked_ref" in row:
            ref = self._parse_linked_ref(row["linked_ref"], warnings, lookup)
            if ref is not None:
                vals["linked_ref"] = ref
        return vals

    def _parse_linked_ref(self, value, warnings, lookup):
        """'model,id' or {"model", "id"} -> 'model,id'; False clears; None
        means "bad value, leave the field alone"."""
        if not value:
            return False
        if isinstance(value, dict):
            model, record_id = value.get("model"), value.get("id")
        else:
            model, _sep, record_id = str(value).partition(",")
        if model not in dict(self._selection_linked_ref()):
            warnings.append(f"linked_ref: {model!r} can't be linked here (not installed?)")
            return None
        if not lookup.existing_id(model, record_id):
            warnings.append(f"linked_ref: {model},{record_id} not found")
            return None
        return f"{model},{int(record_id)}"

    def _attach_files(self, files, warnings):
        """Adds the bot's files (base64 'datas'); the same file twice is kept once."""
        self.ensure_one()
        Attachment = self.env["ir.attachment"]
        for index, file in enumerate(files):
            name = isinstance(file, dict) and (file.get("name") or f"file-{index + 1}")
            try:
                raw = base64.b64decode(file["datas"], validate=False) if isinstance(file, dict) else None
            except (KeyError, TypeError, binascii.Error):
                raw = None
            if not raw:
                warnings.append(f"attachment {index}: no readable 'datas' - skipped")
                continue
            if len(raw) > MAX_ATTACHMENT_BYTES:
                warnings.append(f"attachment {name!r} is over {MAX_ATTACHMENT_BYTES // 1048576} MB - skipped")
                continue
            attachment = Attachment.search([
                ("res_model", "=", self._name), ("res_id", "=", self.id),
                ("checksum", "=", hashlib.sha1(raw).hexdigest()),
            ], limit=1)
            if not attachment:
                attachment = Attachment.create({
                    "name": name,
                    "raw": raw,
                    "mimetype": file.get("mimetype") or False,
                    "res_model": self._name,
                    "res_id": self.id,
                })
            if attachment not in self.attachment_ids:
                self.attachment_ids = [fields.Command.link(attachment.id)]

    # ------------------------------------------------------------------
    # The notebook screen
    # ------------------------------------------------------------------

    @api.model
    def get_notebook(self, date=None, group_id=None, search=None):
        """Everything the notebook screen shows, in one call.

        date: the day page (summaries and items closed that day), default
        today in Dubai. group_id: only this group. search: also return up to
        50 matching items, closed ones included.
        """
        return self._build_notebook(date, group_id, search)[0]

    def _build_notebook(self, date, group_id, search, with_week=False):
        """(get_notebook's result, what get_dashboard needs to add to it).
        with_week also fetches the items closed since Monday (Dubai)."""
        today = dubai_today()
        day = parse_date(date) or today
        now = utc_now()
        is_manager = self.env.user.has_group("kh_wa_inbox.group_kh_wa_manager")
        group_id = int(group_id) if group_id else False
        group_domain = [("group_id", "=", group_id)] if group_id else []
        fetch = self._notebook_fetch_fields(is_manager)

        # All open items: the dashboard's group cards need every group even
        # when one is picked; the lists use the picked group's share.
        open_all = self.search_fetch([("state", "in", OPEN_STATES)], fetch, order="asked_at asc, id asc")
        open_items = open_all.filtered(lambda i: i.group_id.id == group_id) if group_id else open_all
        start, end = dubai_day_bounds(day)
        closed_items = self.search_fetch(
            group_domain + [("state", "in", CLOSED_STATES), ("done_at", ">=", start), ("done_at", "<", end)],
            fetch, order="done_at desc, id desc",
        )
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_start_utc = dubai_day_bounds(week_start)[0]
        closed_week_all = self.browse()
        if with_week:
            closed_week_all = self.search_fetch(
                [("state", "in", CLOSED_STATES), ("done_at", ">=", week_start_utc)], fetch, order="done_at desc, id desc",
            )
        closed_week = closed_week_all.filtered(lambda i: i.group_id.id == group_id) if group_id else closed_week_all
        found = self.browse()
        search = (search or "").strip()
        if len(search) >= 2:
            found = self.search_fetch(
                group_domain + ["|", "|", "|", "|",
                                ("name", "ilike", search), ("source_text", "ilike", search),
                                ("requester_name", "ilike", search), ("done_note", "ilike", search),
                                ("assignee_id.name", "ilike", search)],
                fetch, order="asked_at desc, id desc", limit=SEARCH_LIMIT,
            )
        payloads = self._notebook_payloads(open_all | closed_items | closed_week_all | found, now, today, is_manager)

        cutoff = today + timedelta(days=7)
        counters = {"needs_manager": 0, "urgent": 0, "overdue": 0, "open": 0}
        needs_manager, urgent, upcoming = [], [], []
        open_by_group = defaultdict(list)
        for item in open_items:
            payload = payloads[item.id]
            counters["open"] += 1
            counters["needs_manager"] += item.needs_manager
            counters["urgent"] += item.urgent
            counters["overdue"] += payload["is_overdue"]
            # Each item shows in the first section it fits.
            if item.needs_manager:
                needs_manager.append(payload)
            elif item.urgent:
                urgent.append(payload)
            elif item.kind == "deadline" and item.due_date and item.due_date <= cutoff:
                upcoming.append(payload)
            else:
                open_by_group[item.group_id.id].append(payload)
        needs_manager.sort(key=lambda p: not p["urgent"])
        upcoming.sort(key=lambda p: p["due_date"])

        # An archived group keeps its place while it still has open items.
        groups = self.env["kh.wa.group"].with_context(active_test=False).search_fetch(
            ["|", ("active", "=", True), ("id", "in", open_all.group_id.ids)],
            ["name", "color", "category", "sequence", "last_message_at"],
        )
        open_counts = dict(self._read_group([("state", "in", OPEN_STATES)], ["group_id"], ["__count"]))
        group_list = [
            {"id": g.id, "name": g.name, "color": g.color, "category": g.category, "open_count": open_counts.get(g, 0)}
            for g in groups
        ]
        group_order = {g.id: index for index, g in enumerate(groups)}
        open_sections = [
            {"group_id": gid, "group_name": items[0]["group_name"], "group_color": items[0]["group_color"], "items": items}
            for gid, items in sorted(open_by_group.items(), key=lambda kv: group_order.get(kv[0], len(group_order)))
        ]

        result = {
            "today": fields.Date.to_string(today),
            "date": fields.Date.to_string(day),
            "is_manager": is_manager,
            "quick_done_minutes": self._quick_done_minutes(),
            "groups": group_list,
            "counters": counters,
            "users": self._notebook_users(),
            "sections": {
                "needs_manager": needs_manager,
                "urgent": urgent,
                "open": open_sections,
                "upcoming": upcoming,
                "day_summary": self._notebook_day_summary(day, group_id, group_order) if is_manager else [],
                "closed": [payloads[item.id] for item in closed_items],
                "memos": self._notebook_memos(),
            },
            "search_results": [payloads[item.id] for item in found] if len(search) >= 2 else False,
        }
        context = {
            "today": today, "day": day, "now": now, "is_manager": is_manager, "group_id": group_id,
            "group_domain": group_domain, "week_start": week_start, "week_start_utc": week_start_utc,
            "open_items": open_items, "closed_week": closed_week, "payloads": payloads, "groups": groups,
            "open_all": open_all, "closed_week_all": closed_week_all, "group_order": group_order,
        }
        return result, context

    @api.model
    def _notebook_fetch_fields(self, is_manager):
        names = [
            "name", "kind", "state", "urgent", "needs_manager", "group_id", "project_id", "partner_id",
            "requester_name", "assignee_id", "asked_at", "due_date", "done_at", "done_note",
            "source_text", "context_text", "source_kind", "linked_ref", "remind_on",
        ]
        return names + (["requester_phone", "manager_note"] if is_manager else [])

    @api.model
    def _notebook_payloads(self, items, now, today, is_manager):
        """{item id: dict}. Attachments come as metadata only, never contents."""
        # The user can read these items; their related names and file lists
        # are read with sudo (a project the user can't open must not break
        # the whole screen).
        related = items.sudo()
        files = defaultdict(list)
        for item in related:
            for att in item.attachment_ids:
                files[item.id].append({
                    "id": att.id,
                    "name": att.name,
                    "mimetype": att.mimetype or "",
                    "url": f"/web/content/{att.id}",
                })
        linked = self._notebook_linked(items)
        payloads = {}
        for item, item_sudo in zip(items, related):
            payloads[item.id] = {
                "id": item.id,
                "name": item.name,
                "kind": item.kind,
                "state": item.state,
                "urgent": item.urgent,
                "needs_manager": item.needs_manager,
                "is_overdue": bool(item.due_date and item.due_date < today and item.state in OPEN_STATES),
                "group_id": item.group_id.id,
                "group_name": item_sudo.group_id.name,
                "group_color": item_sudo.group_id.color,
                "project": item_sudo.project_id.display_name or "",
                "partner": item_sudo.partner_id.display_name or "",
                "requester_name": item.requester_name or "",
                "requester_phone": (item.requester_phone or "") if is_manager else "",
                "assignee": {"id": item.assignee_id.id, "name": item_sudo.assignee_id.name} if item.assignee_id else False,
                "asked_at": fields.Datetime.to_string(item.asked_at) or False,
                "age": arabic_age(item.asked_at, now),
                "due_date": fields.Date.to_string(item.due_date) or False,
                "done_at": fields.Datetime.to_string(item.done_at) or False,
                "took": duration_text((item.done_at - item.asked_at).total_seconds())
                if item.done_at and item.asked_at and item.state in CLOSED_STATES else "",
                "done_note": item.done_note or "",
                "source_text": item.source_text or "",
                "context_text": item.context_text or "",
                "source_kind": item.source_kind,
                "attachments": files.get(item.id, []),
                "linked": linked.get(item.id, False),
                "remind_on": fields.Date.to_string(item.remind_on) or False,
                "manager_note": (item.manager_note or "") if is_manager else "",
            }
        return payloads

    @api.model
    def _notebook_linked(self, items):
        """{item id: {"model", "id", "name"}} for linked records that still exist."""
        by_model = defaultdict(dict)
        for item in items:
            if item.linked_ref:
                by_model[item.linked_ref._name][item.id] = item.linked_ref.id
        result = {}
        for model, item_to_record in by_model.items():
            records = self.env[model].browse(set(item_to_record.values())).exists()
            readable = records._filtered_access("read")
            label = self.env["ir.model"].sudo()._get(model).name
            names = {record.id: record.display_name for record in readable}
            for item_id, record_id in item_to_record.items():
                if record_id in records.ids:
                    result[item_id] = {"model": model, "id": record_id, "name": names.get(record_id, label)}
        return result

    @api.model
    def _notebook_day_summary(self, day, group_id, group_order):
        domain = [("date", "=", day)] + ([("group_id", "=", int(group_id))] if group_id else [])
        days = self.env["kh.wa.day"].search_fetch(
            domain, ["group_id", "summary", "message_count", "quick_done_count", "visit_count"],
        )
        pages = [
            {
                "group_id": page.group_id.id,
                "group_name": page.group_id.name,
                "group_color": page.group_id.color,
                "lines": [line.strip() for line in (page.summary or "").splitlines() if line.strip()],
                "message_count": page.message_count,
                "quick_done_count": page.quick_done_count,
                "visit_count": page.visit_count,
            }
            for page in days
        ]
        return sorted(pages, key=lambda p: group_order.get(p["group_id"], len(group_order)))

    @api.model
    def _notebook_memos(self):
        memos = self.env["kh.wa.memo"].search_fetch(
            [("user_id", "=", self.env.uid), ("done", "=", False)], ["text", "pinned", "item_id"],
        )
        return [{"id": m.id, "text": m.text, "pinned": m.pinned, "item_id": m.item_id.id} for m in memos]

    @api.model
    def _notebook_users(self):
        """People an item can be assigned to: everyone with notebook access."""
        users = self.env.ref("kh_wa_inbox.group_kh_wa_user").sudo().all_user_ids.filtered(
            lambda u: u.active and not u.share
        )
        return [{"id": u.id, "name": u.name} for u in users.sorted("name")]


class _RowLookup:
    """Per-batch cache of the groups, users and records a batch refers to."""

    def __init__(self, env):
        self.env = env
        self._groups = {}
        self._users = {}
        self._phones = None

    def group(self, chat_id):
        chat_id = str(chat_id).strip()
        if chat_id not in self._groups:
            self._groups[chat_id] = self.env["kh.wa.group"].with_context(active_test=False).search(
                [("wa_chat_id", "=", chat_id)], limit=1,
            )
        return self._groups[chat_id]

    def user(self, login):
        login = str(login or "").strip()
        if not login:
            return self.env["res.users"]
        if login not in self._users:
            self._users[login] = self.env["res.users"].sudo().search(
                [("login", "=ilike", login), ("share", "=", False)], limit=1,
            )
        return self._users[login]

    def user_by_phone(self, phone):
        """Only when exactly one internal user has this number."""
        if self._phones is None:
            users = self.env["res.users"].sudo().search([("share", "=", False)])
            pairs = [(u.partner_id.phone, u.id) for u in users]
            if "hr.employee" in self.env:
                employees = self.env["hr.employee"].sudo().search([("user_id", "in", users.ids)])
                for field in ("work_phone", "mobile_phone", "private_phone"):
                    if field in employees._fields:
                        pairs += [(emp[field], emp.user_id.id) for emp in employees]
            self._phones = phone_index(pairs)
        matches = self._phones.get(normalize_phone(phone), set())
        return self.env["res.users"].browse(next(iter(matches))) if len(matches) == 1 else self.env["res.users"]

    def existing_id(self, model, value):
        """False for an empty value, the id if the record exists, else None."""
        if not value:
            return False
        try:
            record_id = int(value)
        except (TypeError, ValueError):
            return None
        return record_id if self.env[model].sudo().browse(record_id).exists() else None

    def record_from(self, vals, field, model):
        return self.env[model].browse(vals[field]) if vals.get(field) else self.env[model]
