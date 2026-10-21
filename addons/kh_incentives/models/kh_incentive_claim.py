# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

CEO_ID = 369  # Majed - same approver as the Collection app's manager step


class KhIncentiveClaim(models.Model):
    _name = "kh.incentive.claim"
    _description = "Incentive / Commission Claim"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "month desc, id desc"
    _rec_name = "name"

    name = fields.Char(string="Reference", compute="_compute_name", store=True)
    employee_id = fields.Many2one(
        "res.users", string="Employee", default=lambda self: self.env.user,
        required=True, tracking=True,
    )
    month = fields.Date(string="Month", required=True, default=fields.Date.context_today, tracking=True)
    project_id = fields.Many2one("project.project", string="Project", tracking=True)
    file_reference = fields.Char(
        string="Contract/File", help="Free-text reference if this isn't tied to a Project record."
    )

    incentive_type = fields.Selection(
        [("new_contract", "New Contract"), ("overdue_debt", "Overdue Debt Collected")],
        string="Incentive Type", required=True, tracking=True,
    )
    role = fields.Selection(
        [
            ("source", "Source"),
            ("relationship", "Relationship"),
            ("offer", "Offer"),
            ("negotiation", "Negotiation"),
            ("execution", "Execution"),
            ("collection", "Collection"),
        ],
        string="Role", required=True, tracking=True,
    )

    amount_collected = fields.Monetary(string="Amount Collected", tracking=True)
    approved_margin = fields.Monetary(string="Approved Margin", tracking=True)
    incentive_amount = fields.Monetary(string="Incentive Amount", required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", string="Currency", default=lambda self: self.env.company.currency_id
    )

    financial_reviewer_id = fields.Many2one("res.users", string="Financial Reviewer", tracking=True)
    payment_date = fields.Date(string="Payment Date", tracking=True)
    note = fields.Text(string="Notes")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_approval", "Pending CEO Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("paid", "Paid"),
        ],
        string="Status", default="draft", required=True, tracking=True,
    )
    is_ceo = fields.Boolean(string="Is Current User the CEO?", compute="_compute_is_ceo")

    def _compute_is_ceo(self):
        for rec in self:
            rec.is_ceo = self.env.user.id == CEO_ID

    @api.depends("employee_id", "month", "role")
    def _compute_name(self):
        for rec in self:
            month_label = rec.month.strftime("%Y-%m") if rec.month else ""
            role_label = dict(rec._fields["role"].selection).get(rec.role, "")
            parts = [p for p in (rec.employee_id.name, month_label, role_label) if p]
            rec.name = _("Incentive - %s") % " / ".join(parts) if parts else _("Incentive")

    def _check_is_ceo(self):
        if self.env.user.id != CEO_ID:
            raise UserError(_("Only the CEO can approve or reject an incentive claim."))

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only a draft claim can be submitted."))
            rec.state = "pending_approval"
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=CEO_ID,
                summary=_("Incentive claim awaiting your approval"),
                note=_("%s submitted an incentive claim of %s for %s.")
                % (rec.employee_id.name, rec.incentive_amount, rec.name),
            )

    def action_approve(self):
        self._check_is_ceo()
        for rec in self:
            if rec.state != "pending_approval":
                raise UserError(_("This claim is not pending approval."))
            rec.state = "approved"
            rec._close_my_pending_activities()
            rec.message_post(body=_("Approved by the CEO."))

    def action_reject(self):
        self._check_is_ceo()
        for rec in self:
            if rec.state != "pending_approval":
                raise UserError(_("This claim is not pending approval."))
            rec.state = "rejected"
            rec._close_my_pending_activities()
            rec.message_post(body=_("Rejected by the CEO."))

    def action_reset_to_draft(self):
        for rec in self:
            rec.state = "draft"

    def action_mark_paid(self):
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Only an approved claim can be marked paid."))
            rec.state = "paid"
            rec.payment_date = rec.payment_date or fields.Date.context_today(rec)

    def _close_my_pending_activities(self):
        self.activity_ids.filtered(lambda a: a.user_id.id == self.env.user.id).action_feedback(
            feedback=_("Done")
        )
