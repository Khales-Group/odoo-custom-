# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError
try:
    from odoo.tools import Markup
except ImportError:
    from markupsafe import Markup

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
    x_studio_project = fields.Many2one('project.project', string='Project', ondelete='cascade', index=True)
    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', ondelete='cascade', index=True)
    crm_lead_id = fields.Many2one('crm.lead', string='Related Lead', ondelete='cascade', index=True)
    
    # حقل مؤقت: يربط الاسم القديم بالاسم الجديد لمنع انهيار النظام بسبب العرض القديم
    project_id = fields.Many2one('project.project', related='x_studio_project', string='Project (Legacy)')

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
    partner_id = fields.Many2one('res.partner', string="Vendor", tracking=True)

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
        return {'title', 'amount', 'currency_id', 'company_id', 'department_id', 'rule_id', 'partner_id', 'x_studio_project'}

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
        """ Strictly set only the FIRST sequence level to 'pending' """
        for rec in self:
            current_stage = rec.approval_stage or 'procurement'
            rec.approval_line_ids.filtered(lambda l: l.approval_stage == current_stage).sudo().unlink()
            
            vals_list = []
            rule = rec.rule_id if current_stage == 'procurement' else rec.payment_rule_id
            
            # --- Dynamic Project Approval (Khales Project Management) ---
            # Inject Majed (369) or Mamon (385) based on Project Tags
            if rec.x_studio_project and rec.company_id and 'khales project management' in rec.company_id.name.lower():
                tags = rec.x_studio_project.sudo().tag_ids.mapped('name')
                tags_lower = [t.lower() for t in tags]
                
                # Check for Sharjah (shrajah) or Fujairah
                if any(t in tags_lower for t in ['sharjah', 'shrajah', 'fujairah']):
                    vals_list.append({
                        "request_id": rec.id,
                        "name": "Flexible Project Approval - Sharjah/Fujairah",
                        "approver_id": 369,  # Majed
                        "required": True,
                        "state": "waiting",
                        "company_id": rec.company_id.id,
                        "sequence": 1,
                        "approval_stage": current_stage,
                    })

            if not rule and not vals_list:
                continue

            if rule:
                # 1. Create all lines as 'waiting' by default
                for step in rule.step_ids.sorted('sequence'):
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
                # 2. Find the lowest sequence number in this new set
                min_seq = min(v['sequence'] for v in vals_list)
                for v in vals_list:
                    if v['sequence'] == min_seq:
                        v['state'] = 'pending' # ONLY the first level is pending
                
                self.env["kh.approval.line"].sudo().create(vals_list)

    # -------------------------------------------------------------------------
    # Actions (buttons)
    # -------------------------------------------------------------------------
    def action_submit(self):
        """Requester submits: build steps, move to in_review, notify first approver."""
        for rec in self:
            if rec.state != "draft":
                continue
            
            # Validation: Rule is mandatory for standard requests
            # Relax validation for Khales Project Management if Project is set (Dynamic Approval)
            is_dynamic_project = rec.x_studio_project and rec.company_id and 'khales project management' in rec.company_id.name.lower()

            if rec.approval_type == 'standard' and not rec.rule_id and not is_dynamic_project:
                raise UserError(_("Please select an Approval Rule before submitting."))

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
        Full Reset: Clears ALL approval lines (Procurement & Payment) 
        so the new Revision starts fresh.
        """
        for rec in self.sudo():
            # Permission check
            if rec.requester_id.id != self.env.uid and not self.env.user.has_group('kh_approvals.group_kh_approvals_manager'):
                raise AccessError(_("Only the requester or a manager can revise this request."))
            
            if rec.state not in ('in_review', 'approved', 'rejected'):
                raise UserError(_("Only non-Draft requests can be revised."))

            # 1. DELETE ALL APPROVAL LINES (Clean Slate)
            # We remove everything because a Revised request requires full re-approval.
            rec.approval_line_ids.sudo().unlink()

            # 2. RESET FIELDS
            vals = {
                'state': 'draft',
                'revision': rec.revision + 1,
                'last_revised_by': self.env.user.id,
                'last_revised_on': fields.Datetime.now(),
                'submitted_on': False,
                'payment_rule_id': False, # Clear the Payment Rule
            }
            
            # Reset stage based on rule type
            if rec.is_purchase_request:
                vals['approval_stage'] = 'procurement'
            else:
                vals['approval_stage'] = False

            rec.write(vals)

            # 3. Close any open activities from the old version
            rec._close_all_todos()

            # 4. Log the History in Chatter
            rec._post_note(
                _("✏️ <b>Request Revised (Rev %s):</b><br/>"
                  "All previous approval steps have been cleared for re-approval.<br/>"
                  "Check the chatter history above for previous approval logs.") % (rec.revision + 1)
            )
        return True

    def action_withdraw_request(self):
        # Feature disabled at your request
        raise UserError(_("This option has been disabled by your administrator."))

    def action_approve_request(self):
        """ 
        Approves the current line. 
        Fixes the 'Invalid Operation' error by correctly handling empty stages.
        """
        Line = self.env['kh.approval.line'].sudo()
        
        for rec in self.sudo():
            # FIX: If stage is empty (False), default to 'procurement' to match the lines
            current_stage_filter = rec.approval_stage or 'procurement'

            # 1. STRICT SEARCH: Filter by Request + User + Pending + CORRECT STAGE
            line = Line.search([
                ('request_id', '=', rec.id),
                ('state', '=', 'pending'),
                ('approver_id', '=', self.env.uid),
                ('approval_stage', '=', current_stage_filter)  # <--- FIXED FILTER
            ], limit=1)

            if not line:
                # Manager fallback
                if self.env.user.has_group('kh_approvals.group_kh_approvals_manager'):
                    line = Line.search([
                        ('request_id', '=', rec.id),
                        ('state', '=', 'pending'),
                        ('approval_stage', '=', current_stage_filter) # <--- FIXED FILTER
                    ], limit=1)
            
            if not line:
                raise UserError(_("Invalid Operation: You are not the current active approver for this stage."))

            # 2. Approve the found line
            line.write({'state': 'approved'})
            rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid).sudo().action_feedback(feedback="Approved")

            # 3. Check for peers at the same sequence IN THIS STAGE
            same_level_pending = Line.search_count([
                ('request_id', '=', rec.id),
                ('sequence', '=', line.sequence),
                ('approval_stage', '=', current_stage_filter), 
                ('state', '!=', 'approved'),
                ('required', '=', True)
            ])

            if same_level_pending == 0:
                # 4. Find the NEXT sequence level IN THIS STAGE
                next_step = Line.search([
                    ('request_id', '=', rec.id),
                    ('sequence', '>', line.sequence),
                    ('approval_stage', '=', current_stage_filter), 
                    ('state', '=', 'waiting')
                ], order='sequence, id', limit=1)

                if next_step:
                    # Activate next steps
                    next_seq_val = next_step.sequence
                    Line.search([
                        ('request_id', '=', rec.id), 
                        ('sequence', '=', next_seq_val),
                        ('approval_stage', '=', current_stage_filter)
                    ]).write({'state': 'pending'})
                    
                    rec._notify_pending_approvers()
                else:
                    # --- STAGE COMPLETE ---
                    rec.write({'state': 'approved'})
                    
                    # Logic for Two-Cycle Requests (Purchase Request)
                    is_procurement_cycle = (
                        rec.approval_stage == 'procurement' or 
                        (not rec.approval_stage and rec.is_purchase_request)
                    )
                    
                    if is_procurement_cycle:
                        if not rec.approval_stage: rec.write({'approval_stage': 'procurement'})

                        # --- NEW: Create Empty PO if Purchase Request ---
                        if rec.is_purchase_request and not rec.purchase_order_id:
                            # Use selected vendor or fallback to a dummy 'Pending Vendor'
                            partner = rec.partner_id
                            if not partner:
                                partner = self.env['res.partner'].sudo().search([('name', '=', 'Pending Vendor')], limit=1)
                                if not partner:
                                    partner = self.env['res.partner'].sudo().create({
                                        'name': 'Pending Vendor',
                                        'is_company': True,
                                    })
                            
                            # Find picking type (Deliver To) - Required by Purchase Order
                            picking_type = self.env['stock.picking.type'].sudo().search([
                                ('code', '=', 'incoming'),
                                ('company_id', '=', rec.company_id.id)
                            ], limit=1)
                            
                            # Fallback: Search via warehouse if direct match fails
                            if not picking_type:
                                picking_type = self.env['stock.picking.type'].sudo().search([
                                    ('code', '=', 'incoming'),
                                    ('warehouse_id.company_id', '=', rec.company_id.id)
                                ], limit=1)

                            if not picking_type:
                                raise UserError(_("Cannot create Purchase Order: No 'Incoming Shipment' picking type found for company %s.") % rec.company_id.name)

                            po_vals = {
                                'partner_id': partner.id,
                                'company_id': rec.company_id.id,
                                'currency_id': rec.currency_id.id,
                                'origin': rec.name,
                                'date_order': fields.Datetime.now(),
                                'picking_type_id': picking_type.id,
                                'kh_approval_id': rec.id,
                            }

                            # Create PO (sudo to ensure permissions)
                            po = self.env['purchase.order'].sudo().create(po_vals)
                            rec.purchase_order_id = po.id
                            
                            # Populate Studio field if it exists (Legacy Support)
                            if 'x_studio_purchase_order' in rec._fields:
                                rec.write({'x_studio_purchase_order': po.id})
                            
                            # Assign activity to Khalid on the new PO
                            khaled = self.env['res.users'].sudo().browse(364)
                            if khaled.exists():
                                po.activity_schedule(
                                    'mail.mail_activity_data_todo',
                                    user_id=khaled.id,
                                    summary=_("New PO from Approval: %s") % rec.name,
                                    note=_("This PO was automatically created from Approval Request %s. Please review.") % rec.name
                                )
                        
                        khaled = self.env['res.users'].sudo().browse(364)
                        if khaled.exists():
                            rec.activity_schedule(
                                'mail.mail_activity_data_todo',
                                user_id=khaled.id,
                                summary=_("Procurement Approved: Start Payment Cycle"),
                                note=_("Please click 'Start Payment Cycle' to proceed.")
                            )
                    
                    # Logic for Payment Cycle OR Single Payment Requests
                    elif rec.approval_stage == 'pay_review' or not rec.is_purchase_request:
                        # If it's a simple Payment Request (not purchase request), we mark as done
                        if rec.approval_stage == 'pay_review':
                             rec.write({'approval_stage': 'done'})
                        
                        accountant = self.env['res.users'].sudo().browse(355)
                        if accountant.exists():
                            rec.activity_schedule(
                                'mail.mail_activity_data_todo',
                                user_id=accountant.id,
                                summary=_("Fully Approved: Mark as Paid"),
                                note=_("Payment cycle complete.")
                            )
        return True

    def action_reject_request(self):
        """ Open wizard to enter rejection reason. """
        self.ensure_one()
        return {
            'name': _('Reject Request'),
            'type': 'ir.actions.act_window',
            'res_model': 'kh.approval.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _reject_with_reason(self, reason):
        """ Perform rejection with logged reason. """
        for rec in self.sudo():
            # 1. Log feedback on activity (Close To-Do)
            rec.activity_ids.filtered(lambda a: a.user_id.id == self.env.uid).sudo().action_feedback(
                feedback=_("Rejected. Reason: %s") % reason
            )
            
            # 2. Update Request State
            rec.write({'state': 'rejected'})
            
            # 3. Update Approval Line State
            rec.approval_line_ids.filtered(
                lambda l: l.state == 'pending' and l.approver_id.id == self.env.uid
            ).write({'state': 'rejected', 'note': reason})

            # 4. Log in Chatter
            rec.message_post(
                body=Markup(_("❌ <b>Request Rejected</b> by %s.<br/><b>Reason:</b> %s")) % (self.env.user.name, reason),
                message_type="comment",
                subtype_xmlid="mail.mt_note",
            )
            
            # 5. Notify Requester
            if rec.requester_id.partner_id:
                rec._notify_partner(
                    partner=rec.requester_id.partner_id,
                    body_html=Markup(_("Your request <b>%s</b> has been rejected by %s.<br/><b>Reason:</b> %s")) % (rec.name, self.env.user.name, reason),
                    subject=_("Request Rejected: %s") % rec.title
                )
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
        """ 
        Starts Cycle 2. 
        RESTRICTION: Only Khaled (ID 364) can trigger this action.
        """
        # 1. STRICT ID CHECK: Block anyone who is not Khaled
        if self.env.user.id != 364:
            raise UserError(_("Access Denied: Only Khaled (ID 364) is authorized to start the Payment Cycle."))

        for rec in self.sudo():
            if rec.state != 'approved':
                raise UserError(_("Request must be Approved before starting the Payment cycle."))
            
            # --- AUTOMATIC SYSTEM FILLING ---
            payment_rule = self.env['kh.approval.rule'].search([
                ('name', '=', 'Purchase Payment'),
                ('company_id', '=', rec.company_id.id)
            ], limit=1)
            
            if not payment_rule:
                raise UserError(_("System Error: No rule named 'Purchase Payment' found for company '%s'.") % rec.company_id.name)

            # Switch Stage
            rec.write({
                'payment_rule_id': payment_rule.id,
                'approval_stage': 'pay_review',
                'state': 'in_review',
            })

            # Generate lines for the second cycle
            rec._build_approval_lines()
            rec._notify_pending_approvers()
            
            # Close Khaled's activity
            rec._close_my_open_todos()
            
            rec._post_note(_("🚀 <b>Cycle 2 Started:</b> Payment Cycle triggered by Khaled."))
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


# ============================================================================
# Reject Wizard
# ============================================================================
class KhApprovalRejectWizard(models.TransientModel):
    _name = "kh.approval.reject.wizard"
    _description = "Reject Request Wizard"

    request_id = fields.Many2one('kh.approval.request', required=True)
    reason = fields.Text(string="Reason for Rejection", required=True)

    def action_confirm(self):
        self.ensure_one()
        self.request_id._reject_with_reason(self.reason)
        return {'type': 'ir.actions.act_window_close'}
