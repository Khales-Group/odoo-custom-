# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError


class HrPayslipExtension(models.Model):
    _inherit = "hr.payslip"

    # =========================================================
    # FIX FOR PRINT ERROR
    # =========================================================
    # The standard layout expects a 'partner_id' to print the address.
    # We link this to the Employee's Private Address (address_home_id).
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        related='employee_id.address_home_id',
        readonly=True,
    )
    # =========================================================

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
        department_id = False
        kh_department_id = False
        total_amount = sum(self.mapped('net_wage'))

        if self:
            department = self[0].employee_id.department_id
            if department:
                kh_department = self.env['kh.approvals.department'].search([('name', '=', department.name)], limit=1)
                if kh_department:
                    kh_department_id = kh_department.id
        
        # Create a new approval request
        approval_request = self.env["kh.approval.request"].create({
            "title": "Payslip Approval Request",
            "requester_id": self.env.user.id,
            "payslip_ids": [(6, 0, self.ids)],
            "approval_type": "payslip",
            "amount": total_amount,
            "rule_id": False,  # We are not using rules for this type of approval
            "department_id": kh_department_id,
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