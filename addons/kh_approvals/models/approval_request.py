# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Khales Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    requester_id = fields.Many2one(
        "res.users", string="Requester",
        default=lambda self: self.env.user.id, tracking=True,
    )
    amount = fields.Monetary(string="Amount", currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
        required=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("in_review", "In Review"),
         ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft", required=True, tracking=True,
    )

    line_rule_ids = fields.Many2many("kh.approval.rule", string="Approval Route")
    approval_line_ids = fields.One2many(
        "kh.approval.line", "request_id", string="Approval Steps", copy=False
    )

    pending_line_id = fields.Many2one(
        "kh.approval.line", compute="_compute_pending_line", store=False
    )
    is_current_user_approver = fields.Boolean(
        compute="_compute_pending_line", store=False
    )

    # ---- FIX 1: make this recompute whenever lines or their approver/state change
    @api.depends(
        "approval_line_ids.state",
        "approval_line_ids.approver_id",
        "approval_line_ids.id",
    )
    def _compute_pending_line(self):
        uid = self.env.user.id
        for rec in self:
            # first pending step
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            rec.pending_line_id = line.id if line else False
            rec.is_current_user_approver = bool(line and line.approver_id.id == uid)

    # ---------------------------- Notifications ----------------------------
    def _ensure_followers(self):
        for rec in self:
            partners = rec.requester_id.partner_id
            partners |= rec.approval_line_ids.mapped("approver_id.partner_id")
            if partners:
                # subscribe with sudo to avoid edge ACL issues
                rec.sudo().message_subscribe(partner_ids=partners.ids)

    def _close_my_open_todos(self):
        for rec in self:
            acts = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)
            for a in acts:
                a.action_feedback(feedback=_("Done"))

    def _dm_ping(self, partner, body_html):
        """Send a direct message that triggers browser popup/sound (if allowed)."""
        self.ensure_one()
        me_partner = self.env.user.partner_id

        # Odoo 17/18
        if "discuss.channel" in self.env:
            Channel = self.env["discuss.channel"].sudo().with_context(mail_create_nolog=True)
            channel = Channel.search([
                ("channel_type", "=", "chat"),
                ("channel_member_ids.partner_id", "in", [partner.id]),
                ("channel_member_ids.partner_id", "in", [me_partner.id]),
            ], limit=1)
            if not channel:
                channel = Channel.create({
                    "name": f"{me_partner.name} ↔ {partner.name}",
                    "channel_type": "chat",
                    "channel_member_ids": [
                        (0, 0, {"partner_id": me_partner.id}),
                        (0, 0, {"partner_id": partner.id}),
                    ],
                })
            channel.message_post(body=body_html, message_type="comment",
                                 subtype_xmlid="mail.mt_comment")
            return

        # Odoo 16 fallback
        if "mail.channel" in self.env:
            Channel = self.env["mail.channel"].sudo().with_context(mail_create_nolog=True)
            channel = Channel.search([
                ("channel_type", "=", "chat"),
                ("channel_partner_ids", "in", [partner.id]),
                ("channel_partner_ids", "in", [me_partner.id]),
            ], limit=1)
            if not channel:
                channel = Channel.create({
                    "name": f"{me_partner.name} ↔ {partner.name}",
                    "channel_type": "chat",
                    "channel_partner_ids": [(6, 0, [partner.id, me_partner.id])],
                })
            channel.message_post(body=body_html, message_type="comment",
                                 subtype_xmlid="mail.mt_comment")
            return

        # Final fallback: chatter on document
        self.message_post(body=body_html, partner_ids=[partner.id],
                          subtype_xmlid="mail.mt_comment")

    def _notify_first_pending(self):
        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or not line.approver_id:
                continue

            # 1) Activity (clock) – run with sudo so it’s always created
            rec.sudo().activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=line.approver_id.id,
                summary=_("Approval needed"),
                note=_("Please review approval request: %s", rec.name),
            )

            # 2) Chatter (bell/inbox)
            rec.sudo().message_post(
                body=_("Approval needed from <b>%s</b>.") % line.approver_id.name,
                partner_ids=[line.approver_id.partner_id.id],
                subtype_xmlid="mail.mt_comment",
            )

            # 3) Direct chat ping (native notification + sound)
            link = f"/web#id={rec.id}&model=kh.approval.request&view_type=form"
            html = _("🔔 <b>Approval needed</b> for: "
                     "<a href='%s'>%s</a><br/>Requester: %s") % (link, rec.name, rec.requester_id.name)
            rec._dm_ping(line.approver_id.partner_id, html)

    # ------------------------------ Actions ------------------------------
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
                link = f"/web#id={rec.id}&model=kh.approval.request&view_type=form"
                rec._dm_ping(
                    rec.requester_id.partner_id,
                    _("✅ <b>Approved</b>: <a href='%s'>%s</a>") % (link, rec.name),
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
            link = f"/web#id={rec.id}&model=kh.approval.request&view_type=form"
            rec._dm_ping(
                rec.requester_id.partner_id,
                _("❌ <b>Rejected</b>: <a href='%s'>%s</a>") % (link, rec.name),
            )
        return True


class KhApprovalRule(models.Model):
    _name = "kh.approval.rule"
    _description = "Approval Rule"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    role = fields.Selection(
        [("manager", "Management"), ("finance", "Finance")],
        default="manager", required=True,
    )
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
        default="pending", required=True,
    )
    note = fields.Char()
