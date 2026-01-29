# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)

class KhHrAudit(models.Model):
    _name = 'kh.hr.audit'
    _description = 'HR Monthly Audit Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'audit_date desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    manager_id = fields.Many2one('hr.employee', string='Manager', required=True, help="Manager receiving the report")
    department_id = fields.Many2one('hr.department', string='Department')
    audit_date = fields.Date(string='Audit Date', default=fields.Date.context_today, readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('sent', 'Sent')], default='draft', string="Status")
    
    # Employee details within the report for archiving
    line_ids = fields.One2many('kh.hr.audit.line', 'audit_id', string='Audit Lines')
    
    # Statistical fields for the interface (Graph/Pivot)
    avg_performance = fields.Float(string='Average Performance', compute='_compute_stats', store=True)

    @api.depends('line_ids.score')
    def _compute_stats(self):
        for rec in self:
            if rec.line_ids:
                rec.avg_performance = sum(rec.line_ids.mapped('score')) / len(rec.line_ids)
            else:
                rec.avg_performance = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('kh.hr.audit') or _('New')
        return super().create(vals_list)

    @api.model
    def _cron_generate_monthly_reports(self):
        """ Called on the 29th of each month via Cron """
        # Fetch all managers who have subordinates
        managers = self.env['hr.employee'].search([('child_ids', '!=', False)])
        
        for manager in managers:
            # Create a draft report for the manager
            audit = self.create({
                'manager_id': manager.id,
                'department_id': manager.department_id.id,
            })
            
            # Add a line for each subordinate
            for sub in manager.child_ids:
                self.env['kh.hr.audit.line'].create({
                    'audit_id': audit.id,
                    'employee_id': sub.id,
                    'score': 80.0, # Placeholder for your performance logic
                })
            
            # Send the report via email
            audit.action_send_audit_report()

    def action_send_audit_report(self):
        template = self.env.ref('kh_hr_audit.email_template_hr_audit', raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
            self.write({'state': 'sent'})

class KhHrAuditLine(models.Model):
    _name = 'kh.hr.audit.line'
    _description = 'HR Audit Line'

    audit_id = fields.Many2one('kh.hr.audit', string='Audit Ref', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    score = fields.Float(string='Performance Score %')
    notes = fields.Text(string='Notes')