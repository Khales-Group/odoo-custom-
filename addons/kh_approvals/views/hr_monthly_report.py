# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date
try:
    from odoo.tools import Markup
except ImportError:
    from markupsafe import Markup

class KhHrMonthlyReport(models.Model):
    _name = 'kh.hr.monthly.report'
    _description = 'Monthly Employee Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_generated desc, id desc'

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default=lambda self: _('New'))
    
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True, readonly=True, index=True)
    manager_id = fields.Many2one('hr.employee', string="Manager", related='employee_id.parent_id', store=True, readonly=True, index=True)
    
    # Helper field for Record Rules (Manager POV)
    manager_user_id = fields.Many2one('res.users', related='manager_id.user_id', store=True, string="Manager User", index=True)
    user_id = fields.Many2one('res.users', string="User", related='employee_id.user_id', store=True, index=True)
    
    date_generated = fields.Date(string="Date", default=fields.Date.context_today, readonly=True)
    month_label = fields.Char(string="Month", compute='_compute_month_label', store=True)
    
    summary = fields.Html(string="Report Content")
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('reviewed', 'Reviewed')
    ], default='draft', string="Status", tracking=True)

    @api.depends('date_generated')
    def _compute_month_label(self):
        for rec in self:
            if rec.date_generated:
                rec.month_label = rec.date_generated.strftime('%B %Y')
            else:
                rec.month_label = ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('kh.hr.monthly.report') or _('New')
        return super().create(vals_list)

    def action_mark_reviewed(self):
        self.write({'state': 'reviewed'})

    @api.model
    def _cron_generate_monthly_reports(self):
        """ Generates a report for every active employee on the 29th. """
        employees = self.env['hr.employee'].search([('active', '=', True)])
        today = fields.Date.today()
        start_of_month = today.replace(day=1)
        
        vals_list = []
        for emp in employees:
            # Avoid duplicates for the same month
            exists = self.search_count([
                ('employee_id', '=', emp.id),
                ('date_generated', '>=', start_of_month),
                ('date_generated', '<=', today)
            ])
            if exists:
                continue
            
            vals_list.append({
                'employee_id': emp.id,
                'date_generated': today,
                'summary': Markup(f"<p>Monthly report automatically generated for <b>{emp.name}</b> on {today}.</p>"),
            })
            
        if vals_list:
            reports = self.create(vals_list)
            # Notify Managers via Activity
            for report in reports:
                if report.manager_user_id:
                    report.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=report.manager_user_id.id,
                        summary=f"Review Monthly Report: {report.employee_id.name}",
                        note=f"The monthly report for {report.month_label} is ready for your review."
                    )