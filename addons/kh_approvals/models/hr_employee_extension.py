# -*- coding: utf-8 -*-

from odoo import fields, models

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    approval_request_ids = fields.One2many(
        'kh.approval.request',
        'employee_id',
        string="Approval Requests",
    )

    approval_request_count = fields.Integer(
        string="Approval Request Count",
        compute='_compute_approval_request_count',
    )

    def _compute_approval_request_count(self):
        for employee in self:
            employee.approval_request_count = len(employee.approval_request_ids)
