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

    def action_request_approval(self):
        # Create a new approval request
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

        return {
            "type": "ir.actions.act_window",
            "res_model": "kh.approval.request",
            "res_id": approval_request.id,
            "view_mode": "form",
            "target": "current",
        }
