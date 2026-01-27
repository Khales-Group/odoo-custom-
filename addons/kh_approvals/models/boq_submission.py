from odoo import models, fields, api

class BoqSubmission(models.Model):
    _name = 'kh.boq.submission'
    _description = 'BOQ Submission'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    project_id = fields.Many2one('project.project', string="Project", required=True)
    applicant_name = fields.Char(string="Applicant/Company", required=True)
    line_ids = fields.One2many('kh.boq.line', 'submission_id', string="Lines")
    total_amount = fields.Float(string="Grand Total", compute="_compute_total", store=True)
    state = fields.Selection([('draft', 'Draft'), ('submitted', 'Submitted')], default='submitted')

    @api.depends('line_ids.total')
    def _compute_total(self):
        for record in self:
            record.total_amount = sum(line.total for line in record.line_ids)

class BoqSubmissionLine(models.Model):
    _name = 'kh.boq.line'
    _description = 'BOQ Line Item'

    submission_id = fields.Many2one('kh.boq.submission')
    product_id = fields.Many2one('product.product', string="Item")
    quantity = fields.Float(string="Qty")
    price_unit = fields.Float(string="Unit Price")
    total = fields.Float(string="Total", compute="_compute_row_total", store=True)

    @api.depends('quantity', 'price_unit')
    def _compute_row_total(self):
        for line in self:
            line.total = line.quantity * line.price_unit