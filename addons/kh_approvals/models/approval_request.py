# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


# ============================================================================
# Approval Request  (NO emails, NO chatter, NO activities)
# ============================================================================
class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Khales Approval Request"
    # Keep mail mixins OUT to avoid any implicit messaging.
    # If your views include a chatter widget, leave the mixins in and
    # always write with tracking_disable=True; but you asked to remove everything.
    # _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True

    # -------------------------------------------------------------------------
    # Fields
    # -------------------------------------------------------------------------
    name = fields.Char(required=True)

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    department_id = fields.Many2one(
        "kh.approvals.department",
        string="Department",
    )

    requester_id = fields.Many2one(
        "res.users",
        string="Requester",
        default=lambda self: self.env.user.id,
    )

    amount = fields.Monetary(string="Amount", currency_field="currency_id")

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
        index=True,
    )

    # Single rule selector (rule defines company/department/approver sequence)
    rule_id = fields.Many2one(
        "kh.approval.rule",
        string="Approval Rule",
        required=True,
        domain="[('company_id','in',[False, company_id]), '|', ('department_id','=',False), ('department_id','=',department_id)]",
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
    # Steps generation  (NO messaging)
    # -------------------------------------------------------------------------
    def _build_approval_lines(self):
        """
        (Re)generate approval steps based on the chosen rule (single rule).
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
    # Actions (buttons) — NO emails, NO chatter, NO activities
    # -------------------------------------------------------------------------
    def action_submit(self):
        """Requester submits: build steps and move to in_review."""
        for rec in self:
            if rec.state != "draft":
                continue
            rec._build_approval_lines()
            # Make the state change without tracking (in case mail.thread was re-added)
            rec.with_context(tracking_disable=True).write({"state": "in_review"})
        return True

    def action_approve_request(self):
        """Current approver approves their step; finish or move to next approver."""
        for rec in self:
            if rec.state != "in_review":
                continue

            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or line.approver_id.id != self.env.uid:
                raise UserError(_("You are not the current approver."))

            # Approve my step
            line.write({"state": "approved"})

            # Next approver or finished
            next_line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not next_line:
                rec.with_context(tracking_disable=True).write({"state": "approved"})
        return True

    def action_reject_request(self):
        """Current approver rejects; request becomes Rejected."""
        for rec in self:
            if rec.state != "in_review":
                continue

            line = rec.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]
            if not line or line.approver_id.id != self.env.uid:
                raise UserError(_("You are not the current approver."))

            line.write({"state": "rejected"})
            rec.with_context(tracking_disable=True).write({"state": "rejected"})
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
