# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)


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
    name = fields.Char(string="Request ID", required=True, tracking=True, default=_("New"), copy=False)
    title = fields.Char(
        string="Title",
        required=True,
        tracking=True,
        states={'in_review': [('readonly', True)], 'approved': [('readonly', True)], 'rejected': [('readonly', True)]}
    )
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
        domain="[('company_id', '=', company_id)]"
    )

    requester_id = fields.Many2one(
        "res.users",
        string="Requester",
        default=lambda self: self.env.user.id,
        tracking=True,
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        related="requester_id.employee_id",
        store=True,
        readonly=True,
    )

    amount = fields.Monetary(string="Amount", currency_field="currency_id", tracking=True)

    payslip_ids = fields.Many2many(
        "hr.payslip",
        string="Payslips",
        readonly=True,
    )

    approval_type = fields.Selection(
        [
            ("standard", "Standard"),
            ("payslip", "Payslip"),
        ],
        string="Approval Type",
        default="standard",
        required=True,
    )

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

    payment_state = fields.Selection(
        [
            ("not_paid", "Not Paid"),
            ("paid", "Paid"),
        ],
        string="Payment Status",
        default="not_paid",
        tracking=True,
        copy=False,
    )

    # Revision / audit helpers
    revision = fields.Integer(default=0, tracking=True)
    last_revised_by = fields.Many2one('res.users', readonly=True)
    last_revised_on = fields.Datetime(readonly=True)
    submitted_on = fields.Datetime(string="Submitted On", readonly=True, tracking=True)

    # Single rule selector (rule defines company/department/approver sequence)
    rule_id = fields.Many2one(
        "kh.approval.rule",
        string="Approval Rule",
        domain="[ ('department_id','=',department_id)]",
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
        for rec in self:
            lines = rec.sudo().approval_line_ids.sorted('id')
            if lines:
                rec.steps_overview_html = self.env['ir.qweb']._render(
                    'kh_approvals.steps_overview_template',
                    {'lines': lines}
                )
            else:
                rec.steps_overview_html = "<i>No approval steps.</i>"
    def _critical_fields(self):
        """Fields that, if changed, should trigger a new approval cycle."""
        return {'title', 'amount', 'currency_id', 'company_id', 'department_id', 'rule_id'}

    # -------------------------------------------------------------------------
    # ORM overrides
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Assign company, department (from rule if empty), and company-scoped name/sequence."""
        for vals in vals_list:
            vals.setdefault("company_id", self.env.company.id)
 
            # If name is default "New", assign a sequence number
            if vals.get("name", _("New")) == _("New"):
                seq = self.env["ir.sequence"].with_context(
                    force_company=vals["company_id"]
                ).next_by_code("kh.approval.request")
                vals["name"] = seq or _("New")
            # auto-pick department from chosen rule if left empty
            if vals.get("rule_id") and not vals.get("department_id"):
                rule = self.env["kh.approval.rule"].browse(vals["rule_id"])
                vals["department_id"] = rule.department_id.id
        return super().create(vals_list)

    def unlink(self):
        """
        Only requester can delete; allowed when state in ('draft','rejected').
        This keeps audit intact for processed requests.
        """
        for rec in self:
            if rec.requester_id.id != self.env.uid:
                raise AccessError(_("Only the requester can delete this request."))
            if rec.state not in ("draft", "rejected"):
                raise UserError(_("You can delete only Draft or Rejected requests."))
        return super().unlink()

    def write(self, vals):
        """
        Block edits to critical fields once submitted, unless in Draft or we’re doing a controlled transition.
        """
        critical = self._critical_fields()
        if critical.intersection(vals.keys()):
            for rec in self:
                if rec.state != 'draft':
                    if not self.env.context.get('kh_allow_write_outside_draft'):
                        raise UserError(_("You cannot edit request details after submission. "
                                          "Use 'Edit Request' to return to Draft, edit, and re-submit."))
        return super().write(vals)

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
                subject=f"{self.name}: {self.title}",
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
            subject=subject or f"{self.name}: {self.title}",
            subtype_xmlid="mail.mt_comment",
            email_layout_xmlid="mail.mail_notification_light",  # no SMTP
        )

    def _ensure_followers(self):
        """Subscribe requester + all approvers so they see inbox notifications, silently."""
        for rec in self:
            partners = rec.requester_id.partner_id | rec.approval_line_ids.mapped("approver_id.partner_id")
            if partners:
                with rec.env.cr.savepoint():
                    rec.with_context(mail_post_autofollow=False).message_subscribe(
                        partner_ids=partners.ids,
                        subtype_ids=[],  # silent
                    )

    def _activity_done_silent(self, activity):
        """Mark a single activity as done with a quiet note."""
        self.ensure_one()
        self.with_context(mail_activity_quick_update=True)._post_note(
            body_html=f"<div>{activity.activity_type_id.name}: Done</div>",
            partner_ids=self.message_follower_ids.mapped("partner_id").ids,
        )
        activity.action_done()

    def _close_my_open_todos(self):
        """Mark my open To-Do activities on this request as done for the current user."""
        for rec in self:
            acts = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)
            if acts:
                rec._activity_done_silent(acts)

    def _close_all_todos(self):
        """Close all To-Do activities on this request (any user)."""
        for rec in self:
            # When a request is revised, we cancel (unlink) all open approval activities.
            # The activities were created by the requester, who is the one revising,
            # so they have the permission to unlink them.
            rec.activity_ids.unlink()

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

    def _notify_pending_approvers(self):
        """
        Ensure ONE To-Do for each current pending approver.
        """
        todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        
        for rec in self:
            pending_lines = rec.approval_line_ids.filtered(lambda l: l.state == "pending")
            for line in pending_lines:
                if not line.approver_id:
                    continue

                # Throttle
                if rec._recently_notified(line.approver_id.partner_id, minutes=10):
                    continue

                # Ensure exactly one open To-Do
                existing = rec.activity_ids.filtered(
                    lambda a: a.user_id.id == line.approver_id.id and \
                              (not todo_type or a.activity_type_id.id == todo_type.id)
                )
                if not existing:
                    # Schedule the todo as sudo() and with the request company so the activity is created even if the approver's current company differs.
                    with rec.env.cr.savepoint():
                        rec.sudo().with_company(rec.company_id.id).activity_schedule(
                            "mail.mail_activity_data_todo",
                            user_id=line.approver_id.id,
                            summary=_("Approval needed: %s") % rec.title,
                            note=_("Please review approval request %s: %s") % (rec.name or rec.title, rec.title),
                        )
    # -------------------------------------------------------------------------
    # Steps generation
    # -------------------------------------------------------------------------
    def _build_approval_lines(self):
        """
        (Re)generate approval steps based on the chosen rule (single rule) or
        approval type.
        Uses sudo() so normal users (read-only on lines) can submit.
        """
        for rec in self:
            # Clear any existing generated steps
            rec.approval_line_ids.sudo().unlink()
            vals_list = []

            if rec.approval_type == 'standard':
                if not rec.rule_id:
                    raise UserError(_("Please choose an Approval Rule first."))

                rule = rec.rule_id

                # Company/department guardrails
                if rule.company_id and rule.company_id != rec.company_id:
                    raise UserError(_("Rule belongs to another company."))
                if rule.department_id and rec.department_id and rule.department_id != rec.department_id:
                    raise UserError(_("Rule belongs to another department."))

                # Amount threshold on rule (optional)
                if rule.min_amount and rec.amount and rec.amount < rec.min_amount:
                    raise UserError(_("Amount is below this rule's minimum."))

                steps = rule.step_ids.sorted(key=lambda s: (s.sequence, s.id))
                for step in steps:
                    if not step.approver_id:
                        continue
                    vals_list.append({
                        "request_id": rec.id,
                        "name": step.name or step.approver_id.name,
                        "approver_id": step.approver_id.id,
                        "required": True,
                        "state": "waiting",
                        "company_id": rec.company_id.id,
                        "sequence": step.sequence,
                    })

            elif rec.approval_type == 'payslip':
                # TODO: Make payslip approvers configurable
                # For now, we use a hardcoded list of approvers.
                approvers = self.env['res.users'].browse([2]) # Administrator
                for approver in approvers:
                    vals_list.append({
                        "request_id": rec.id,
                        "name": f"Approval by {approver.name}",
                        "approver_id": approver.id,
                        "required": True,
                        "state": "waiting",
                        "company_id": rec.company_id.id,
                        "sequence": 10,
                    })

            if not vals_list:
                raise UserError(_("No approvers found for this request."))

            if vals_list:
                min_sequence = min(v['sequence'] for v in vals_list)
                for v in vals_list:
                    if v['sequence'] == min_sequence:
                        v['state'] = 'pending'

            self.env["kh.approval.line"].sudo().create(vals_list)
    # -------------------------------------------------------------------------
    # Actions (buttons)
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
            rec.with_context(tracking_disable=True).write({
                "state": "in_review",
                "submitted_on": fields.Datetime.now(),
            })
            rec._post_note(
                _("Request submitted for approval."),
                partner_ids=[rec.requester_id.partner_id.id],  # Ping requester only
            )
            rec._notify_pending_approvers()
        return True

    def action_revise_request(self):
        """
        Requester turns a non-draft request back to Draft to edit safely.
        - Allowed for owner only
        - Closes activities
        - Clears approval lines
        - Increments revision
        - Notifies followers & previous approvers
        """
        for rec in self:
            if rec.requester_id.id != self.env.uid:
                raise AccessError(_("Only the requester can revise this request."))
            if rec.state not in ('in_review', 'approved', 'rejected'):
                raise UserError(_("Only non-Draft requests can be revised."))

            prev_approver_partners = rec.approval_line_ids.mapped('approver_id.partner_id')

            rec._close_all_todos()
            rec.approval_line_ids.sudo().unlink()

            rec.with_context(tracking_disable=True).write({
                'state': 'draft',
                'revision': rec.revision + 1,
                'last_revised_by': self.env.user.id,
                'last_revised_on': fields.Datetime.now(),
                'submitted_on': False, # Clear submission date on revise
            })

            rec._post_note(
                _("✏️ Request revised by <b>%s</b>. All approvals have been reset.<br/>"
                  "Revision: <b>%s</b>") % (self.env.user.name, rec.revision),
                partner_ids=rec.message_follower_ids.mapped("partner_id").ids,
            )
            if prev_approver_partners:
                rec._post_note(
                    _("Revised and approvals reset."),
                    partner_ids=prev_approver_partners.ids,
                )
        return True
    def action_withdraw_request(self):
        # Feature disabled at your request
        raise UserError(_("This option has been disabled by your administrator."))
    def action_approve_request(self):
        """Current approver approves their step; finish or notify next approver."""
        for rec in self:
            if rec.state != "in_review":
                continue

            line = self.env["kh.approval.line"].sudo().search(
                [
                    ("request_id", "=", rec.id),
                    ("state", "=", "pending"),
                    ("approver_id", "=", self.env.uid),
                ],
                order="sequence, id",
                limit=1,
            )
            if not line:
                raise UserError(_("You are not a current approver for this request, or you have already approved."))

            activity_to_close = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)[:1]
            if activity_to_close:
                activity_to_close.with_user(rec.requester_id).unlink()

            line.sudo().write({"state": "approved"})
            
            # Invalidate the cache to ensure the next check gets the fresh data
            rec._invalidate_cache(['approval_line_ids'])

            rec._post_note(
                _("Approved by <b>%s</b>.") % self.env.user.name,
                partner_ids=[rec.requester_id.partner_id.id],
            )

            # Check if all lines at the current sequence level are approved.
            current_sequence = line.sequence
            other_pending_lines_at_level = self.env['kh.approval.line'].sudo().search_count([
                ('request_id', '=', rec.id),
                ('sequence', '=', current_sequence),
                ('required', '=', True),
                ('state', '!=', 'approved'),
            ])

            if other_pending_lines_at_level == 0:
                # This level is complete. Find the next level.
                next_level_lines = self.env['kh.approval.line'].sudo().search([
                    ('request_id', '=', rec.id),
                    ('sequence', '>', current_sequence),
                ], order='sequence', limit=1)

                if next_level_lines:
                    # There is a next level. Set all lines at that level to 'pending'.
                    next_sequence = next_level_lines.sequence
                    lines_to_make_pending = self.env['kh.approval.line'].sudo().search([
                        ('request_id', '=', rec.id),
                        ('sequence', '=', next_sequence),
                    ])
                    lines_to_make_pending.sudo().write({'state': 'pending'})
                    rec._notify_pending_approvers()
                else:
                    # This was the last level. Do a final check to be sure.
                    all_required_lines = self.env['kh.approval.line'].sudo().search([
                        ('request_id', '=', rec.id),
                        ('required', '=', True)
                    ])
                    
                    _logger.debug(f"Final verification for request {rec.name} (ID: {rec.id}). "
                                  f"Required lines found: {len(all_required_lines)}. "
                                  f"States: {[f'{line.name} (ID: {line.id}, State: {line.state})' for line in all_required_lines]}")

                    if all(line.state == 'approved' for line in all_required_lines):
                        # All required lines are approved. The request is fully approved.
                        old_state = rec.state
                        rec.sudo().write({"state": "approved"})
                        rec.message_post(
                            body=_("Request approved."),
                            tracking_value_ids=[(0, 0, {
                                'field_id': self.env['ir.model.fields']._get(self._name, 'state').id,
                                'old_value_char': dict(self._fields['state'].selection).get(old_state),
                                'new_value_char': dict(self._fields['state'].selection).get('approved'),
                            })],
                            message_type="notification",
                            subtype_xmlid="mail.mt_comment",
                            partner_ids=[rec.requester_id.partner_id.id]
                        )

                        rec._notify_partner(
                            rec.requester_id.partner_id,
                            _("✅ <b>Approved</b>: <a href='%(link)s'>%(name)s: %(title)s</a>") % {"link": rec._deeplink(), "name": rec.name, "title": rec.title},
                            subject=f"Approved: {rec.name}",
                        )

                        if rec.approval_type == "payslip":
                            rec.payslip_ids.write({"approval_state": "approved"})
                        
                        if rec.amount > 0:
                            user_to_notify_and_follow = self.env['res.users'].browse(363)
                            if user_to_notify_and_follow.exists():
                                rec.with_user(rec.requester_id.id).with_company(rec.company_id).message_subscribe(
                                    partner_ids=[user_to_notify_and_follow.partner_id.id]
                                )
                                rec.with_user(rec.requester_id.id).with_company(rec.company_id).activity_schedule(
                                    'mail.mail_activity_data_todo',
                                    user_id=user_to_notify_and_follow.id,
                                    summary=_("Request Approved: %s") % rec.title,
                                    note=_("Your request %s has been approved. Please mark as paid.") % (rec.name),
                                )
                    else:
                        # Failsafe: The sequential logic determined this was the last step,
                        # but not all required lines are approved. This indicates a potential
                        # issue with the approval rule setup (e.g., sequence gaps) or a bug.
                        _logger.warning(
                            "Request %s reached final approval step prematurely. "
                            "Not all required lines are approved. Aborting approval.",
                            rec.name
                        )
                        rec._post_note(
                            _("Approval process stalled due to a configuration issue. "
                              "Please contact an administrator. (Error: Final validation failed)")
                        )
        return True

    def action_reject_request(self):
        """Current approver rejects; request becomes Rejected and requester is pinged."""
        for rec in self:
            if rec.state != "in_review":
                continue

            line = self.env["kh.approval.line"].sudo().search(
                [
                    ("request_id", "=", rec.id),
                    ("state", "=", "pending"),
                    ("approver_id", "=", self.env.uid),
                ],
                limit=1,
            )
            if not line:
                raise UserError(_("You are not the current approver."))

            rec._close_my_open_todos()
            line.sudo().write({"state": "rejected"})

            # Log state change in chatter
            old_state = rec.state
            rec.sudo().write({"state": "rejected"})
            rec.message_post(
                body=_("❌ Rejected by <b>%s</b>.") % self.env.user.name,
                tracking_value_ids=[(0, 0, {
                    'field_id': self.env['ir.model.fields']._get(self._name, 'state').id,
                    'old_value_char': dict(self._fields['state'].selection).get(old_state),
                    'new_value_char': dict(self._fields['state'].selection).get('rejected'),
                })],
                message_type="notification",
                subtype_xmlid="mail.mt_comment",
                partner_ids=[rec.requester_id.partner_id.id]
            )

            rec._notify_partner(
                rec.requester_id.partner_id,
                _("❌ <b>Rejected</b>: <a href='%(link)s'>%(name)s: %(title)s</a>") % {"link": rec._deeplink(), "name": rec.name, "title": rec.title},
                subject=f"Rejected: {rec.name}",
            )
            if rec.approval_type == "payslip":
                rec.payslip_ids.write({"approval_state": "rejected"})
        return True

    def action_opt_out_as_approver(self):
        # Feature disabled at your request
        raise UserError(_("This option has been disabled by your administrator."))

    def action_mark_as_paid(self):
        """Marks the request as paid and closes the associated activity."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Only approved requests can be marked as paid."))
            if rec.payment_state == 'paid':
                raise UserError(_("This request has already been marked as paid."))
            if not rec.amount > 0:
                raise UserError(_("This action is only for requests with a payment amount."))

            # Close the open "To-Do" activity for the current user (the accountant).
            rec._close_my_open_todos()

            rec.write({'payment_state': 'paid'})

            # Post a note in the chatter
            rec._post_note(
                _("Request marked as <b>Paid</b> by %s.") % self.env.user.name,
                partner_ids=rec.message_follower_ids.mapped("partner_id").ids,
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
    _order = "sequence, id"
    _check_company_auto = True

    request_id = fields.Many2one("kh.approval.request", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10, help="Lower is earlier.")
    company_id = fields.Many2one(
        "res.company", related="request_id.company_id", store=True, index=True
    )
    name = fields.Char()
    approver_id = fields.Many2one("res.users", required=True)
    required = fields.Boolean(default=True)
    state = fields.Selection(
        [
            ("waiting", "Waiting"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("withdrawn", "Withdrawn"),  # (not used now, but kept for history)
        ],
        default="waiting",
        required=True,
    )
    note = fields.Char()