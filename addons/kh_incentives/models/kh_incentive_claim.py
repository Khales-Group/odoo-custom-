# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.kh_collection.models.kh_collection_case import HANDLER_ROLES

CEO_ID = 369  # Majed - same approver as the Collection app's manager step

# Bonus rules (percentages of the amount received).
COLLECTION_RATES = {"1_accountant": 0.25, "2_pro": 0.5, "3_lawyer": 1.0}
DESIGN_RATE = 4.0
HANDOVER_MIN, HANDOVER_MAX = 500.0, 3500.0


class KhIncentiveClaim(models.Model):
    # Technical name kept from the first version (incentive claims) so the
    # existing records, access rules and menus stay attached.
    _name = "kh.incentive.claim"
    _description = "Bonus"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    # Bonus types and roles sort in the order the manager reads them:
    # Collection (Accountant, PRO, Lawyer), Design, Handover, Other.
    _order = "month desc, bonus_type, collection_role, employee_id, id desc"
    _rec_name = "name"

    name = fields.Char(string="Reference", compute="_compute_name", store=True)
    employee_id = fields.Many2one(
        "res.users", string="Employee", default=lambda self: self.env.user,
        required=True, tracking=True,
    )
    month = fields.Date(string="Month", required=True, default=fields.Date.context_today, tracking=True)
    bonus_type = fields.Selection(
        [
            ("collection", "Collection"),
            ("design", "Design Start"),
            ("handover", "Project Handover"),
            ("other", "Other"),
        ],
        string="Bonus Type", required=True, default="other", tracking=True,
        help="Collection: money collected on a collection case - Accountant 0.25%, PRO 0.5%, "
             "Lawyer 1% of the amount received (created automatically).\n"
             "Design Start: 4% of the client's payment that starts the design, for the designer.\n"
             "Project Handover: 500 to 3,500 for the project manager once the project is "
             "handed over / complete (a draft is created automatically).\n"
             "Other: any other bonus, amount entered by hand.",
    )
    collection_role = fields.Selection(HANDLER_ROLES, string="Collected As", tracking=True)
    collection_case_id = fields.Many2one(
        "kh.collection.case", string="Collection Case", tracking=True, index="btree_not_null",
    )
    project_id = fields.Many2one("project.project", string="Project", tracking=True)
    invoice_id = fields.Many2one(
        "account.move", string="Client Invoice",
        domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]",
        groups="account.group_account_invoice",
        help="Pick the client's invoice and the amount received is filled in from what was paid on it.",
    )
    amount_collected = fields.Monetary(
        string="Amount Received", tracking=True,
        compute="_compute_amount_collected", store=True, readonly=False,
    )
    rate = fields.Float(string="Rate (%)", compute="_compute_rate", store=True, digits=(5, 2))
    incentive_amount = fields.Monetary(
        string="Bonus Amount", required=True, tracking=True,
        compute="_compute_incentive_amount", store=True, readonly=False,
    )
    currency_id = fields.Many2one(
        "res.currency", string="Currency", default=lambda self: self.env.company.currency_id
    )
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

    @api.depends("employee_id", "month", "bonus_type", "collection_role")
    def _compute_name(self):
        types = dict(self._fields["bonus_type"].selection)
        roles = dict(self._fields["collection_role"].selection)
        for rec in self:
            kind = types.get(rec.bonus_type, "")
            if rec.bonus_type == "collection" and rec.collection_role:
                kind = "%s (%s)" % (kind, roles[rec.collection_role])
            month_label = rec.month.strftime("%Y-%m") if rec.month else ""
            parts = [p for p in (rec.employee_id.name, kind, month_label) if p]
            rec.name = _("Bonus - %s", " / ".join(parts)) if parts else _("Bonus")

    @api.depends("invoice_id")
    def _compute_amount_collected(self):
        # Filled in when the invoice is picked, and not afterwards: later
        # payments on the same invoice must not change a bonus already
        # approved or paid.
        for rec in self:
            invoice = rec.sudo().invoice_id
            if invoice:
                rec.amount_collected = invoice.amount_total_signed - invoice.amount_residual_signed
            else:
                rec.amount_collected = rec.amount_collected

    @api.depends("bonus_type", "collection_role")
    def _compute_rate(self):
        for rec in self:
            if rec.bonus_type == "collection":
                rec.rate = COLLECTION_RATES.get(rec.collection_role, 0.0)
            elif rec.bonus_type == "design":
                rec.rate = DESIGN_RATE
            else:
                rec.rate = 0.0

    @api.depends("bonus_type", "rate", "amount_collected")
    def _compute_incentive_amount(self):
        for rec in self:
            if rec.bonus_type in ("collection", "design"):
                amount = rec.amount_collected * rec.rate / 100.0
                rec.incentive_amount = rec.currency_id.round(amount) if rec.currency_id else round(amount, 2)
            else:
                # Handover / Other: entered by hand.
                rec.incentive_amount = rec.incentive_amount

    @api.constrains("bonus_type", "incentive_amount", "state")
    def _check_handover_amount(self):
        for rec in self:
            if (
                rec.bonus_type == "handover"
                and rec.state != "draft"
                and not HANDOVER_MIN <= rec.incentive_amount <= HANDOVER_MAX
            ):
                raise ValidationError(_("A project handover bonus must be between 500 and 3,500."))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _check_is_ceo(self):
        if self.env.user.id != CEO_ID:
            raise UserError(_("Only the CEO can approve or reject a bonus."))

    def _ask_ceo(self, summary):
        for rec in self:
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=CEO_ID,
                summary=summary,
                note=_("%(employee)s - %(bonus)s: %(amount)s", employee=rec.employee_id.name,
                       bonus=rec.name, amount=rec.incentive_amount),
            )

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only a draft bonus can be submitted."))
            rec.state = "pending_approval"
        self._ask_ceo(_("Bonus awaiting your approval"))

    def action_approve(self):
        # The CEO can approve straight from Draft too - e.g. a handover
        # bonus he just set the amount on himself.
        self._check_is_ceo()
        for rec in self:
            if rec.state not in ("draft", "pending_approval"):
                raise UserError(_("This bonus is not waiting for approval."))
            rec.state = "approved"
            rec._close_my_pending_activities()
            rec.message_post(body=_("Approved by the CEO."))

    def action_reject(self):
        self._check_is_ceo()
        for rec in self:
            if rec.state not in ("draft", "pending_approval"):
                raise UserError(_("This bonus is not waiting for approval."))
            rec.state = "rejected"
            rec._close_my_pending_activities()
            rec.message_post(body=_("Rejected by the CEO."))

    def action_reset_to_draft(self):
        for rec in self:
            rec.state = "draft"

    def action_mark_paid(self):
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Only an approved bonus can be marked paid."))
            rec.state = "paid"
            rec.payment_date = rec.payment_date or fields.Date.context_today(rec)

    def _close_my_pending_activities(self):
        self.activity_ids.filtered(lambda a: a.user_id.id == self.env.user.id).action_feedback(
            feedback=_("Done")
        )

    # ------------------------------------------------------------------
    # Created automatically by the other apps
    # ------------------------------------------------------------------
    @api.model
    def _create_collection_bonuses(self, vals_list):
        """Collection app: money came in on a case - one bonus per payment,
        straight to the CEO for approval."""
        bonuses = self.sudo().create([
            dict(vals, bonus_type="collection", state="pending_approval") for vals in vals_list
        ])
        bonuses._ask_ceo(_("Collection bonus awaiting your approval"))
        return bonuses

    @api.model
    def _create_handover_bonuses(self, projects):
        """Projects: a project was handed over / completed - a draft bonus
        for its project manager; the CEO sets the amount (500 - 3,500) and
        approves it."""
        existing = self.sudo().search([
            ("bonus_type", "=", "handover"),
            ("project_id", "in", projects.ids),
            ("state", "!=", "rejected"),
        ]).project_id
        vals_list = [
            {
                "employee_id": project.user_id.id,
                "bonus_type": "handover",
                "project_id": project.id,
                "incentive_amount": 0.0,
                "note": _("Created automatically: the project was handed over / set to complete. "
                          "Set the amount (500 - 3,500) and approve."),
            }
            for project in projects
            if project.user_id and project not in existing
        ]
        bonuses = self.sudo().create(vals_list)
        bonuses._ask_ceo(_("Set and approve the project handover bonus (500 - 3,500)"))
        return bonuses
