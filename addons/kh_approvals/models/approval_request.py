# addons/kh_approvals/models/approval_request.py
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Khales Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # --- Fields ---
    name = fields.Char(required=True, tracking=True)
    requester_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user.id,
        tracking=True,
    )
    amount = fields.Monetary(currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_review", "In Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        tracking=True,
    )

    line_rule_ids = fields.Many2many(
        "kh.approval.rule",
        string="Approval Route",
    )
    approval_line_ids = fields.One2many(
        "kh.approval.line",
        "request_id",
        string="Approval Steps",
    )

    # --- Helpers ---
    def _build_approval_lines(self):
        """(Re)generate approval steps from selected rules."""
        for rec in self:
            # Clear previous steps even if user has no unlink rights
            rec.approval_line_ids.sudo().unlink()

            rules = rec.line_rule_ids.sorted(key=lambda r: (r.sequence, r.id))
            vals_list = []
            for rule in rules:
                if rule.min_amount and rec.amount < rule.min_amount:
                    continue
                if not rule.user_id:
                    continue
                vals_list.append(
                    {
                        "request_id": rec.id,
                        "name": rule.name,
                        "approver_id": rule.user_id.id,
                        "required": True,
                        "state": "pending",
                    }
                )
            if not vals_list:
                raise UserError(_("No matching approval rules or missing approvers."))

            self.env["kh.approval.line"].create(vals_list)

    def _notify_first_pending(self):
        """Create a To-Do activity for the first pending approver."""
        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if line and line.approver_id:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("Approval needed"),
                    note=_("Please review approval request: %s", rec.name),
                    user_id=line.approver_id.id,
                )

    # --- Actions ---
    def action_submit(self):
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
    role = fields.Selection(
        [("manager", "Management"), ("finance", "Finance")],
        default="manager",
    )
    user_id = fields.Many2one("res.users", string="Approver")
    min_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
    )


class KhApprovalLine(models.Model):
    _name = "kh.approval.line"
    _description = "Approval Step"
    _order = "id"

    request_id = fields.Many2one(
        "kh.approval.request",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char()
    approver_id = fields.Many2one("res.users", required=True)
    required = fields.Boolean(default=True)
    state = fields.Selection(
        [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending",
    )
    note = fields.Char()

    # Approver actions
    def action_approve(self):
        for rec in self:
            rec.state = "approved"
            req = rec.request_id
            if all(l.state == "approved" or not l.required for l in req.approval_line_ids):
                req.state = "approved"
        return True

    def action_reject(self):
        for rec in self:
            rec.state = "rejected"
            rec.request_id.state = "rejected"
        return True
