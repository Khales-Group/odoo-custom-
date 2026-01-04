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
    # --- Relations to external documents (added for compatibility after migration) ---
    project_id = fields.Many2one('project.project', string='Project', ondelete='cascade', index=True)
    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', ondelete='cascade', index=True)
    crm_lead_id = fields.Many2one('crm.lead', string='Related Lead', ondelete='cascade', index=True)

    name = fields.Char(string="Request ID", required=True, tracking=True, default=lambda self: _("New"), copy=False)
    title = fields.Char(
        string="Title",
        required=True,
        tracking=True,
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

    rule_id = fields.Many2one(
        "kh.approval.rule",
        string="Approval Rule",
        domain="[ ('department_id','=',department_id)]",
        tracking=True,
    )

    # --- Two-Cycle Approval Support ---
    payment_rule_id = fields.Many2one(
        "kh.approval.rule",
        string="Payment Approval Rule",
        domain="[('company_id', '=', company_id)]",
        tracking=True,
        help="Rule used for the second cycle (Payment Approval)."
    )
    approval_stage = fields.Selection(
        [('procurement', 'Procurement Cycle'), ('pay_review', 'Payment Cycle'), ('done', 'Fully Approved')],
        default='procurement',
        string="Current Stage",
        required=True,
        tracking=True
    )

    # UI helper: show Petty Cash items tab when the chosen rule is 'Petty Cash'
    is_petty_cash = fields.Boolean(compute='_compute_is_petty_cash', store=False)

    # Concrete steps generated from the rule's step_ids
    approval_line_ids = fields.One2many(
        "kh.approval.line", "request_id", string="Approval Steps", copy=False
    )

    petty_cash_line_ids = fields.One2many(
        "kh.approval.petty.cash.line", "request_id", string="Petty Cash Items", copy=True
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
    @api.depends('rule_id.name')
    def _compute_is_petty_cash(self):
        for rec in self:
            rec.is_petty_cash = rec.rule_id.name == 'Petty Cash'

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
        """Mark a single activity as done with a quiet note.

        This implementation is company-agnostic and tolerant of missing permissions.
        It posts a quiet note then attempts to mark the activity done using sudo()
        and the special context key expected by the mail_activity guard.
        """
        self.ensure_one()
        try:
            # Post a quiet note (no email, no auto-follow)
            self.with_context(mail_activity_quick_update=True)._post_note(
                body_html=f"&lt;div&gt;{getattr(activity.activity_type_id, 'name', 'To-Do')}: Done&lt;/div&gt;",
                partner_ids=self.message_follower_ids.mapped('partner_id').ids,
            )
        except Exception as e:
            _logger.debug("Failed to post activity done note: %s", e)
        try:
            # Use sudo and the activity_mark_as_done context so custom guards allow the action/unlink.
            activity.with_context(activity_mark_as_done=True).sudo().action_done()
        except Exception as e:
            # As fallback, attempt unlink (also under sudo & guard context),
            # but swallow errors — we cannot let activity errors break approval flow.
            try:
                activity.with_context(activity_mark_as_done=True).sudo().unlink()
            except Exception as e2:
                _logger.warning("Failed to mark/unlink activity (id=%s): %s", getattr(activity, 'id', False), e2)

    def _close_my_open_todos(self):
        """Mark my open To-Do activities on this request as done for the current user.

        Safe: iterates per-activity and uses sudo/context to avoid company/permission failures.
        """
        for rec in self:
            acts = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)
            if not acts:
                continue
            for act in acts:
                try:
                    rec._activity_done_silent(act)
                except Exception as e:
                    _logger.warning("Failed to close activity (id=%s) for user %s: %s",
                                    getattr(act, 'id', False), self.env.uid, e)

    def _close_all_todos(self):
        """Close all To-Do activities on this request (any user).

        We avoid bulk searches/unlinks that trigger company guards. Instead iterate each activity
        and either mark it done or unlink it under sudo with the activity_mark_as_done context.
        This is safe across companies and users.
        """
        for rec in self:
            activities = rec.activity_ids
            if not activities:
                continue
            for act in activities:
                try:
                    # Prefer marking done (keeps history) and use sudo + guard context.
                    act.with_context(activity_mark_as_done=True).sudo().action_done()
                except Exception:
                    try:
                        # Fallback: attempt unlink under sudo with the guard context.
                        act.with_context(activity_mark_as_done=True).sudo().unlink()
                    except Exception as e:
                        _logger.warning("Failed to remove activity (id=%s) during close_all: %s",
                                        getattr(act, 'id', False), e)

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
        Uses sudo to create activities across companies.
        """
        todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)

        for rec in self:
            # Use sudo() to read pending lines, bypassing record rules for visibility.
            pending_lines = rec.sudo().approval_line_ids.filtered(lambda l: l.state == "pending")

            for line in pending_lines:
                approver = line.approver_id
                if not approver:
                    continue

                # Throttle to avoid spamming notifications
                if rec._recently_notified(approver.partner_id, minutes=10):
                    continue

                # Check for an existing open To-Do for this approver on this request
                existing_activity = rec.sudo().activity_ids.filtered(
                    lambda a: a.user_id.id == approver.id and \
                              (not todo_type or a.activity_type_id.id == todo_type.id)
                )
                if existing_activity:
                    continue

                # Create the activity in the approver's company context if possible,
                # falling back to the request's company. This ensures visibility.
                company_id = approver.company_id.id or rec.company_id.id

                try:
                    with rec.env.cr.savepoint():
                        # Use sudo() to create the activity, as the current user (e.g., scheduler)
                        # may not have permission to create activities for other users.
                        rec.sudo().with_company(company_id).activity_schedule(
                            "mail.mail_activity_data_todo",
                            user_id=approver.id,
                            summary=_("Approval needed: %s") % rec.title,
                            note=_("Please review approval request %s: %s") % (rec.name or rec.title, rec.title),
                        )
                except Exception as e:
                    _logger.error(
                        "Failed to create approval activity for user %s (ID: %s) on request %s (ID: %s): %s",
                        approver.name, approver.id, rec.name, rec.id, e
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
            current_stage = rec.approval_stage or 'procurement'

            # Clear ONLY the lines for the current stage (allow retrying/resetting current cycle)
            # We preserve lines from other stages (e.g. completed procurement lines)
            rec.approval_line_ids.filtered(lambda l: l.approval_stage == current_stage).sudo().unlink()
            
            vals_list = []

            if rec.approval_type == 'standard':
                # Select rule based on current stage
                rule = False
                if current_stage == 'procurement':
                    rule = rec.rule_id
                elif current_stage == 'pay_review':
                    rule = rec.payment_rule_id
                
                if not rule:
                    raise UserError(_("Please select an Approval Rule for the '%s' stage.") % current_stage)
                
                # Company/department guardrails
                if rule.company_id and rule.company_id != rec.company_id:
                    raise UserError(_("Rule belongs to another company."))
                if rule.department_id and rec.department_id and rule.department_id != rec.department_id:
                    raise UserError(_("Rule belongs to another department."))

                # Amount threshold on rule (optional)
                if rule.min_amount and rec.amount and rec.amount < rule.min_amount:
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
                        "approval_stage": current_stage,
                    })

            elif rec.approval_type == 'payslip':
                rule = False
                if rec.department_id:
                    rule = self.env['kh.approval.rule'].search([
                        ('company_id', '=', rec.company_id.id),
                        ('department_id', '=', rec.department_id.id),
                    ], limit=1)

                if not rule:
                    # Fallback to no department
                    rule = self.env['kh.approval.rule'].search([
                        ('company_id', '=', rec.company_id.id),
                        ('department_id', '=', False),
                    ], limit=1)

                if not rule:
                    raise UserError(_("No approval rule found for payslip approvals in this company. Please create a rule for the relevant department or a general rule with no department assigned."))

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
                        "approval_stage": current_stage,
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
            # Only clear lines for the active stage
            rec.approval_line_ids.filtered(lambda l: l.approval_stage == rec.approval_stage).sudo().unlink()

            rec.with_context(tracking_disable=True).write({
                'state': 'draft',
                'revision': rec.revision + 1,
                'last_revised_by': self.env.user.id,
                'last_revised_on': fields.Datetime.now(),
                'submitted_on': False,  # Clear submission date on revise
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
        """Approve the current pending line for the current user.

        Semi-sudo strategy:
        - Use sudo() for IO/activities and writes so company/ACL do not raise errors.
        - But enforce minimal validation: the acting user must be the approver for the pending line
          unless they are a manager or superuser — in those privileged cases, we allow fallback selection.
        - Add verbose logging so we can trace invalid approver situations.
        - Mark the acting user's activities as done (if any).
        """
        MailActivity = self.env['mail.activity'].sudo()
        Line = self.env['kh.approval.line'].sudo()
        Request = self.sudo()

        for rec in Request:
            if rec.state != "in_review":
                _logger.info("Skip approve: request %s (id=%s) not in 'in_review' (state=%s).", rec.name, rec.id, rec.state)
                continue

            action_user = self.env.uid

            # Try to find a pending line explicitly for the action user
            line = Line.search([
                ('request_id', '=', rec.id),
                ('state', '=', 'pending'),
                ('approver_id', '=', action_user),
            ], order='sequence, id', limit=1)

            if not line:
                # Log detailed debug info: existing pending approvers
                pending = Line.search([('request_id', '=', rec.id), ('state', '=', 'pending')])
                pending_approvers = [(l.id, l.approver_id.id if l.approver_id else None) for l in pending]
                _logger.warning(
                    "No pending line matched user %s for request %s (id=%s). Pending lines: %s",
                    action_user, rec.name, rec.id, pending_approvers
                )

                # Allow managers/su to pick the first pending line as fallback
                is_privileged = (self.env.is_superuser() or self.env.user.has_group('kh_approvals.group_kh_approvals_manager'))
                if is_privileged and pending:
                    line = pending.sorted('sequence, id')[0]
                    _logger.info("Privileged user %s will approve fallback line id=%s for request %s (id=%s).",
                                 action_user, line.id, rec.name, rec.id)
                else:
                    # Not privileged and no line matching: deny with helpful log & message
                    _logger.error(
                        "User %s is not a pending approver for request %s (id=%s) and is not privileged. Abort approve.",
                        action_user, rec.name, rec.id
                    )
                    raise UserError(_("You are not a current approver for this request, or you have already approved."))

            # From here, 'line' is the target approval line (as sudo record)
            try:
                _logger.info("User %s approving line id=%s (approver=%s) on request %s (id=%s).",
                             action_user, line.id, getattr(line, 'approver_id', False) and line.approver_id.id or None, rec.name, rec.id)

                # Mark any activities for the action_user as done (safe, uses sudo)
                try:
                    acts = MailActivity.search([('res_model', '=', rec._name), ('res_id', '=', rec.id), ('user_id', '=', action_user)])
                    if acts:
                        for a in acts:
                            try:
                                a.with_context(activity_mark_as_done=True).sudo().action_feedback(feedback=_("Approved"))
                            except Exception:
                                try:
                                    a.with_context(activity_mark_as_done=True).sudo().action_done()
                                except Exception as e:
                                    _logger.exception("Failed to mark activity id=%s done while approving request %s: %s", getattr(a,'id',False), rec.name, e)
                except Exception as e:
                    _logger.exception("Failed while trying to close activities for user %s on request %s: %s", action_user, rec.name, e)

                # Approve the line and persist (line is already a sudo record)
                line.write({'state': 'approved'})

                # Refresh cache on request
                rec._invalidate_cache(['approval_line_ids'])

                # Post a quiet sudo note (safe)
                try:
                    rec._post_note(_("Approved by <b>%s</b>.") % self.env.user.name, partner_ids=[rec.requester_id.partner_id.id])
                except Exception as e:
                    _logger.exception("Failed to post approval note for request %s: %s", rec.name, e)

                # Progress sequences or finalize approval
                current_sequence = line.sequence
                other_pending_count = Line.search_count([
                    ('request_id', '=', rec.id),
                    ('sequence', '=', current_sequence),
                    ('required', '=', True),
                    ('state', '!=', 'approved'),
                ])
                if other_pending_count == 0:
                    # Move to next sequence or finalize
                    next_level = Line.search([('request_id', '=', rec.id), ('sequence', '>', current_sequence)], order='sequence', limit=1)
                    if next_level:
                        next_seq = next_level.sequence
                        lines_to_pending = Line.search([('request_id', '=', rec.id), ('sequence', '=', next_seq)])
                        if lines_to_pending:
                            lines_to_pending.write({'state': 'pending'})
                            # notify next approvers
                            try:
                                rec._notify_pending_approvers()
                            except Exception as e:
                                _logger.exception("Failed to notify next approvers for request %s: %s", rec.name, e)
                    else:
                        # Finalize
                        all_required = Line.search([('request_id', '=', rec.id), ('required', '=', True)])
                        if all(line_rec.state == 'approved' for line_rec in all_required):
                            old_state = rec.state
                            try:
                                rec.write({'state': 'approved'})
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
                            except Exception as e:
                                _logger.exception("Failed to finalize approval state for request %s: %s", rec.name, e)

                            try:
                                rec._notify_partner(
                                    rec.requester_id.partner_id,
                                    _("✅ <b>Approved</b>: <a href='%(link)s'>%(name)s: %(title)s</a>") % {
                                        "link": rec._deeplink(), "name": rec.name, "title": rec.title
                                    },
                                    subject=f"Approved: {rec.name}",
                                )
                            except Exception as e:
                                _logger.exception("Failed to send approval partner notification for request %s: %s", rec.name, e)

                            # Post-approval actions
                            try:
                                if rec.approval_type == "payslip":
                                    rec.payslip_ids.sudo().write({"approval_state": "approved"})
                            except Exception:
                                _logger.exception("Failed to mark payslips approved for request %s", rec.name)

                            # --- NOTIFY KHALED (364) TO START PAYMENT CYCLE ---
                            if rec.approval_stage == 'procurement' and rec.payment_rule_id:
                                khaled = self.env['res.users'].sudo().browse(364)
                                if khaled.exists():
                                    rec.activity_schedule(
                                        'mail.mail_activity_data_todo',
                                        user_id=khaled.id,
                                        summary=_("Procurement Approved: Start Payment Cycle"),
                                        note=_("The procurement cycle for %s is complete. Please click 'Start Payment Cycle' to trigger the Payment Cycle.") % rec.name,
                                    )
                                    rec._post_note(_("🔔 Notified Khaled (364) to start the Payment Cycle."))

                            # --- NOTIFY ACCOUNTANT (355) ---
                            # We only want this to trigger at the very end of everything (Payment Cycle Done)
                            if rec.approval_stage == 'pay_review' and rec.amount and rec.amount > 0:
                                user_to_notify_and_follow = self.env['res.users'].browse(355)
                                if user_to_notify_and_follow.exists():
                                    try:
                                        rec.with_company(rec.company_id).message_subscribe(partner_ids=[user_to_notify_and_follow.partner_id.id])
                                    except Exception as e:
                                        _logger.warning("Subscribe failed for user %s on request %s: %s", user_to_notify_and_follow.id, rec.name, e)
                                    try:
                                        rec.with_company(rec.company_id).activity_schedule(
                                            'mail.mail_activity_data_todo',
                                            user_id=user_to_notify_and_follow.id,
                                            summary=_("Request Approved: %s") % rec.title,
                                            note=_("Your request %s has been approved. Please mark as paid.") % (rec.name),
                                        )
                                    except Exception as e:
                                        _logger.warning("Scheduling post-approval activity failed for user %s on request %s: %s", user_to_notify_and_follow.id, rec.name, e)

            except Exception as e:
                _logger.exception("Unhandled exception while approving request %s (id=%s): %s", rec.name, rec.id, e)
        return True

    def action_reject_request(self):
        """Current approver rejects; request becomes Rejected and requester is pinged.

        Semi-sudo strategy similar to approve:
        - Use sudo for IO/actions to avoid company/ACL issues
        - Minimal validation: only permit reject if user is the approver or is manager/su (privileged)
        - Mark the approver's activities done
        - Log extensively on fallback/invalid cases
        """
        MailActivity = self.env['mail.activity'].sudo()
        Line = self.env['kh.approval.line'].sudo()
        Request = self.sudo()

        for rec in Request:
            if rec.state != "in_review":
                _logger.info("Skip reject: request %s (id=%s) not in 'in_review' (state=%s).", rec.name, rec.id, rec.state)
                continue

            action_user = self.env.uid

            # Find the pending line for this user
            line = Line.search([
                ('request_id', '=', rec.id),
                ('state', '=', 'pending'),
                ('approver_id', '=', action_user),
            ], order='sequence, id', limit=1)

            if not line:
                pending = Line.search([('request_id', '=', rec.id), ('state', '=', 'pending')])
                pending_approvers = [(l.id, l.approver_id.id if l.approver_id else None) for l in pending]
                _logger.warning("No pending line matched user %s for request %s (id=%s) during reject. Pending lines: %s",
                                action_user, rec.name, rec.id, pending_approvers)

                is_privileged = (self.env.is_superuser() or self.env.user.has_group('kh_approvals.group_kh_approvals_manager'))
                if is_privileged and pending:
                    line = pending.sorted('sequence, id')[0]
                    _logger.info("Privileged user %s will reject fallback line id=%s for request %s (id=%s).",
                                 action_user, line.id, rec.name, rec.id)
                else:
                    _logger.error("User %s is not a pending approver for request %s (id=%s) and is not privileged. Abort reject.",
                                  action_user, rec.name, rec.id)
                    raise UserError(_("You are not the current approver."))

            try:
                _logger.info("User %s rejecting line id=%s (approver=%s) on request %s (id=%s).",
                             action_user, line.id, getattr(line, 'approver_id', False) and line.approver_id.id or None, rec.name, rec.id)

                # Mark any activities for the action_user as done (safe)
                try:
                    acts = MailActivity.search([('res_model', '=', rec._name), ('res_id', '=', rec.id), ('user_id', '=', action_user)])
                    if acts:
                        for a in acts:
                            try:
                                a.with_context(activity_mark_as_done=True).sudo().action_feedback(feedback=_("Rejected"))
                            except Exception:
                                try:
                                    a.with_context(activity_mark_as_done=True).sudo().action_done()
                                except Exception as e:
                                    _logger.exception("Failed to mark activity id=%s done while rejecting request %s: %s", getattr(a,'id',False), rec.name, e)
                except Exception as e:
                    _logger.exception("Failed while trying to close activities for user %s on request %s: %s", action_user, rec.name, e)

                # Mark the line rejected and mark request as rejected
                line.write({'state': 'rejected'})

                old_state = rec.state
                rec.write({'state': 'rejected'})
                try:
                    rec.message_post(
                        body=_("❌ Rejected  <b>%s</b>.") % self.env.user.name,
                        tracking_value_ids=[(0, 0, {
                            'field_id': self.env['ir.model.fields']._get(self._name, 'state').id,
                            'old_value_char': dict(self._fields['state'].selection).get(old_state),
                            'new_value_char': dict(self._fields['state'].selection).get('rejected'),
                        })],
                        message_type="notification",
                        subtype_xmlid="mail.mt_comment",
                        partner_ids=[rec.requester_id.partner_id.id]
                    )
                except Exception as e:
                    _logger.exception("Failed to post reject message for request %s: %s", rec.name, e)

                try:
                    rec._notify_partner(
                        rec.requester_id.partner_id,
                        _("❌ <b>Rejected</b>: <a href='%(link)s'>%(name)s: %(title)s</a>") % {"link": rec._deeplink(), "name": rec.name, "title": rec.title},
                        subject=f"Rejected: {rec.name}",
                    )
                except Exception as e:
                    _logger.exception("Failed to send reject partner notification for request %s: %s", rec.name, e)

                # For payslip type, update payslips
                try:
                    if rec.approval_type == "payslip":
                        rec.payslip_ids.sudo().write({"approval_state": "rejected"})
                except Exception:
                    _logger.exception("Failed to mark payslips rejected for request %s", rec.name)

            except Exception as e:
                _logger.exception("Unhandled exception while rejecting request %s (id=%s): %s", rec.name, rec.id, e)
        return True

    def action_opt_out_as_approver(self):
        # Feature disabled at your request
        raise UserError(_("This option has been disabled by your admin."))

    def action_mark_as_paid(self):
        """Accountant marks the request as paid (even if not an approver)."""
        for rec in self.sudo():
            if rec.payment_state == "paid":
                raise UserError(_("This request is already marked as paid."))

            # Change payment state
            rec.write({
                'payment_state': 'paid',
            })

            # Close accountant's activity
            accountant_acts = rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid)
            for act in accountant_acts:
                try:
                    act.with_context(activity_mark_as_done=True).sudo().action_done()
                except:
                    act.with_context(activity_mark_as_done=True).sudo().unlink()

            # Log message
            rec.message_post(
                body=_("💰 Marked as &lt;b&gt;Paid&lt;/b&gt; by &lt;b&gt;%s&lt;/b&gt;.") % self.env.user.name
            )

        return True

    def action_start_payment_cycle(self):
        """ This function triggers the second cycle (Payment) """
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Request must be Approved before starting Payment cycle."))
            if rec.approval_stage != 'procurement':
                raise UserError(_("Payment cycle already started."))
            if not rec.payment_rule_id:
                raise UserError(_("Please select a Payment Approval Rule before starting the next cycle."))

            # 1. Switch Stage
            rec.write({
                'approval_stage': 'pay_review',
                'state': 'in_review', # Go back to In Review
            })

            # 2. Build lines for the new stage
            rec._build_approval_lines()
            
            # 3. Notify new approvers
            rec._notify_pending_approvers()
            
            rec._post_note(_("🚀 <b>Payment Approval Cycle Started.</b>"))



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
    name = fields.Char("Name")
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
    approval_stage = fields.Selection(
        [('procurement', 'Procurement Cycle'), ('pay_review', 'Payment Cycle'), ('done', 'Fully Approved')],
        default='procurement',
        required=True
    )
    note = fields.Char()


# ============================================================================
# Petty Cash Line
# ============================================================================
class KhApprovalPettyCashLine(models.Model):
    _name = "kh.approval.petty.cash.line"
    _description = "Petty Cash Line"

    request_id = fields.Many2one("kh.approval.request", required=True, ondelete="cascade")
    name = fields.Char("Name", required=True)
    qty = fields.Float(string='Quantity', default=1.0)
    unit_price = fields.Float(string='Unit Price')
    unit = fields.Char(string='Unit')
