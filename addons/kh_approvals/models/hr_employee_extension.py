# -*- coding: utf-8 -*-

from odoo import fields, models

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    approval_request_ids = fields.One2many(
        'kh.approval.request',
        'requester_id',
        string="Approval Requests",
        compute='_compute_approval_request_ids',
        store=False,
    )

    def _compute_approval_request_ids(self):
        for employee in self:
            if employee.user_id:
                employee.approval_request_ids = self.env['kh.approval.request'].search([
                    ('requester_id', '=', employee.user_id.id)
                ])
            else:
                employee.approval_request_ids = False,
