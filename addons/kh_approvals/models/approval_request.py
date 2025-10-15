# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Khales Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # -------------------------------------------------------------------------
    # Fields
    # -------------------------------------------------------------------------
    name = fields.Char(required=True, tracking=True)

    requester_id = fields.Many2one(
        "res.users",
        string="Requester",
        default=lambda self: self.env.user.id,
        tracking=True,
    )

    amount = fields.Monetary(string="Amount", currency_field="currency_id", tracking=True)

    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
        required=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_review", "In Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )

    # Approval route (rules chosen by user)
    line_rule_ids = fields.Many2many("kh.approval.rule", string="Approval Route")

    # Concrete steps generated from rules
    approval_line_ids = fields.One2many(
        "kh.approval.line", "request_id", string="Approval Steps", copy=False
    )

    # Helper fields for UI logic
    pending_line_id = fields.Many2one(
        "kh.approval.line", compute="_compute_pending_line", store=False
    )
    is_current_user_approver = fields.Boolean(
        compute="_compute_pending_line", store=False
    )

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    @api.depends("approval_line_ids.state", "approval_line_ids.approver_id")
    def _compute_pending_line(self):
        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            rec.pending_line_id = line.id if line else False
            rec.is_current_user_approver = bool(
                line and line.approver_id.id == rec.env.user.id
            )

    # -------------------------------------------------------------------------
    # Helpers - Links
    # -------------------------------------------------------------------------
    def _deeplink(self):
        """Return a stable /web# deeplink to this record (form view)."""
        self.ensure_one()
        return f"/web#id={self.id}&model=kh.approval.request&view_type=form"

    # -------------------------------------------------------------------------
    # Helpers - Followers & Notifications (incl. desktop popup + sound)
    # -------------------------------------------------------------------------
    def _ensure_followers(self):
        """Subscribe requester + all approvers so they see inbox notifications."""
        for rec in self:
            partners = rec.requester_id.partner_id
            partners |= rec.approval_line_ids.mapped("approver_id.partner_id")
            if partners:
                # Do not let subscription failures roll back the main transaction
                with rec.env.cr.savepoint():
                    rec.message_subscribe(partner_ids=partners.ids)

    def _close_my_open_todos(self):
        """Mark my open To-Do activities on this request as done for the current user."""
        for rec in self:
            acts = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)
            for a in acts:
                a.action_feedback(feedback=_("Done"))

    def _dm_ping(self, partner, body_html):
        """
        Try to send a direct chat message (native browser popup + sound when allowed).
        Supports Odoo 17/18 (discuss.channel) and Odoo 16- (mail.channel).
        Never raises; falls back to a chatter message if chat models are unavailable.
        """
        self.ensure_one()
        me_partner = self.env.user.partner_id

        try:
            # Odoo 17/18 – discuss.channel
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
                channel.message_post(
                    body=body_html,
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
                return

            # Odoo 16 and earlier – mail.channel
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
                channel.message_post(
                    body=body_html,
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
                return

        except Exception:
            # Do not break the main flow if DM fails for any reason
            pass

        # Fallback: regular chatter ping so the user still gets notified in Inbox
        self.message_post(
            body=body_html,
            partner_ids=[partner.id],
            subtype_xmlid="mail.mt_comment",
        )

    def _notify_first_pending(self):
        """
        Create a To-Do for the first pending approver, post in chatter,
        and ping them in direct chat (desktop popup + sound).
        """
        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or not line.approver_id:
                continue

            # 1) Activity (clock icon)
            with rec.env.cr.savepoint():
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=line.approver_id.id,
                    summary=_("Approval needed"),
                    note=_("Please review approval request: %s") % rec.name,
                )

            # 2) Chatter (bell/inbox)
            with rec.env.cr.savepoint():
                rec.message_post(
                    body=_("Approval needed from <b>%s</b>.") % line.approver_id.name,
                    partner_ids=[line.approver_id.partner_id.id],
                    subtype_xmlid="mail.mt_comment",
                )

            # 3) Direct chat ping (native notification + sound)
            with rec.env.cr.savepoint():
                html = _(
                    "🔔 <b>Approval needed</b> for: "
                    "<a href='%(link)s'>%(name)s</a><br/>Requester: %(req)s"
                ) % {"link": rec._deeplink(), "name": rec.name, "req": rec.requester_id.name}
                rec._dm_ping(line.approver_id.partner_id, html)

    # -------------------------------------------------------------------------
    # Actions (buttons)
    # -------------------------------------------------------------------------
    def action_submit(self):
        """Requester submits: build steps, move to in_review, ping first approver."""
        for rec in self:
            if rec.state != "draft":
                continue
            rec._build_approval_lines()
            with rec.env.cr.savepoint():
                rec._ensure_followers()
            rec.state = "in_review"
            with rec.env.cr.savepoint():
                rec.message_post(body=_("Request submitted for approval."))
            with rec.env.cr.savepoint():
                rec._notify_first_pending()
        return True

    def action_approve_request(self):
        """Current approver approves their step; finish or notify next approver."""
        for rec in self:
            if rec.state != "in_review":
                continue

            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or line.approver_id.id != self.env.uid:
                raise UserError(_("You are not the current approver."))

            # Close my To-Do on this document
            rec._close_my_open_todos()

            # Approve my step
            line.write({"state": "approved"})
            with rec.env.cr.savepoint():
                rec.message_post(
                    body=_("Approved by <b>%s</b>.") % self.env.user.name,
                    partner_ids=[rec.requester_id.partner_id.id],
                    subtype_xmlid="mail.mt_comment",
                )

            # Next approver or finished
            next_line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if next_line:
                with rec.env.cr.savepoint():
                    rec._notify_first_pending()
            else:
                rec.state = "approved"
                with rec.env.cr.savepoint():
                    rec.message_post(
                        body=_("✅ Request approved."),
                        partner_ids=[rec.requester_id.partner_id.id],
                        subtype_xmlid="mail.mt_comment",
                    )
                # DM the requester with a popup + sound
                with rec.env.cr.savepoint():
                    rec._dm_ping(
                        rec.requester_id.partner_id,
                        _("✅ <b>Approved</b>: <a href='%s'>%s</a>") % (rec._deeplink(), rec.name),
                    )
        return True

    def action_reject_request(self):
        """Current approver rejects; request becomes Rejected and requester is pinged."""
        for rec in self:
            if rec.state != "in_review":
                continue

            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or line.approver_id.id != self.env.uid:
                raise UserError(_("You are not the current approver."))

            rec._close_my_open_todos()
            line.write({"state": "rejected"})
            rec.state = "rejected"
            with rec.env.cr.savepoint():
                rec.message_post(
                    body=_("❌ Rejected by <b>%s</b>.") % self.env.user.name,
                    partner_ids=[rec.requester_id.partner_id.id],
                    subtype_xmlid="mail.mt_comment",
                )

            # DM the requester with a popup + sound
            with rec.env.cr.savepoint():
                rec._dm_ping(
                    rec.requester_id.partner_id,
                    _("❌ <b>Rejected</b>: <a href='%s'>%s</a>") % (rec._deeplink(), rec.name),
                )
        return True

    # -------------------------------------------------------------------------
    # Steps generation
    # -------------------------------------------------------------------------
    def _build_approval_lines(self):
        """
        (Re)generate approval steps based on selected rules and request amount.
        Uses sudo() to remove previous steps even if the end-user lacks unlink rights.
        """
        for rec in self:
            rec.approval_line_ids.sudo().unlink()

            rules = rec.line_rule_ids.sorted(key=lambda r: (r.sequence, r.id))
            vals = []
            for rule in rules:
                # NOTE: simple same-currency comparison; if you mix currencies
                # add conversion: rule.currency_id._convert(rule.min_amount, rec.currency_id, rec.company_id, fields.Date.today())
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
    role = fields.Selection(
        [("manager", "Management"), ("finance", "Finance")],
        default="manager",
        required=True,
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
        default="pending",
        required=True,
    )
    note = fields.Char()
