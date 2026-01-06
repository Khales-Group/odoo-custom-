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
        string="Current Stage",
        required=False,
        tracking=True
    )

    is_purchase_request = fields.Boolean(compute='_compute_is_purchase_request', store=True)

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
    @api.depends('rule_id')
    def _compute_is_purchase_request(self):
        for rec in self:
            # Check if the rule name matches your specific purchase request rule
            is_pr = rec.rule_id and rec.rule_id.name == 'Purchase request'
            rec.is_purchase_request = is_pr
            
            # Automatically set the initial stage ONLY for Purchase Requests in Draft
            if is_pr and not rec.approval_stage and rec.state == 'draft':
                rec.approval_stage = 'procurement'
            elif not is_pr:
                rec.approval_stage = False # Keep empty for all other rules

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
        """ Regenerate lines without strict department blocking for payment cycles """
        for rec in self:
            current_stage = rec.approval_stage or 'procurement'
            rec.approval_line_ids.filtered(lambda l: l.approval_stage == current_stage).sudo().unlink()
            
            vals_list = []
            if rec.approval_type == 'standard':
                # Use rule_id for procurement, and payment_rule_id for the next cycle
                rule = rec.rule_id if current_stage == 'procurement' else rec.payment_rule_id
                
                if not rule:
                    raise UserError(_("Please select an Approval Rule for the '%s' stage.") % current_stage)
                
                # --- FIX: Remove the strict department check to allow Payment Rules to work ---
                if rule.company_id and rule.company_id != rec.company_id:
                    raise UserError(_("Rule belongs to another company."))

                steps = rule.step_ids.sorted(key=lambda s: (s.sequence, s.id))
                for step in steps:
                    if not step.approver_id: continue
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

            if vals_list:
                min_sequence = min(v['sequence'] for v in vals_list)
                for v in vals_list:
                    if v['sequence'] == min_sequence: v['state'] = 'pending'
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
        Resets the request to Draft and clears all cycle-related data 
        to ensure a fresh start.
        """
        for rec in self.sudo():
            if rec.requester_id.id != self.env.uid and not self.env.user.has_group('kh_approvals.group_kh_approvals_manager'):
                raise AccessError("Only the requester or a manager can revise this request.")
            
            if rec.state not in ('in_review', 'approved', 'rejected'):
                raise UserError("Only non-Draft requests can be revised.")

            # 1. Clear approval lines for the active stage
            rec.approval_line_ids.filtered(lambda l: l.approval_stage == rec.approval_stage).unlink()

            # 2. RESET CYCLE FIELDS
            # Clear the payment rule and set stage back to Procurement
            vals = {
                'state': 'draft',
                'revision': rec.revision + 1,
                'last_revised_by': self.env.user.id,
                'last_revised_on': fields.Datetime.now(),
                'submitted_on': False,
                'payment_rule_id': False, # This clears the 'Purchase Payment' selection
            }
            
            # Only reset stage if it's a Purchase Request
            if rec.is_purchase_request:
                vals['approval_stage'] = 'procurement'
            else:
                vals['approval_stage'] = False

            rec.write(vals)

            # 3. Close any open activities
            rec._close_all_todos()

            rec._post_note(
                "✏️ <b>Request Revised:</b> All approval steps reset. Cycle data cleared."
            )
        return True

    def action_withdraw_request(self):
        # Feature disabled at your request
        raise UserError(_("This option has been disabled by your administrator."))

    def action_approve_request(self):
        """ Sequential Approval & Khaled Notification """
        Line = self.env['kh.approval.line'].sudo()
        for rec in self.sudo():
            if rec.state != "in_review": continue

            line = Line.search([('request_id', '=', rec.id), ('state', '=', 'pending'), ('approver_id', '=', self.env.uid)], limit=1)
            if not line and self.env.user.has_group('kh_approvals.group_kh_approvals_manager'):
                line = Line.search([('request_id', '=', rec.id), ('state', '=', 'pending')], limit=1)
            
            if not line: raise UserError("You are not the current approver.")

            # 1. Approve current line
            line.write({'state': 'approved'})
            rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid).sudo().action_feedback(feedback="Approved")

            # 2. Check if there are more people at this SAME sequence level
            other_pending = Line.search_count([
                ('request_id', '=', rec.id),
                ('sequence', '=', line.sequence),
                ('state', '!=', 'approved')
            ])

            if other_pending == 0:
                # 3. Move to the NEXT sequence level (Sequential logic)
                next_line = Line.search([
                    ('request_id', '=', rec.id),
                    ('sequence', '>', line.sequence),
                    ('state', '=', 'waiting')
                ], order='sequence, id', limit=1)

                if next_line:
                    # Only mark the very next level as pending
                    Line.search([('request_id', '=', rec.id), ('sequence', '=', next_line.sequence)]).write({'state': 'pending'})
                    rec._notify_pending_approvers()
                else:
                    # --- PROCUREMENT CYCLE FINISHED ---
                    rec.write({'state': 'approved'})
                    if rec.approval_stage == 'procurement':
                        khaled = self.env['res.users'].browse(364)
                        if khaled.exists():
                            rec.activity_schedule(
                                'mail.mail_activity_data_todo',
                                user_id=khaled.id,
                                summary="Update Amount & Start Payment Cycle",
                                note="Procurement approved. Please check/update the final amount and click 'Start Payment Cycle'."
                            )
        return True

    def action_reject_request(self):
        """ Mark activity as done with 'Rejected' feedback """
        for rec in self.sudo():
            rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid).sudo().action_feedback(feedback=_("Rejected"))
            rec.write({'state': 'rejected'})
            rec.approval_line_ids.filtered(lambda l: l.state == 'pending' and l.approver_id.id == self.env.uid).write({'state': 'rejected'})
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
        """ Start Cycle 2 with Sequential Activities """
        for rec in self.sudo():
            if rec.state != 'approved': raise UserError("Request must be Approved first.")
            
            payment_rule = self.env['kh.approval.rule'].search([
                ('name', '=', 'Purchase Payment'),
                ('company_id', '=', rec.company_id.id)
            ], limit=1)
            
            if not payment_rule:
                raise UserError("No rule named 'Purchase Payment' found for this company.")

            # Switch Stage
            rec.write({
                'payment_rule_id': payment_rule.id,
                'approval_stage': 'pay_review',
                'state': 'in_review',
            })

            # This method generates lines and marks only the FIRST sequence as 'pending'
            rec._build_approval_lines()
            rec._notify_pending_approvers()
            rec._close_my_open_todos()
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
