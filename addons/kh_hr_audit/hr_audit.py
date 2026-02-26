# -*- coding: utf-8 -*-
from odoo import models, fields, api

class KhHrAudit(models.Model):
    _name = 'kh.hr.audit'
    _description = 'HR Monthly Audit'

    name = fields.Char(string="Audit Name")
    manager_id = fields.Many2one('hr.employee', string="Manager")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent')
    ], default='draft')