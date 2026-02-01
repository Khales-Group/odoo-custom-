from odoo import models, fields, api, _
from odoo.exceptions import UserError

# --- Submission Header (عرض السعر) ---
class BoqSubmission(models.Model):
    _name = 'kh.boq.submission'
    _description = 'Contractor Bid Submission'
    _rec_name = 'contractor_id'

    project_id = fields.Many2one('project.project', string="Project", readonly=True)
    contractor_id = fields.Many2one('res.partner', string="Contractor", readonly=True)
    submission_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    
    line_ids = fields.One2many('kh.boq.line', 'submission_id', string="Bid Lines")
    total_amount = fields.Float(compute='_compute_total', string="Total Bid Value", store=True)

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('subtotal'))

# --- Submission Lines (تفاصيل عرض السعر) ---
class BoqSubmissionLine(models.Model):
    _name = 'kh.boq.line'
    _description = 'Bid Line Detail'

    submission_id = fields.Many2one('kh.boq.submission', string="Submission")
    plan_line_id = fields.Many2one('kh.project.boq.plan', string="Original Item")
    
    # حقول Related لتظهر البيانات تلقائياً من الماستر
    section_name = fields.Char(related='plan_line_id.section_name', string="Section", store=True)
    item_description = fields.Char(related='plan_line_id.item_description', string="Description", store=True)
    uom_id = fields.Char(related='plan_line_id.uom_id', string="Unit", store=True)
    
    quantity = fields.Float(string="Qty", readonly=True)
    unit_price = fields.Float(string="Unit Price", readonly=True)
    subtotal = fields.Float(compute='_compute_subtotal', string="Subtotal", store=True)

    @api.depends('quantity', 'unit_price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.unit_price
