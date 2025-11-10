# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError


class HrPayslipExtension(models.Model):
    _inherit = "hr.payslip"

    approval_request_id = fields.Many2one(
        "kh.approval.request",
        string="Approval Request",
        copy=False,
        readonly=True,
    )

    approval_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("to_approve", "To Approve"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Approval State",
        default="draft",
        copy=False,
        readonly=True,
        tracking=True,
    )

    def _get_ceo_user(self):
        # Find the CEO user based on their job title or a specific configuration
        # This is a placeholder implementation. You should adapt it to your needs.
        ceo_job = self.env["hr.job"].search([("name", "=", "Chief Executive Officer")], limit=1)
        if ceo_job:
            ceo_employee = self.env["hr.employee"].search([("job_id", "=", ceo_job.id)], limit=1)
            if ceo_employee and ceo_employee.user_id:
                return ceo_employee.user_id
        return self.env["res.users"]

    def action_request_approval(self):
        # Create a new approval request
        ceo_user = self._get_ceo_user()
        if not ceo_user:
            raise UserError(_("No CEO user found. Please configure a CEO in the system."))

        approval_request = self.env["kh.approval.request"].create({
            "title": "Payslip Approval Request",
            "requester_id": self.env.user.id,
            "payslip_ids": [(6, 0, self.ids)],
            "approval_type": "payslip",
            "rule_id": False,  # We are not using rules for this type of approval
        })

        # Set the approval state of the payslips
        self.write({
            "approval_state": "to_approve",
            "approval_request_id": approval_request.id,
        })

        # Create an activity for the CEO
        self.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=ceo_user.id,
            summary=_("Payslip Approval"),
            note=_("Please approve the following payslips."),
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "kh.approval.request",
            "res_id": approval_request.id,
            "view_mode": "form",
            "target": "current",
        }
