# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


# ============================================================================
# Approval Request
# ============================================================================
class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Khales Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True

    # -------------------------------------------------------------------------
    # Fields
    # -------------------------------------------------------------------------
    name = fields.Char(required=True, tracking=True)

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        tracking=True,
    )

    department_id = fields.Many2one(
        "kh.approvals.department",
        string="Department",
        tracking=True,
    )

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
        tracking=True,  # tracking is fine; we'll disable it at write-time to avoid emails
    )

    # Single rule selector (rule defines company/department/approver sequence)
    rule_id = fields.Many2one(
        "kh.approval.rule",
        string="Approval Rule",
        required=True,
        domain="[('company_id','in',[False, company_id]), '|', ('department_id','=',False), ('department_id','=',department_id)]",
        tracking=True,
    )

    # Concrete steps generated from the rule's step_ids
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
    # ORM overrides
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Assign company, department (from rule if empty), and company-scoped name/sequence."""
        for vals in vals_list:
            # company default
            vals.setdefault("company_id", self.env.company.id)

            # name from sequence, scoped by company
            if not vals.get("name"):
                seq = self.env["ir.sequence"].with_context(
                    force_company=vals["company_id"]
                ).next_by_code("kh.approval.request")
                vals["name"] = seq or _("New")

            # auto-pick department from chosen rule if left empty
            if vals.get("rule_id") and not vals.get("department_id"):
                rule = self.env["kh.approval.rule"].browse(vals["rule_id"])
                vals["department_id"] = rule.department_id.id
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # Helpers - Links
    # -------------------------------------------------------------------------
    def _deeplink(self):
        """Return a stable /web# deeplink to this record (form view)."""
        self.ensure_one()
        return f"/web#id={self.id}&model=kh.approval.request&view_type=form"

    # -------------------------------------------------------------------------
    # Helpers - Silent chatter & notifications (NO EMAIL)
    # -------------------------------------------------------------------------
    def _post_note(self, body_html, partner_ids=None):
        """
        Post an INTERNAL NOTE only (no email, no auto-subscribe).
        Appears in chatter & Discuss/Inbox; safe on servers without SMTP.
        """
        self.with_context(
            mail_notify_force_send=False,   # never attempt to send right now
            mail_post_autofollow=False,
            mail_create_nosubscribe=True,
        ).message_post(
            body=body_html,
            message_type="comment",
            subtype_xmlid="mail.mt_note",   # note subtype => no email
            email_layout_xmlid="mail.mail_notification_light",  # force no email
            partner_ids=partner_ids or [],
        )

    def _ensure_followers(self):
        """Subscribe requester + all approvers so they see inbox notifications."""
        for rec in self:
            partners = rec.requester_id.partner_id
            partners |= rec.approval_line_ids.mapped("approver_id.partner_id")
            if partners:
                with rec.env.cr.savepoint():
                    # Use mail_post_autofollow to prevent "You are now following" emails
                    rec.with_context(mail_post_autofollow=True).message_subscribe(
                        partner_ids=partners.ids)

    def _activity_done_silent(self, activity):
        """
        Mark an activity as done and post feedback silently (NO EMAIL).
        This bypasses the standard action_feedback which can trigger emails.
        """
        self.ensure_one()
        # Post the feedback message silently first
        self.with_context(mail_activity_quick_update=True)._post_note(
            body_html=f"<div>{activity.activity_type_id.name}: Done</div>",
            partner_ids=self.message_follower_ids.mapped("partner_id").ids,
        )
        # Unlink the activity
        activity.with_context(kh_from_mark_done=True).unlink()

    def _close_my_open_todos(self):
        """Mark my open To-Do activities on this request as done for the current user."""
        for rec in self:
            acts = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)
            if acts:
                rec._activity_done_silent(acts)

    def _dm_ping(self, partner, body_html):
        """
        Direct chat ping (popup + sound) — NO SMTP.
        Tries discuss.channel (Odoo 17/18) or mail.channel (Odoo 16-).
        Falls back to an internal note if channels aren’t available.
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
                    email_layout_xmlid="mail.mail_notification_light",  # force no email
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
                    email_layout_xmlid="mail.mail_notification_light",  # force no email
                )
                return

        except Exception:
            pass  # never block approval flow on chat issues

        # Fallback: internal note ping (still NO email)
        self._post_note(body_html, partner_ids=[partner.id])

    def _notify_first_pending(self):
        """
        Create a To-Do for the first pending approver, post an internal note,
        and ping them via chat. None of these requires SMTP.
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

            # 2) Chatter (internal note; NO email)
            with rec.env.cr.savepoint():
                rec._post_note(
                    _("🔔 Approval needed from <b>%s</b>.") % line.approver_id.name,
                    partner_ids=[line.approver_id.partner_id.id],
                )

            # 3) Direct chat ping (popup + sound; NO email)
            with rec.env.cr.savepoint():
                html = _(
                    "🔔 <b>Approval needed</b> for: "
                    "<a href='%(link)s'>%(name)s</a><br/>Requester: %(req)s"
                ) % {"link": rec._deeplink(), "name": rec.name, "req": rec.requester_id.name}
                rec._dm_ping(line.approver_id.partner_id, html)

    # -------------------------------------------------------------------------
    # Steps generation
    # -------------------------------------------------------------------------
    def _build_approval_lines(self):
        """
        (Re)generate approval steps based on the chosen rule (single rule).
        Uses sudo() to remove previous steps even if the end-user lacks unlink rights.
        """
        for rec in self:
            # Clear any existing generated steps
            rec.approval_line_ids.sudo().unlink()

            if not rec.rule_id:
                raise UserError(_("Please choose an Approval Rule first."))

            rule = rec.rule_id

            # Company/department guardrails
            if rule.company_id and rule.company_id != rec.company_id:
                raise UserError(_("Rule belongs to another company."))
            if rule.department_id and rec.department_id and rule.department_id != rec.department_id:
                raise UserError(_("Rule belongs to another department."))

            # Amount threshold on rule (optional)
            if rule.min_amount and rec.amount and rec.amount < rule.min_amount:
                raise UserError(_("Amount is below this rule's minimum."))

            vals = []
            for step in rule.step_ids.sorted(key=lambda s: (s.sequence, s.id)):
                if not step.approver_id:
                    continue
                vals.append({
                    "request_id": rec.id,
                    "name": step.name or step.approver_id.name,
                    "approver_id": step.approver_id.id,
                    "required": True,
                    "state": "pending",
                    "company_id": rec.company_id.id,
                })

            if not vals:
                raise UserError(_("This rule has no approvers defined."))

            self.env["kh.approval.line"].create(vals)

    # -------------------------------------------------------------------------
    # Actions (buttons) — NO EMAIL paths
    # -------------------------------------------------------------------------
    def action_submit(self):
        """Requester submits: build steps, move to in_review, notify first approver."""
        for rec in self:
            if rec.state != "draft":
                continue
            rec._build_approval_lines()
            with rec.env.cr.savepoint():
                rec._ensure_followers()
            # 🔇 Avoid email from tracking on state change
            rec.with_context(tracking_disable=True).write({"state": "in_review"})
            rec._post_note(_("Request submitted for approval."))
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

            rec._close_my_open_todos()

            # Approve my step
            line.write({"state": "approved"})
            rec._post_note(
                _("Approved by <b>%s</b>.") % self.env.user.name,
                partner_ids=[rec.requester_id.partner_id.id],
            )

            # Next approver or finished
            next_line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if next_line:
                rec._notify_first_pending()
            else:
                # 🔇 Avoid email from tracking on state change
                rec.with_context(tracking_disable=True).write({"state": "approved"})
                rec._post_note(
                    _("✅ Request approved."),
                    partner_ids=[rec.requester_id.partner_id.id],
                )
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

            # 🔇 Avoid email from tracking on state change
            rec.with_context(tracking_disable=True).write({"state": "rejected"})

            rec._post_note(
                _("❌ Rejected by <b>%s</b>.") % self.env.user.name,
                partner_ids=[rec.requester_id.partner_id.id],
            )
            rec._dm_ping(
                rec.requester_id.partner_id,
                _("❌ <b>Rejected</b>: <a href='%s'>%s</a>") % (rec._deeplink(), rec.name),
            )
        return True


# ============================================================================
# Approval Rule (+ Step sequence)
# ============================================================================
class KhApprovalRule(models.Model):
    _name = "kh.approval.rule"
    _description = "Approval Rule"
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    company_id = fields.Many2one("res.company", string="Company")
    department_id = fields.Many2one("kh.approvals.department", string="Department")

    min_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
        required=True,
    )

    # Ordered approver sequence
    step_ids = fields.One2many(
        "kh.approval.rule.step", "rule_id", string="Steps", copy=True
    )


# ============================================================================
# Approval Line (generated)
# ============================================================================
class KhApprovalLine(models.Model):
    _name = "kh.approval.line"
    _description = "Approval Step"
    _order = "id"
    _check_company_auto = True

    request_id = fields.Many2one("kh.approval.request", required=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company", related="request_id.company_id", store=True, index=True
    )
    name = fields.Char()
    approver_id = fields.Many2one("res.users", required=True)
    required = fields.Boolean(default=True)
    state = fields.Selection(
        [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending",
        required=True,
    )
    note = fields.Char()
