from odoo import api, fields, models, _
from odoo.exceptions import UserError

class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Khales Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    requester_id = fields.Many2one("res.users", default=lambda self: self.env.user, tracking=True)
    amount = fields.Monetary(currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id.id)
    state = fields.Selection(
        [("draft", "Draft"), ("in_review", "In Review"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft", tracking=True
    )
    line_rule_ids = fields.Many2many("kh.approval.rule", string="Approval Route")
    approval_line_ids = fields.One2many("kh.approval.line", "request_id", string="Approval Steps")

    def _build_approval_lines(self):
        """Create approval_line_ids from line_rule_ids, applying min_amount filters and sequence."""
        for rec in self:
            rec.approval_line_ids.unlink()
            rules = rec.line_rule_ids.sorted(key=lambda r: (r.sequence, r.id))
            vals_list = []
            for rule in rules:
                if rule.min_amount and rec.amount < rule.min_amount:
                    continue
                vals_list.append({
                    "request_id": rec.id,
                    "name": rule.name,
                    "approver_id": rule.user_id.id,
                    "required": True,
                    "state": "pending",
                })
            if not vals_list:
                raise UserError(_("No matching approval rules for this amount."))
            self.env["kh.approval.line"].create(vals_list)

    def _notify_first_pending(self):
        """Assign activity/email for first pending line."""
        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if line and line.approver_id:
                # Activity in chatter
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=line.approver_id.id,
                    note=_("Please review approval request: %s", rec.name),
                )
                # Simple email (optional – remove if you don’t want emails)
                template = self.env.ref("mail.email_template_partner", raise_if_not_found=False)
                if template:
                    template.sudo().send_mail(rec.id, force_send=False, email_values={"email_to": line.approver_id.partner_id.email})

    def action_submit(self):
        """Submit request: generate steps, set state, notify approver."""
        for rec in self:
            if rec.state != "draft":
                continue
            rec._build_approval_lines()
            rec.state = "in_review"
            rec._notify_first_pending()
        return True

class KhApprovalRule(models.Model):
    _name = "kh.approval.rule"
    _description = "Approval Rule"
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    user_id = fields.Many2one("res.users", string="Approver")
    min_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id.id)
    role = fields.Selection([("manager","Management"), ("finance","Finance")], default="manager")

class KhApprovalLine(models.Model):
    _name = "kh.approval.line"
    _description = "Approval Step"
    _order = "id"

    request_id = fields.Many2one("kh.approval.request", required=True, ondelete="cascade")
    name = fields.Char()
    approver_id = fields.Many2one("res.users", required=True)
    required = fields.Boolean(default=True)
    state = fields.Selection([("pending","Pending"), ("approved","Approved"), ("rejected","Rejected")], default="pending")
    note = fields.Char()

    def action_approve(self):
        for rec in self:
            rec.state = "approved"
            # if all required lines approved -> request approved
            req = rec.request_id
            if all(l.state == "approved" or not l.required for l in req.approval_line_ids):
                req.state = "approved"
        return True

    def action_reject(self):
        for rec in self:
            rec.state = "rejected"
            rec.request_id.state = "rejected"
        return True
