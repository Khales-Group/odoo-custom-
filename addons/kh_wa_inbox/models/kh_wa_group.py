from odoo import api, fields, models

from .kh_wa_tools import parse_utc_datetime, run_batch

OPEN_STATES = ("open", "waiting")
GROUP_ROW_FIELDS = ("name", "category", "color", "sequence", "active")


class KhWaGroup(models.Model):
    _name = "kh.wa.group"
    _description = "WhatsApp Group"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    wa_chat_id = fields.Char(
        string="WhatsApp Chat ID", required=True, index=True, copy=False,
        help="The group's id on WhatsApp (e.g. 1203630xxxx@g.us). The bot finds the group by it.",
    )
    category = fields.Selection(
        [
            ("legal", "Legal"),
            ("projects", "Projects"),
            ("marketing", "Marketing"),
            ("accounts", "Accounts"),
            ("hr", "HR"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
    )
    color = fields.Integer(string="Color")
    project_id = fields.Many2one(
        "project.project", string="Project", ondelete="set null",
        help="Default project for this group's items.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    last_message_at = fields.Datetime(string="Last Message At", help="Sent by the bot with upsert_groups.")
    item_ids = fields.One2many("kh.wa.item", "group_id", string="Items")
    open_count = fields.Integer(string="Open Items", compute="_compute_open_count")

    _wa_chat_id_unique = models.Constraint(
        "UNIQUE(wa_chat_id)", "Another group already has this WhatsApp chat id."
    )

    def _compute_open_count(self):
        counts = dict(self.env["kh.wa.item"]._read_group(
            [("group_id", "in", self.ids), ("state", "in", OPEN_STATES)], ["group_id"], ["__count"],
        ))
        for group in self:
            group.open_count = counts.get(group, 0)

    def action_open_items(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("kh_wa_inbox.action_kh_wa_item")
        action["domain"] = [("group_id", "=", self.id)]
        action["context"] = {"search_default_filter_open": 1}
        return action

    # ------------------------------------------------------------------
    # XML-RPC API (the WhatsApp bot)
    # ------------------------------------------------------------------

    @api.model
    def upsert_groups(self, rows):
        """Create or update groups, keyed by wa_chat_id.

        Row: {"wa_chat_id"*, "name" (* when new), "category", "color",
        "project_id", "sequence", "active", "last_message_at" (UTC, ISO 8601
        or epoch; an older value than the stored one is ignored)}.
        Returns {"ids": [...], "errors": [...]}.
        """
        return run_batch(self, rows, lambda row: row.get("wa_chat_id"), self._upsert_group_row)

    def _upsert_group_row(self, row, warnings):
        chat_id = str(row.get("wa_chat_id") or "").strip()
        if not chat_id:
            raise ValueError("wa_chat_id is required")
        vals = {name: row[name] for name in GROUP_ROW_FIELDS if name in row}
        if "name" in vals:
            vals["name"] = str(vals["name"] or "").strip()
            if not vals["name"]:
                raise ValueError("name can't be empty")
        if "category" in vals:
            vals["category"] = vals["category"] or "other"
            if vals["category"] not in dict(self._fields["category"].selection):
                raise ValueError(f"category: unknown value {vals['category']!r}")
        for name in ("color", "sequence"):
            if name in vals:
                vals[name] = int(vals[name] or 0)
        if "active" in vals:
            vals["active"] = bool(vals["active"])
        if "project_id" in row:
            project_id = row["project_id"]
            if not project_id:
                vals["project_id"] = False
            elif self.env["project.project"].sudo().browse(int(project_id)).exists():
                vals["project_id"] = int(project_id)
            else:
                warnings.append(f"project_id {project_id} not found - left unchanged")

        group = self.with_context(active_test=False).search([("wa_chat_id", "=", chat_id)], limit=1)
        if row.get("last_message_at"):
            last = parse_utc_datetime(row["last_message_at"])
            if not group.last_message_at or last > group.last_message_at:
                vals["last_message_at"] = last
        if group:
            group.write(vals)
            return group.id
        if not vals.get("name"):
            raise ValueError("name is required for a new group")
        return self.create({**vals, "wa_chat_id": chat_id}).id
