from odoo import api, fields, models, _
from odoo.exceptions import UserError

class KhApprovalRule(models.Model):
    _name = "kh.approval.rule"
    _description = "Approval Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    role = fields.Selection([
        ("line_manager","Line Manager"),
        ("project_manager","Project Manager"),
        ("finance","Finance"),
        ("director","Director"),
    ], required=True, default="line_manager")
    user_id = fields.Many2one("res.users", string="Specific Approver")
    min_amount = fields.Monetary("Min Amount")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    required = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    requester_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True, tracking=True)
    amount = fields.Monetary(tracking=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    state = fields.Selection([
        ("draft","Draft"),
        ("in_review","In Review"),
        ("approved","Approved"),
        ("rejected","Rejected"),
    ], default="draft", tracking=True)
    rule_ids = fields.Many2many("kh.approval.rule", string="Approval Route")
    approval_line_ids = fields.One2many("kh.approval.line", "request_id")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    def action_submit(self):
        for rec in self:
            if not rec.rule_ids:
                raise UserError(_("No approval rules on this request."))
            rec._generate_lines_from_rules()
            rec.state = "in_review"
            rec.activity_schedule('mail.mail_activity_data_todo', user_id=rec.requester_id.id, note=_("Request submitted for approval."))

    def _generate_lines_from_rules(self):
        for rec in self:
            rec.approval_line_ids.unlink()
            lines = []
            for rule in rec.rule_ids.sorted(lambda r: r.sequence):
                if rule.min_amount and rec.amount and rec.amount < rule.min_amount:
                    continue
                approver = rule.user_id or rec._resolve_role_to_user(rule.role)
                lines.append((0, 0, {
                    "name": rule.name,
                    "approver_id": approver.id,
                    "required": rule.required,
                    "state": "pending",
                }))
            if not lines:
                raise UserError(_("No approval steps generated from rules."))
            rec.write({"approval_line_ids": lines})

    def _resolve_role_to_user(self, role):
        # Basic default: requester’s manager if set; otherwise requester.
        # You can implement real business logic later (e.g., department manager, PM, finance group).
        return self.requester_id

    def _check_all_approved(self):
        for rec in self:
            required_lines = rec.approval_line_ids.filtered(lambda l: l.required)
            if required_lines and all(l.state == "approved" for l in required_lines):
                rec.state = "approved"

class KhApprovalLine(models.Model):
    _name = "kh.approval.line"
    _description = "Approval Step"
    _order = "id"

    name = fields.Char()
    request_id = fields.Many2one("kh.approval.request", required=True, ondelete="cascade")
    approver_id = fields.Many2one("res.users", required=True)
    required = fields.Boolean(default=True)
    state = fields.Selection([("pending","Pending"),("approved","Approved"),("rejected","Rejected")], default="pending")
    note = fields.Text()

    def action_approve(self):
        for line in self:
            line.state = "approved"
            line.request_id.message_post(body=_("Step approved by %s") % (line.approver_id.name or ''))
            line.request_id._check_all_approved()

    def action_reject(self):
        for line in self:
            line.state = "rejected"
            line.request_id.state = "rejected"
            line.request_id.message_post(body=_("Step rejected by %s") % (line.approver_id.name or ''))
