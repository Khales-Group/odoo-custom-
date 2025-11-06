# -*- coding: utf-8 -*-
from odoo import fields, models

class HrEmployee(models.Model):
    _inherit = "hr.employee"

    approval_request_count = fields.Integer(
        compute="_compute_approval_request_count",
        string="Approval Requests"
    )

    def _compute_approval_request_count(self):
        """Count all approval requests submitted by the employee's linked user."""
        for employee in self:
            if employee.user_id:
                employee.approval_request_count = self.env["kh.approval.request"].search_count(
                    [("requester_id", "=", employee.user_id.id)]
                )
            else:
                employee.approval_request_count = 0

    def action_open_approval_requests(self):
        """Smart button action to show approval requests for this employee."""
        self.ensure_one()
        return {
            "name": "Approval Requests",
            "type": "ir.actions.act_window",
            "res_model": "kh.approval.request",
            "view_mode": "list,form",
            "domain": [("requester_id", "=", self.user_id.id)],
            "context": {"default_requester_id": self.user_id.id},
        }