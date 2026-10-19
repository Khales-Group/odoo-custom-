# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

MAJID_ID = 369  # Majed - the manager; every escalation needs his approval
PRO_OFFICER_LOGIN = "hmam.h7@khales.ae"  # Hamam - Public Relations officer
LAWYER_LOGIN = "as.sami71@hotmail.com"  # Ahmed Ali - the lawyer


class KhCollectionCase(models.Model):
    _name = "kh.collection.case"
    _description = "Collection Case"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _rec_name = "name"

    name = fields.Char(string="Reference", compute="_compute_name", store=True)
    client_id = fields.Many2one("res.partner", string="Client", required=True, tracking=True)
    contractor_id = fields.Many2one("res.partner", string="Contractor", required=True, tracking=True)
    project_id = fields.Many2one("project.project", string="Project", required=True, tracking=True)
    amount = fields.Monetary(string="Amount to Collect", required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", string="Currency", default=lambda self: self.env.company.currency_id
    )
    accountant_id = fields.Many2one(
        "res.users", string="Accountant", default=lambda self: self._default_accountant(),
        required=True, tracking=True,
    )
    note = fields.Text(string="Notes")

    state = fields.Selection(
        [
            ("accountant", "With Accountant"),
            ("pending_pro_approval", "Pending Manager Approval (PRO)"),
            ("pro", "With PRO"),
            ("pending_law_approval", "Pending Manager Approval (Legal)"),
            ("law", "With Lawyer"),
            ("collected", "Collected"),
        ],
        string="Status",
        default="accountant",
        required=True,
        tracking=True,
    )

    report_id = fields.Many2one("x_reports", string="Law/PRO File", readonly=True, copy=False)
    pro_task_id = fields.Many2one("project.task", string="PRO Task", readonly=True, copy=False)
    law_task_id = fields.Many2one("project.task", string="Legal Task", readonly=True, copy=False)
    is_manager = fields.Boolean(string="Is Current User the Manager?", compute="_compute_is_manager")

    def _compute_is_manager(self):
        for rec in self:
            rec.is_manager = self.env.user.id == MAJID_ID

    @api.model
    def _default_accountant(self):
        # Looked up by name, not a fixed id - same approach already used
        # elsewhere in this codebase (project_ai_manager.py) since the real
        # user id for "Karan" isn't reliably known/fixed across environments.
        karan = self.env["res.users"].sudo().search([("name", "ilike", "karan")], limit=1)
        return karan or self.env.user

    @api.depends("client_id", "project_id")
    def _compute_name(self):
        for rec in self:
            parts = [p for p in (rec.client_id.name, rec.project_id.name) if p]
            rec.name = _("Collection - %s") % " / ".join(parts) if parts else _("Collection")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_manager(self):
        return self.env["res.users"].browse(MAJID_ID)

    def _get_pro_officer(self):
        return self.env["res.users"].search([("login", "=", PRO_OFFICER_LOGIN)], limit=1)

    def _get_lawyer(self):
        return self.env["res.users"].search([("login", "=", LAWYER_LOGIN)], limit=1)

    def _check_is_manager(self):
        if self.env.user.id != MAJID_ID:
            raise UserError(_("Only the manager can approve this escalation."))

    def _request_manager_approval(self, message):
        manager = self._get_manager()
        for rec in self:
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=manager.id,
                summary=_("Approval needed: collection case escalation"),
                note=message,
            )
            rec.message_post(body=message)

    def _close_my_pending_activities(self):
        self.activity_ids.filtered(lambda a: a.user_id.id == self.env.user.id).action_feedback(
            feedback=_("Approved")
        )

    # ------------------------------------------------------------------
    # Stage 1: accountant -> PRO (needs Majed's approval)
    # ------------------------------------------------------------------
    def action_request_pro_escalation(self):
        for rec in self:
            if rec.state != "accountant":
                raise UserError(_("You can only request escalation while the case is 'With Accountant'."))
            rec.state = "pending_pro_approval"
            rec._request_manager_approval(
                _("Accountant %s could not collect %s from %s. Waiting for your approval to transfer it to PRO.")
                % (rec.accountant_id.name, rec.amount, rec.client_id.name)
            )

    def action_reject_pro_escalation(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_pro_approval":
                continue
            rec.state = "accountant"
            rec._close_my_pending_activities()
            rec.message_post(body=_("Manager rejected the escalation - case sent back to the accountant."))

    def action_approve_pro_escalation(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_pro_approval":
                raise UserError(_("This case is not pending a PRO escalation approval."))
            pro_officer = rec._get_pro_officer()
            report = self.env["x_reports"].create(
                {
                    "x_name": rec.name,
                    "x_studio_type": "PRO",
                    "x_studio_user_id": pro_officer.id,
                    "x_studio_partner_id": rec.client_id.id,
                    "x_studio_company_id": rec.project_id.company_id.id or self.env.company.id,
                    "x_studio_notes": rec.note,
                    "x_studio_value": rec.amount,
                    "x_studio_many2one_field_4g2_1irjm2hqi": rec.project_id.id,  # "Project realted"
                    "kh_collection_case_id": rec.id,
                }
            )
            task = self.env["project.task"].create(
                {
                    "name": _("Collection: %s") % rec.name,
                    "project_id": rec.project_id.id,
                    "user_ids": [(6, 0, [pro_officer.id])],
                    "description": _("Collect %s from %s (contractor: %s). Accountant %s could not collect it.")
                    % (rec.amount, rec.client_id.name, rec.contractor_id.name, rec.accountant_id.name),
                }
            )
            rec.write(
                {
                    "state": "pro",
                    "report_id": report.id,
                    "pro_task_id": task.id,
                }
            )
            rec._close_my_pending_activities()
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=pro_officer.id,
                summary=_("A collection case has been transferred to you"),
                note=_("Collection case %s (amount %s) has been transferred to you - see file %s and its task.")
                % (rec.name, rec.amount, report.x_name),
            )
            rec.message_post(body=_("Manager approved - case transferred to %s (PRO).") % pro_officer.name)

    # ------------------------------------------------------------------
    # Stage 2: PRO -> Law (needs Majed's approval)
    # ------------------------------------------------------------------
    def action_request_law_escalation(self):
        for rec in self:
            if rec.state != "pro":
                raise UserError(_("You can only request escalation while the case is 'With PRO'."))
            rec.state = "pending_law_approval"
            rec._request_manager_approval(
                _("PRO could not collect %s from %s. Waiting for your approval to transfer it to the lawyer.")
                % (rec.amount, rec.client_id.name)
            )

    def action_reject_law_escalation(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_law_approval":
                continue
            rec.state = "pro"
            rec._close_my_pending_activities()
            rec.message_post(body=_("Manager rejected the escalation - case sent back to PRO."))

    def action_approve_law_escalation(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_law_approval":
                raise UserError(_("This case is not pending a legal escalation approval."))
            lawyer = rec._get_lawyer()
            if rec.report_id:
                # Same file, moved to the Law department - kh_law automatically
                # resets it to the first Law stage when x_studio_type changes.
                rec.report_id.write({"x_studio_type": "Law", "x_studio_user_id": lawyer.id})
            task = self.env["project.task"].create(
                {
                    "name": _("Collection (Legal): %s") % rec.name,
                    "project_id": rec.project_id.id,
                    "user_ids": [(6, 0, [lawyer.id])],
                    "description": _("Collect %s from %s (contractor: %s) through legal action.")
                    % (rec.amount, rec.client_id.name, rec.contractor_id.name),
                }
            )
            rec.write({"state": "law", "law_task_id": task.id})
            rec._close_my_pending_activities()
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=lawyer.id,
                summary=_("A collection case has been transferred to you"),
                note=_("Collection case %s (amount %s) has been transferred to you for legal follow-up.")
                % (rec.name, rec.amount),
            )
            rec.message_post(body=_("Manager approved - case transferred to %s (Lawyer).") % lawyer.name)

    # ------------------------------------------------------------------
    # Any stage -> Collected
    # ------------------------------------------------------------------
    def action_mark_collected(self):
        for rec in self:
            rec.state = "collected"
            rec.activity_ids.action_feedback(feedback=_("Collected"))
            rec.message_post(body=_("Amount collected."))
