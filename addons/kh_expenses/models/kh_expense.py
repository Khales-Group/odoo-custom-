# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

MAJID_ID = 369  # Majed - the manager; every payment needs his approval (same as kh_collection)

EXPENSE_TYPES = [
    ("rent", "Rent"),
    ("salary", "Salary"),
    ("eos", "End of Service"),
    ("employee", "Employee Expense"),
    ("owner_payment", "Owner Payment"),
    ("internet", "Internet"),
    ("telephone", "Telephone"),
    ("utilities", "Water & Electricity"),
    ("connection", "FEWA / DEWA Connection"),
    ("ac_payment", "AC Payment"),
    ("lawyer_fees", "Lawyer Fees"),
    ("interior_design", "Interior Design"),
    ("contractor_payment", "Contractor Payment"),
    ("supplier", "Supplier"),
    ("subcontractor", "Sub Contractor"),
    ("finish_work", "Finish Work"),
    ("government", "Government Fees"),
    ("other", "Other"),
]


class KhExpense(models.Model):
    _name = "kh.expense"
    _description = "Expense"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "due_date asc, id desc"

    name = fields.Char(string="Description", required=True, tracking=True)
    expense_type = fields.Selection(
        EXPENSE_TYPES, string="Type", default="other", required=True, tracking=True,
    )
    category = fields.Selection(
        [("company", "Company"), ("project", "Projects")],
        string="Section", default="company", required=True, tracking=True,
        help="Company: the office's own expenses. Projects: what is owed on the projects.",
    )
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company, tracking=True,
    )
    creditor = fields.Char(string="Vendor / Creditor", tracking=True)
    partner_id = fields.Many2one(
        "res.partner", string="Contact", tracking=True,
        help="Landlord, supplier, authority... who receives the money.",
    )
    employee_id = fields.Many2one(
        "hr.employee", string="Employee", tracking=True,
        help="For an employee expense: the employee who paid it or is owed it.",
    )
    project_id = fields.Many2one("project.project", string="Project", tracking=True)
    currency_id = fields.Many2one(
        "res.currency", string="Currency", default=lambda self: self.env.company.currency_id
    )
    amount = fields.Monetary(string="Amount", required=True, tracking=True)
    paid_amount = fields.Monetary(string="Paid", tracking=True)
    balance_amount = fields.Monetary(
        string="Remaining", compute="_compute_balance_amount", store=True
    )
    month_amount = fields.Monetary(
        string="This Month", tracking=True, help="What has to be paid this month.",
    )
    due_date = fields.Date(string="Due Date", tracking=True)
    pdc_issued = fields.Boolean(string="PDC Issued", tracking=True)
    pdc_cheque_no = fields.Char(string="PDC Cheque No.", tracking=True)
    pdc_date = fields.Date(string="PDC Date", tracking=True)
    followup = fields.Char(string="With / Project", help="Who follows it up, or the project's owner.")
    is_overdue = fields.Boolean(compute="_compute_is_overdue")
    recurring = fields.Boolean(
        string="Every Month", tracking=True,
        help="Rent, water... When it is paid, next month's expense is created.",
    )
    accountant_id = fields.Many2one(
        "res.users", string="Accountant", default=lambda self: self._default_accountant(),
        required=True, tracking=True,
    )
    note = fields.Text(string="Notes")
    state = fields.Selection(
        [
            ("to_pay", "To Pay"),
            ("pending_approval", "Pending Manager Approval"),
            ("approved", "Approved"),
            ("paid", "Paid"),
        ],
        string="Status", default="to_pay", required=True, tracking=True,
    )
    next_expense_id = fields.Many2one("kh.expense", string="Next Month", readonly=True, copy=False)
    is_manager = fields.Boolean(compute="_compute_is_manager")

    @api.model
    def _default_accountant(self):
        # Same lookup as kh_collection: Karan by name, the user id differs
        # between databases.
        karan = self.env["res.users"].sudo().search([("name", "ilike", "karan")], limit=1)
        return karan or self.env.user

    @api.depends("amount", "paid_amount")
    def _compute_balance_amount(self):
        for rec in self:
            rec.balance_amount = rec.amount - rec.paid_amount

    @api.depends("due_date", "state")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(rec.due_date and rec.due_date < today and rec.state != "paid")

    def _compute_is_manager(self):
        for rec in self:
            rec.is_manager = self.env.user.id == MAJID_ID

    def _check_is_manager(self):
        if self.env.user.id != MAJID_ID:
            raise UserError(_("Only the manager can approve payments."))

    def _close_manager_activities(self, feedback):
        self.activity_ids.filtered(lambda a: a.user_id.id == MAJID_ID).action_feedback(feedback=feedback)

    def action_request_approval(self):
        manager = self.env["res.users"].browse(MAJID_ID)
        for rec in self:
            if rec.state != "to_pay":
                raise UserError(_("You can only ask for approval while the expense is 'To Pay'."))
            rec.state = "pending_approval"
            message = _("%(who)s asks to pay %(amount)s for %(name)s.") % {
                "who": self.env.user.name, "amount": rec.balance_amount or rec.amount, "name": rec.name,
            }
            if manager.exists():
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=manager.id,
                    summary=_("Approval needed: expense payment"),
                    note=message,
                )
            rec.message_post(body=message)

    def action_approve(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_approval":
                raise UserError(_("This expense is not waiting for approval."))
            rec.state = "approved"
            rec._close_manager_activities(_("Approved"))
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=rec.accountant_id.id,
                summary=_("Payment approved - pay it"),
                note=_("Majed approved paying %s.") % rec.name,
            )
            rec.message_post(body=_("Manager approved the payment."))

    def action_reject(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_approval":
                continue
            rec.state = "to_pay"
            rec._close_manager_activities(_("Rejected"))
            rec.message_post(body=_("Manager rejected the payment - back to the accountant."))

    def action_mark_paid(self):
        for rec in self:
            if rec.state != "approved" and self.env.user.id != MAJID_ID:
                raise UserError(_("The payment needs the manager's approval first."))
            vals = {"state": "paid"}
            if not rec.paid_amount:
                vals["paid_amount"] = rec.amount
            rec.write(vals)
            rec.activity_ids.action_feedback(feedback=_("Paid"))
            rec.message_post(body=_("Paid."))
            if rec.recurring and not rec.next_expense_id:
                rec.next_expense_id = rec.copy({
                    "due_date": rec.due_date and rec.due_date + relativedelta(months=1),
                    "paid_amount": 0.0,
                    "state": "to_pay",
                })
