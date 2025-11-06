# -*- coding: utf-8 -*-

from odoo import fields, models

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    approval_request_ids = fields.One2many(
        'kh.approval.request',
        'employee_id',
        string="Approval Requests",
    )