# -*- coding: utf-8 -*-
# Khales Approval Request — single Chrome ping per step + throttle
#
# Key changes:
# - _ensure_followers(): silent subscription (no noisy subtypes)
# - _recently_notified(): throttle helper (default 10 minutes)
# - _notify_first_pending(): relies on ONE source of notification:
#       * default = Activity only (Desktop/Inbox ping via activity)
#       * optional chatter ping if System Parameter kh.approval.notify_mode = 'message'
#   Also throttled to avoid duplicate pings if called twice.
#
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
        tracking=True,  # tracking kept, but we mute it on write
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

    # Always-visible, read-only HTML snapshot of all steps (built with sudo)
    steps_overview_html = fields.Html(
        string="Approval Steps (All Approvers)",
        compute="_compute_steps_overview_html",
        store=False,
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

    # HTML snapshot builder (uses sudo so approvers always see the full sequence)
    def _compute_steps_overview_html(self):
        status_badge = {
            "pending":  "#d97706",   # amber
            "approved": "#059669",   # green
            "rejected": "#dc2626",   # red
        }
        for rec in self:
            rows = []
            for line in rec.sudo().approval_line_ids.sorted(key=lambda l: (l.id,)):
                color = status_badge.get(line.state or "pending", "#6b7280")
                rows.append(
                    f"""
                    <tr>
                      <td style="padding:6px 8px;border-bottom:1px solid #eee;">{(line.name or '')}</td>
                      <td style="padding:6px 8px;border-bottom:1px solid #eee;">{(line.approver_id.name or '')}</td>
                      <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:center;">
                        {'✓' if line.required else ''}
                      </td>
                      <td style="padding:6px 8px;border-bottom:1px solid #eee;">
                        <span style="display:inline-block;padding:2px 8px;border-radius:12px;background:{color}20;color:{color};font-weight:600;text-transform:capitalize;">
                          {line.state or 'pending'}
                        </span>
                      </td>
                      <td style="padding:6px 8px;border-bottom:1px solid #eee;">{(line.note or '')}</td>
                    </tr>
                    """
                )

            if rows:
                rec.steps_overview_html = f"""
                <div style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden">
                  <table style="width:100%;border-collapse:collapse;font-size:13px;">
                    <thead style="background:#f9fafb;">
                      <tr>
                        <th style="text-align:left;padding:8px 10px;">Name</th>
                        <th style="text-align:left;padding:8px 10px;">Approver</th>
                        <th style="text-align:center;padding:8px 10px;">Required</th>
                        <th style="text-align:left;padding:8px 10px;">State</th>
                        <th style="text-align:left;padding:8px 10px;">Note</th>
                      </tr>
                    </thead>
                    <tbody>{''.join(rows)}</tbody>
                  </table>
                </div>
                """
            else:
                rec.steps_overview_html = "<i>No approval steps.</i>"

    # -------------------------------------------------------------------------
    # ORM overrides
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Assign company, department (from rule if empty), and company-scoped name/sequence."""
        for vals in vals_list:
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
    # Helpers - Chatter & notifications (NO EMAIL)
    # -------------------------------------------------------------------------
    def _post_note(self, body_html, partner_ids=None):
        """
        Post an INTERNAL NOTE only (no email, no auto-subscribe).
        Appears in chatter & Discuss/Inbox; safe on servers without SMTP.
        """
        if partner_ids:
            self.message_notify(
                partner_ids=partner_ids,
                body=body_html,
                subject=self.name,
                subtype_xmlid="mail.mt_note",
                email_layout_xmlid="mail.mail_notification_light",
            )
        else:
            self.with_context(
                mail_notify_force_send=False,
                mail_post_autofollow=False,
                mail_create_nosubscribe=True,
            ).message_post(
                body=body_html,
                message_type="comment",
                subtype_xmlid="mail.mt_note",
            )

    def _notify_partner(self, partner, body_html, subject=None):
        """Send an Inbox notification FROM this document (not a user DM)."""
        self.ensure_one()
        self.message_notify(
            partner_ids=[partner.id],
            body=body_html,
            subject=subject or self.name,
            subtype_xmlid="mail.mt_comment",
            email_layout_xmlid="mail.mail_notification_light",  # no SMTP
        )

    def _ensure_followers(self):
        """Subscribe requester + all approvers so they see inbox notifications, silently."""
        for rec in self:
            partners = rec.requester_id.partner_id | rec.approval_line_ids.mapped("approver_id.partner_id")
            if partners:
                with rec.env.cr.savepoint():
                    # Silent subscription: avoid auto-follow subtypes to prevent extra chatter
                    rec.with_context(mail_post_autofollow=False).message_subscribe(
                        partner_ids=partners.ids,
                        subtype_ids=[],  # no default subtypes => quieter
                    )

    def _activity_done_silent(self, activity):
        """
        Mark an activity as done and post feedback silently (NO EMAIL).
        This bypasses the standard action_feedback which can trigger emails.
        """
        self.ensure_one()
        self.with_context(mail_activity_quick_update=True)._post_note(
            body_html=f"<div>{activity.activity_type_id.name}: Done</div>",
            partner_ids=self.message_follower_ids.mapped("partner_id").ids,
        )
        activity.with_context(kh_from_mark_done=True).unlink()

    def _close_my_open_todos(self):
        """Mark my open To-Do activities on this request as done for the current user."""
        for rec in self:
            acts = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)
            if acts:
                rec._activity_done_silent(acts)

    # -------------------------------------------------------------------------
    # Throttle helper
    # -------------------------------------------------------------------------
    def _recently_notified(self, partner, minutes=10):
        """Return True if we already sent this partner a 'needs approval' ping recently."""
        self.ensure_one()
        Message = self.env['mail.message'].sudo()
        now = fields.Datetime.now()
        cutoff = fields.Datetime.subtract(now, minutes=minutes)
        domain = [
            ('model', '=', self._name),
            ('res_id', '=', self.id),
            ('message_type', '=', 'comment'),
            ('partner_ids', 'in', [partner.id]),
            ('body', 'ilike', 'Approval needed'),
            ('date', '>=', cutoff),
        ]
        return bool(Message.search_count(domain))

    def _notify_first_pending(self):
        """
        Ensure ONE To-Do for the current pending approver.
        Default behavior: rely on the Activity as the single Chrome/In-Box notification.
        Optional chatter ping if System Parameter kh.approval.notify_mode = 'message'.
        Throttled to avoid duplicates if method runs twice.
        """
        todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        icp = self.env['ir.config_parameter'].sudo()
        notify_mode = icp.get_param('kh.approval.notify_mode', 'activity')  # 'activity' | 'message'

        for rec in self:
            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or not line.approver_id:
                continue

            # 0) Throttle: if we pinged this approver for this request very recently, skip
            if rec._recently_notified(line.approver_id.partner_id, minutes=10):
                continue

            # 1) Ensure exactly one open To-Do assigned to the approver on this request
            existing = rec.activity_ids
            if todo_type:
                existing = existing.filtered(
                    lambda a: a.user_id.id == line.approver_id.id and a.activity_type_id.id == todo_type.id
                )
            else:
                existing = existing.filtered(lambda a: a.user_id.id == line.approver_id.id)

            if not existing[:1]:
                with rec.env.cr.savepoint():
                    rec.activity_schedule(
                        "mail.mail_activity_data_todo",
                        user_id=line.approver_id.id,
                        summary=_("Approval needed"),
                        note=_("Please review approval request: %s") % rec.name,
                    )

            # 2) Optional chatter ping (OFF by default). If enabled, still one ping & throttled.
            if notify_mode == 'message':
                html = _(
                    "🔔 <b>Approval needed</b> for: <a href='%(link)s'>%(name)s</a><br/>Requester: %(req)s"
                ) % {"link": rec._deeplink(), "name": rec.name, "req": rec.requester_id.name}
                with rec.env.cr.savepoint():
                    rec.message_notify(
                        partner_ids=[line.approver_id.partner_id.id],
                        body=html,
                        subject=rec.name,
                        subtype_xmlid="mail.mt_comment",
                        email_layout_xmlid="mail.mail_notification_light",
                    )

    # -------------------------------------------------------------------------
    # Steps generation
    # -------------------------------------------------------------------------
    def _build_approval_lines(self):
        """
        (Re)generate approval steps based on the chosen rule (single rule).
        Uses sudo() so normal users (read-only on lines) can submit.
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

            self.env["kh.approval.line"].sudo().create(vals)

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
            rec._post_note(
                _("Request submitted for approval."),
                partner_ids=[rec.requester_id.partner_id.id],  # Ping requester only
            )
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

            # Approve my step (sudo -> users are read-only on lines)
            line.sudo().write({"state": "approved"})

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
                rec._notify_partner(
                    rec.requester_id.partner_id,
                    _("✅ <b>Approved</b>: <a href='%s'>%s</a>") % (rec._deeplink(), rec.name),
                    subject=rec.name,
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
            line.sudo().write({"state": "rejected"})

            # 🔇 Avoid email from tracking on state change
            rec.with_context(tracking_disable=True).write({"state": "rejected"})

            rec._post_note(
                _("❌ Rejected by <b>%s</b>.") % self.env.user.name,
                partner_ids=[rec.requester_id.partner_id.id],
            )
            rec._notify_partner(
                rec.requester_id.partner_id,
                _("❌ <b>Rejected</b>: <a href='%s'>%s</a>") % (rec._deeplink(), rec.name),
                subject=rec.name,
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
