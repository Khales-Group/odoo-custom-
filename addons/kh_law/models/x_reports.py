from datetime import timedelta

from odoo import api, fields, models

# A legal file with no update/message for this many days is flagged as stale.
STALE_DAYS = 14


def _positive_boolean_search(operator, value):
    """ Return True/False for "records where the boolean is True?", or None
    when the operator is not supported by the custom search methods. """
    if operator in ("=", "!="):
        value, operator = [value], ("in" if operator == "=" else "not in")
    if operator not in ("in", "not in"):
        return None
    return (operator == "in") == (True in value)


class LawReport(models.Model):
    # Same technical name as the Studio model, so existing data is kept.
    # The Studio fields (x_name, x_studio_type, x_studio_company_id, ...) are
    # deliberately NOT redefined here: they stay Studio-managed and Odoo still
    # loads them onto this class, with their exact Studio definitions. Only
    # the stage is redefined, for the per-department columns and statusbar.
    _name = "x_reports"
    _description = "Law"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "x_name"
    _active_name = "x_active"
    _order = "kh_priority desc, id desc"

    x_studio_stage_id = fields.Many2one(
        "x_reports_stage",
        string="Stage",
        required=True,
        ondelete="restrict",
        tracking=True,
        group_expand="_read_group_stage_ids",
        domain="[('kh_department', '=', x_studio_type)]",
    )

    # ------------------------------------------------------------------
    # Common to both departments
    # ------------------------------------------------------------------
    kh_priority = fields.Selection(
        [("0", "Low"), ("1", "Medium"), ("2", "High")],
        string="Priority",
        default="0",
        tracking=True,
    )
    kh_is_closed = fields.Boolean(related="x_studio_stage_id.kh_is_closed", store=True, string="Closed")
    kh_open_date = fields.Date(
        string="Opened On", compute="_compute_kh_open_date", store=True, readonly=False
    )
    kh_close_date = fields.Date(
        string="Closed On", compute="_compute_kh_close_date", store=True, readonly=False, tracking=True
    )
    kh_duration_days = fields.Integer(
        string="Duration (Days)", compute="_compute_kh_duration_days", store=True, aggregator="avg",
        help="Days from opening to closing, for closed files.",
    )
    kh_last_update = fields.Datetime(string="Last Update", compute="_compute_kh_activity_info")
    kh_days_inactive = fields.Integer(string="Days Without Activity", compute="_compute_kh_activity_info")
    kh_is_stale = fields.Boolean(
        string="No Recent Activity", compute="_compute_kh_activity_info", search="_search_kh_is_stale"
    )

    # ------------------------------------------------------------------
    # Legal Affairs
    # ------------------------------------------------------------------
    kh_case_assessment = fields.Selection(
        [("likely_win", "Likely Win"), ("medium", "Medium"), ("difficult", "Difficult")],
        string="Lawyer's Assessment",
        tracking=True,
    )
    kh_case_outcome = fields.Selection(
        [("won", "Won"), ("lost", "Lost"), ("settled", "Settled"), ("withdrawn", "Withdrawn")],
        string="Outcome",
        tracking=True,
    )
    kh_fee_expected = fields.Monetary(string="Expected Fees", currency_field="x_studio_currency_id")
    kh_fee_collected = fields.Monetary(string="Collected Fees", currency_field="x_studio_currency_id")
    kh_fee_remaining = fields.Monetary(
        string="Remaining Fees", currency_field="x_studio_currency_id",
        compute="_compute_kh_fee_remaining", store=True,
    )

    # ------------------------------------------------------------------
    # PRO
    # ------------------------------------------------------------------
    kh_pro_service = fields.Selection(
        [
            ("trade_license", "Trade License"),
            ("residence", "Residence"),
            ("visa", "Visa"),
            ("labour_contract", "Labour Contract"),
            ("office_lease", "Office Lease"),
            ("other", "Other"),
        ],
        string="Service",
        tracking=True,
    )
    kh_expiry_date = fields.Date(string="Expiry Date", tracking=True)
    kh_days_to_expiry = fields.Integer(string="Days to Expiry", compute="_compute_kh_expiry")
    kh_expiry_state = fields.Selection(
        [
            ("none", "No Expiry"),
            ("far", "More than 90 days"),
            ("ok", "Within 90 days"),
            ("warning", "Within 60 days"),
            ("danger", "Within 30 days"),
            ("expired", "Expired"),
        ],
        string="Expiry Status",
        compute="_compute_kh_expiry",
    )
    kh_expiry_label = fields.Char(string="Countdown", compute="_compute_kh_expiry")
    kh_due_date = fields.Date(string="Target Completion Date", tracking=True)
    kh_is_late = fields.Boolean(string="Late", compute="_compute_kh_is_late", search="_search_kh_is_late")
    kh_on_time = fields.Selection(
        [("on_time", "On Time"), ("late", "Late")],
        string="Completed",
        compute="_compute_kh_on_time",
        store=True,
    )
    kh_fine_count = fields.Integer(string="Fines (Count)", tracking=True)
    kh_fine_amount = fields.Monetary(string="Fines (Amount)", currency_field="x_studio_currency_id")
    kh_rejection_count = fields.Integer(
        string="Rejections / Resubmissions",
        tracking=True,
        help="How many times the transaction was rejected and had to be resubmitted.",
    )
    kh_document_ids = fields.One2many("kh.law.document", "report_id", string="Required Documents")
    kh_missing_doc_count = fields.Integer(
        string="Missing Documents", compute="_compute_kh_missing_doc_count", store=True
    )

    # ------------------------------------------------------------------
    # Stages per department
    # ------------------------------------------------------------------
    def _kh_first_stage(self, department):
        return self.env["x_reports_stage"].search([("kh_department", "=", department)], limit=1)

    def _read_group_stage_ids(self, stages, domain):
        department = self.env.context.get("default_x_studio_type")
        if not department:
            return stages
        return stages.search(["|", ("id", "in", stages.ids), ("kh_department", "=", department)])

    @api.onchange("x_studio_type")
    def _onchange_kh_department(self):
        for rec in self:
            if rec.x_studio_type and rec.x_studio_stage_id.kh_department != rec.x_studio_type:
                rec.x_studio_stage_id = rec._kh_first_stage(rec.x_studio_type)

    @api.model_create_multi
    def create(self, vals_list):
        Stage = self.env["x_reports_stage"]
        for vals in vals_list:
            department = vals.get("x_studio_type") or self.default_get(["x_studio_type"]).get("x_studio_type")
            if not department:
                continue
            stage_id = vals.get("x_studio_stage_id") or self.default_get(["x_studio_stage_id"]).get("x_studio_stage_id")
            if Stage.browse(stage_id).kh_department != department:
                first = self._kh_first_stage(department)
                if first:
                    vals["x_studio_stage_id"] = first.id
        return super().create(vals_list)

    def write(self, vals):
        # Changing the department (e.g. classifying a file without type) also
        # moves the file to the first stage of that department.
        department = vals.get("x_studio_type")
        if department and "x_studio_stage_id" not in vals:
            mismatched = self.filtered(lambda r: r.x_studio_stage_id.kh_department != department)
            first = self._kh_first_stage(department)
            if mismatched and first:
                super(LawReport, mismatched).write(dict(vals, x_studio_stage_id=first.id))
                return super(LawReport, self - mismatched).write(vals)
        return super().write(vals)

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("create_date")
    def _compute_kh_open_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.kh_open_date:
                rec.kh_open_date = rec.create_date.date() if rec.create_date else today

    @api.depends("kh_is_closed")
    def _compute_kh_close_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.kh_is_closed:
                rec.kh_close_date = rec.kh_close_date or today
            else:
                rec.kh_close_date = False

    @api.depends("kh_open_date", "kh_close_date")
    def _compute_kh_duration_days(self):
        for rec in self:
            if rec.kh_open_date and rec.kh_close_date:
                rec.kh_duration_days = max((rec.kh_close_date - rec.kh_open_date).days, 0)
            else:
                rec.kh_duration_days = 0

    @api.depends("write_date", "kh_is_closed")
    def _compute_kh_activity_info(self):
        now = fields.Datetime.now()
        record_ids = [rec._origin.id for rec in self if rec._origin.id]
        last_message = {}
        if record_ids:
            last_message = dict(self.env["mail.message"].sudo()._read_group(
                [("model", "=", self._name), ("res_id", "in", record_ids)],
                ["res_id"],
                ["date:max"],
            ))
        for rec in self:
            dates = [d for d in (rec.write_date, last_message.get(rec._origin.id)) if d]
            last = max(dates) if dates else False
            rec.kh_last_update = last
            rec.kh_days_inactive = (now - last).days if last else 0
            rec.kh_is_stale = bool(last) and not rec.kh_is_closed and rec.kh_days_inactive >= STALE_DAYS

    def _search_kh_is_stale(self, operator, value):
        positive = _positive_boolean_search(operator, value)
        if positive is None:
            return NotImplemented
        threshold = fields.Datetime.now() - timedelta(days=STALE_DAYS)
        recent_ids = [res_id for (res_id,) in self.env["mail.message"].sudo()._read_group(
            [("model", "=", self._name), ("date", ">=", threshold)], ["res_id"],
        )]
        stale_ids = self.with_context(active_test=False).search([
            ("write_date", "<", threshold),
            ("kh_is_closed", "=", False),
            ("id", "not in", recent_ids),
        ]).ids
        return [("id", "in" if positive else "not in", stale_ids)]

    @api.depends("kh_fee_expected", "kh_fee_collected")
    def _compute_kh_fee_remaining(self):
        for rec in self:
            rec.kh_fee_remaining = rec.kh_fee_expected - rec.kh_fee_collected

    @api.depends("kh_expiry_date")
    def _compute_kh_expiry(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.kh_expiry_date:
                rec.kh_days_to_expiry = 0
                rec.kh_expiry_state = "none"
                rec.kh_expiry_label = False
                continue
            days = (rec.kh_expiry_date - today).days
            rec.kh_days_to_expiry = days
            if days < 0:
                rec.kh_expiry_state = "expired"
                rec.kh_expiry_label = self.env._("Expired %s days ago", -days)
                continue
            if days <= 30:
                rec.kh_expiry_state = "danger"
            elif days <= 60:
                rec.kh_expiry_state = "warning"
            elif days <= 90:
                rec.kh_expiry_state = "ok"
            else:
                rec.kh_expiry_state = "far"
            rec.kh_expiry_label = self.env._("%s days left", days)

    @api.depends("kh_due_date", "kh_is_closed")
    def _compute_kh_is_late(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.kh_is_late = bool(rec.kh_due_date) and not rec.kh_is_closed and rec.kh_due_date < today

    def _search_kh_is_late(self, operator, value):
        positive = _positive_boolean_search(operator, value)
        if positive is None:
            return NotImplemented
        today = fields.Date.context_today(self)
        if positive:
            return [("kh_due_date", "<", today), ("kh_is_closed", "=", False)]
        return ["|", "|", ("kh_due_date", "=", False), ("kh_due_date", ">=", today), ("kh_is_closed", "=", True)]

    @api.depends("kh_close_date", "kh_due_date")
    def _compute_kh_on_time(self):
        for rec in self:
            if rec.kh_close_date and rec.kh_due_date:
                rec.kh_on_time = "on_time" if rec.kh_close_date <= rec.kh_due_date else "late"
            else:
                rec.kh_on_time = False

    @api.depends("kh_document_ids.kh_is_received")
    def _compute_kh_missing_doc_count(self):
        for rec in self:
            rec.kh_missing_doc_count = len(rec.kh_document_ids.filtered(lambda d: not d.kh_is_received))
