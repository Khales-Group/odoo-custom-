# -*- coding: utf-8 -*-

from odoo import api, fields, models

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    approval_request_ids = fields.Many2many(
        'kh.approval.request',
        string="Approval Requests",
        compute='_compute_approval_requests',
    )

    approval_request_count = fields.Integer(
        string="Approval Request Count",
        compute='_compute_approval_request_count',
    )

    def _compute_approval_requests(self):
        for employee in self:
            # An employee can have a linked user (hr.employee -> res.users)
            # A user can also have a linked employee (res.users -> hr.employee)
            # We check both to be robust.
            user = employee.user_id or self.env['res.users'].search([('employee_id', '=', employee.id)], limit=1)
            if user:
                # Search for all requests made by this user. Record rules will handle visibility.
                requests = self.env['kh.approval.request'].search([('requester_id', '=', user.id)])
                employee.approval_request_ids = requests
            else:
                employee.approval_request_ids = False

    @api.depends('approval_request_ids')
    def _compute_approval_request_count(self):
        for employee in self:
            employee.approval_request_count = len(employee.approval_request_ids)
