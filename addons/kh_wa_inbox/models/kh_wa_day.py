from odoo import api, fields, models

from .kh_wa_tools import dubai_date, mask_text, parse_date, run_batch


class KhWaDay(models.Model):
    _name = "kh.wa.day"
    _description = "WhatsApp Group Day Page"
    _order = "date desc, group_id"

    date = fields.Date(required=True, index=True)
    group_id = fields.Many2one("kh.wa.group", string="WhatsApp Group", required=True, ondelete="cascade", index=True)
    summary = fields.Text(help="2-4 short lines about the day in this group.")
    message_count = fields.Integer(string="Messages")
    quick_done_ids = fields.One2many("kh.wa.quick.done", "day_id", string="Finished Quickly")
    quick_done_count = fields.Integer(
        string="Finished Within the Threshold", compute="_compute_quick_done_count", store=True,
        help="Requests asked and finished within the quick-done threshold (Settings). "
             "Counted by the server, once per WhatsApp message.",
    )
    visit_count = fields.Integer(string="Site Visits")

    _date_group_unique = models.Constraint(
        "UNIQUE(date, group_id)", "This group already has a page for this day."
    )

    @api.depends("quick_done_ids")
    def _compute_quick_done_count(self):
        for page in self:
            page.quick_done_count = len(page.quick_done_ids)

    @api.depends("date", "group_id.name")
    def _compute_display_name(self):
        for page in self:
            page.display_name = f"{page.group_id.name or ''} · {fields.Date.to_string(page.date) or ''}"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("summary"):
                vals["summary"] = mask_text(vals["summary"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("summary"):
            vals = {**vals, "summary": mask_text(vals["summary"])}
        return super().write(vals)

    @api.model
    def _get_or_create(self, day, group):
        page = self.search([("date", "=", day), ("group_id", "=", group.id)], limit=1)
        return page or self.create({"date": day, "group_id": group.id})

    # ------------------------------------------------------------------
    # XML-RPC API (the WhatsApp bot)
    # ------------------------------------------------------------------

    @api.model
    def upsert_days(self, rows):
        """Create or update day pages, keyed by (date, wa_chat_id).

        Row: {"date"* ("2026-11-02", Dubai), "wa_chat_id"*, "summary",
        "message_count", "visit_count"}. quick_done_count is counted by the
        server from upsert_items and ignored here.
        Returns {"ids": [...], "errors": [...]}.
        """
        return run_batch(
            self, rows, lambda row: f"{row.get('date')}|{row.get('wa_chat_id')}", self._upsert_day_row,
        )

    def _upsert_day_row(self, row, warnings):
        day = parse_date(row.get("date"))
        if not day:
            raise ValueError("date is required")
        chat_id = str(row.get("wa_chat_id") or "").strip()
        group = chat_id and self.env["kh.wa.group"].with_context(active_test=False).search(
            [("wa_chat_id", "=", chat_id)], limit=1,
        )
        if not group:
            raise ValueError(f"unknown wa_chat_id {chat_id!r} - send it with upsert_groups first")
        vals = {}
        if "summary" in row:
            vals["summary"] = str(row["summary"]).strip() if row["summary"] else False
        for name in ("message_count", "visit_count"):
            if name in row:
                vals[name] = int(row[name] or 0)
        page = self._get_or_create(day, group)
        if vals:
            page.write(vals)
        return page.id


class KhWaQuickDone(models.Model):
    """One line per WhatsApp request finished within the threshold: keeps the
    day's count right when the bot sends the same message twice."""

    _name = "kh.wa.quick.done"
    _description = "Request Finished Within the Threshold"
    _order = "id desc"

    source_msg_id = fields.Char(string="Source Message ID", required=True, index=True)
    day_id = fields.Many2one("kh.wa.day", string="Day Page", required=True, ondelete="cascade", index=True)
    asked_at = fields.Datetime(string="Asked At")
    done_at = fields.Datetime(string="Closed At")

    _source_msg_id_unique = models.Constraint(
        "UNIQUE(source_msg_id)", "This WhatsApp message is already counted."
    )

    @api.model
    def _log(self, source_msg_id, group, asked_at, done_at):
        page = self.env["kh.wa.day"]._get_or_create(dubai_date(asked_at), group)
        return self.create({
            "source_msg_id": source_msg_id,
            "day_id": page.id,
            "asked_at": asked_at,
            "done_at": done_at,
        })
