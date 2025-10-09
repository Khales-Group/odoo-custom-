# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Khales Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # Basic fields
    name = fields.Char(required=True, tracking=True)
    requester_id = fields.Many2one(
        "res.users", string="Requester",
        default=lambda self: self.env.user.id, tracking=True)
    amount = fields.Monetary(string="Amount", currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
        required=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("in_review", "In Review"),
         ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft", required=True, tracking=True)

    # Routing and steps
    line_rule_ids = fields.Many2many("kh.approval.rule", string="Approval Route")
    approval_line_ids = fields.One2many(
        "kh.approval.line", "request_id", string="Approval Steps", copy=False)

    # UI helpers
    pending_line_id = fields.Many2one("kh.approval.line", compute="_compute_pending_line", store=False)
    is_current_user_approver = fields.Boolean(compute="_compute_pending_line", store=False)

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    def _compute_pending_line(self):
        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            rec.pending_line_id = line.id if line else False
            rec.is_current_user_approver = bool(line and line.approver_id.id == rec.env.user.id)

    # -------------------------------------------------------------------------
    # Helpers - followers & notifications
    # -------------------------------------------------------------------------
    def _ensure_followers(self):
        """Subscribe requester + all approvers so they see inbox notifications."""
        for rec in self:
            partners = rec.requester_id.partner_id
            partners |= rec.approval_line_ids.mapped("approver_id.partner_id")
            if partners:
                rec.message_subscribe(partner_ids=partners.ids)

    def _close_my_open_todos(self):
        """Mark my open To-Do activities on this request as done."""
        for rec in self:
            acts = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)
            for a in acts:
                a.action_feedback(feedback=_("Done"))

    def _notify_first_pending(self):
        """Create a To-Do for the first pending approver and ping them in chatter."""
        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if line and line.approver_id:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=line.approver_id.id,
                    summary=_("Approval needed"),
                    note=_("Please review approval request: %s", rec.name),
                )
                rec.message_post(
                    body=_("Approval needed from <b>%s</b>.") % line.approver_id.name,
                    partner_ids=[line.approver_id.partner_id.id],
                    subtype_xmlid="mail.mt_comment",
                )

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            rec._build_approval_lines()
            rec._ensure_followers()
            rec.state = "in_review"
            rec.message_post(body=_("Request submitted for approval."))
            rec._notify_first_pending()
        return True

    def action_approve_request(self):
        for rec in self:
            if rec.state != "in_review":
                continue

            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or line.approver_id.id != self.env.uid:
                raise UserError(_("You are not the current approver."))

            rec._close_my_open_todos()
            line.write({"state": "approved"})
            rec.message_post(
                body=_("Approved by <b>%s</b>.") % self.env.user.name,
                partner_ids=[rec.requester_id.partner_id.id],
                subtype_xmlid="mail.mt_comment",
            )

            next_line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if next_line:
                rec._notify_first_pending()
            else:
                rec.state = "approved"
                rec.message_post(
                    body=_("✅ Request approved."),
                    partner_ids=[rec.requester_id.partner_id.id],
                    subtype_xmlid="mail.mt_comment",
                )
        return True

    def action_reject_request(self):
        for rec in self:
            if rec.state != "in_review":
                continue

            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or line.approver_id.id != self.env.uid:
                raise UserError(_("You are not the current approver."))

            rec._close_my_open_todos()
            line.write({"state": "rejected"})
            rec.state = "rejected"
            rec.message_post(
                body=_("❌ Rejected by <b>%s</b>.") % self.env.user.name,
                partner_ids=[rec.requester_id.partner_id.id],
                subtype_xmlid="mail.mt_comment",
            )
        return True

    # -------------------------------------------------------------------------
    # Build steps from rules
    # -------------------------------------------------------------------------
    def _build_approval_lines(self):
        for rec in self:
            rec.approval_line_ids.sudo().unlink()
            rules = rec.line_rule_ids.sorted(key=lambda r: (r.sequence, r.id))
            vals = []
            for rule in rules:
                if rule.min_amount and rec.amount < rule.min_amount:
                    continue
                if not rule.user_id:
                    continue
                vals.append({
                    "request_id": rec.id,
                    "name": rule.name,
                    "approver_id": rule.user_id.id,
                    "required": True,
                    "state": "pending",
                })
            if not vals:
                raise UserError(_("No matching approval rules or missing approvers."))
            self.env["kh.approval.line"].create(vals)


class KhApprovalRule(models.Model):
    _name = "kh.approval.rule"
    _description = "Approval Rule"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    role = fields.Selection([("manager", "Management"), ("finance", "Finance")],
                            default="manager", required=True)
    user_id = fields.Many2one("res.users", string="Approver")
    min_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
        required=True,
    )


class KhApprovalLine(models.Model):
    _name = "kh.approval.line"
    _description = "Approval Step"
    _order = "id"

    request_id = fields.Many2one("kh.approval.request", required=True, ondelete="cascade")
    name = fields.Char()
    approver_id = fields.Many2one("res.users", required=True)
    required = fields.Boolean(default=True)
    state = fields.Selection(
        [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending", required=True)
    note = fields.Char()
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Khales Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # Basic fields
    name = fields.Char(required=True, tracking=True)
    requester_id = fields.Many2one(
        "res.users", string="Requester",
        default=lambda self: self.env.user.id, tracking=True)
    amount = fields.Monetary(string="Amount", currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
        required=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("in_review", "In Review"),
         ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft", required=True, tracking=True)

    # Routing and steps
    line_rule_ids = fields.Many2many("kh.approval.rule", string="Approval Route")
    approval_line_ids = fields.One2many(
        "kh.approval.line", "request_id", string="Approval Steps", copy=False)

    # UI helpers
    pending_line_id = fields.Many2one("kh.approval.line", compute="_compute_pending_line", store=False)
    is_current_user_approver = fields.Boolean(compute="_compute_pending_line", store=False)

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    def _compute_pending_line(self):
        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            rec.pending_line_id = line.id if line else False
            rec.is_current_user_approver = bool(line and line.approver_id.id == rec.env.user.id)

    # -------------------------------------------------------------------------
    # Helpers - followers & notifications
    # -------------------------------------------------------------------------
    def _ensure_followers(self):
        """Subscribe requester + all approvers so they see inbox notifications."""
        for rec in self:
            partners = rec.requester_id.partner_id
            partners |= rec.approval_line_ids.mapped("approver_id.partner_id")
            if partners:
                rec.message_subscribe(partner_ids=partners.ids)

    def _close_my_open_todos(self):
        """Mark my open To-Do activities on this request as done."""
        for rec in self:
            acts = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)
            for a in acts:
                a.action_feedback(feedback=_("Done"))

    def _notify_first_pending(self):
        """Create a To-Do for the first pending approver and ping them in chatter."""
        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if line and line.approver_id:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=line.approver_id.id,
                    summary=_("Approval needed"),
                    note=_("Please review approval request: %s", rec.name),
                )
                rec.message_post(
                    body=_("Approval needed from <b>%s</b>.") % line.approver_id.name,
                    partner_ids=[line.approver_id.partner_id.id],
                    subtype_xmlid="mail.mt_comment",
                )

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            rec._build_approval_lines()
            rec._ensure_followers()
            rec.state = "in_review"
            rec.message_post(body=_("Request submitted for approval."))
            rec._notify_first_pending()
        return True

    def action_approve_request(self):
        for rec in self:
            if rec.state != "in_review":
                continue

            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or line.approver_id.id != self.env.uid:
                raise UserError(_("You are not the current approver."))

            rec._close_my_open_todos()
            line.write({"state": "approved"})
            rec.message_post(
                body=_("Approved by <b>%s</b>.") % self.env.user.name,
                partner_ids=[rec.requester_id.partner_id.id],
                subtype_xmlid="mail.mt_comment",
            )

            next_line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if next_line:
                rec._notify_first_pending()
            else:
                rec.state = "approved"
                rec.message_post(
                    body=_("✅ Request approved."),
                    partner_ids=[rec.requester_id.partner_id.id],
                    subtype_xmlid="mail.mt_comment",
                )
        return True

    def action_reject_request(self):
        for rec in self:
            if rec.state != "in_review":
                continue

            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or line.approver_id.id != self.env.uid:
                raise UserError(_("You are not the current approver."))

            rec._close_my_open_todos()
            line.write({"state": "rejected"})
            rec.state = "rejected"
            rec.message_post(
                body=_("❌ Rejected by <b>%s</b>.") % self.env.user.name,
                partner_ids=[rec.requester_id.partner_id.id],
                subtype_xmlid="mail.mt_comment",
            )
        return True

    # -------------------------------------------------------------------------
    # Build steps from rules
    # -------------------------------------------------------------------------
    def _build_approval_lines(self):
        for rec in self:
            rec.approval_line_ids.sudo().unlink()
            rules = rec.line_rule_ids.sorted(key=lambda r: (r.sequence, r.id))
            vals = []
            for rule in rules:
                if rule.min_amount and rec.amount < rule.min_amount:
                    continue
                if not rule.user_id:
                    continue
                vals.append({
                    "request_id": rec.id,
                    "name": rule.name,
                    "approver_id": rule.user_id.id,
                    "required": True,
                    "state": "pending",
                })
            if not vals:
                raise UserError(_("No matching approval rules or missing approvers."))
            self.env["kh.approval.line"].create(vals)


class KhApprovalRule(models.Model):
    _name = "kh.approval.rule"
    _description = "Approval Rule"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    role = fields.Selection([("manager", "Management"), ("finance", "Finance")],
                            default="manager", required=True)
    user_id = fields.Many2one("res.users", string="Approver")
    min_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
        required=True,
    )


class KhApprovalLine(models.Model):
    _name = "kh.approval.line"
    _description = "Approval Step"
    _order = "id"

    request_id = fields.Many2one("kh.approval.request", required=True, ondelete="cascade")
    name = fields.Char()
    approver_id = fields.Many2one("res.users", required=True)
    required = fields.Boolean(default=True)
    state = fields.Selection(
        [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending", required=True)
    note = fields.Char()
