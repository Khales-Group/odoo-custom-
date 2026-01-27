# -*- coding: utf-8 -*-
from odoo import models, fields, api

class KhBoqSubmission(models.Model):
    _name = 'kh.boq.submission'
    _description = 'BOQ Submission'
    _rec_name = 'partner_id'
    _order = 'submission_date desc'

    project_id = fields.Many2one('project.project', string="Project", required=True)
    partner_id = fields.Many2one('res.partner', string="Contractor", default=lambda self: self.env.user.partner_id)
    submission_date = fields.Datetime(default=fields.Datetime.now)
    line_ids = fields.One2many('kh.boq.line', 'submission_id', string="Lines")
    total_amount = fields.Monetary(compute='_compute_total', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='project_id.currency_id')

    @api.depends('line_ids.total')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('total'))

class KhBoqLine(models.Model):
    _name = 'kh.boq.line'
    _description = 'BOQ Submission Line'

    submission_id = fields.Many2one('kh.boq.submission', ondelete='cascade')
    plan_line_id = fields.Many2one('kh.project.boq.plan', string="Plan Item")
    
    # Snapshot fields in case master changes
    section_name = fields.Char(related='plan_line_id.section_name', store=True)
    item_description = fields.Char(related='plan_line_id.item_description', store=True)
    quantity = fields.Float(string="Qty", required=True)
    
    unit_price = fields.Float(string="Unit Price", required=True)
    total = fields.Float(compute='_compute_total', store=True)

    @api.depends('quantity', 'unit_price')
    def _compute_total(self):
        for rec in self:
            rec.total = rec.quantity * rec.unit_price