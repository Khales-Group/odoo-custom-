from odoo import models, fields, api, _
from datetime import datetime
import pytz # مكتبة التوقيت

class BoqSubmission(models.Model):
    _name = 'kh.boq.submission'
    _description = 'BOQ Submission'
    _rec_name = 'contractor_name' # ليظهر اسم المقاول كعنوان للسجل

    project_id = fields.Many2one('project.project', string="Project", required=True)
    
    # --- 1. بيانات المقاول (نصية كما طلبت) ---
    contractor_name = fields.Char(string="Contractor Name", required=True)
    contractor_email = fields.Char(string="Email")
    contractor_phone = fields.Char(string="Phone")
    
    # حقل اختياري لو حبيت تربطه بالسيستم لاحقاً (اختياري)
    partner_id = fields.Many2one('res.partner', string="Linked Partner")

    # --- 2. التوقيت (الإمارات) ---
    def _get_uae_now(self):
        tz = pytz.timezone('Asia/Dubai')
        return datetime.now(tz)

    submission_date = fields.Datetime(string="Submission Date", default=_get_uae_now)
    
    line_ids = fields.One2many('kh.boq.line', 'submission_id', string="Pricing Lines")
    total_amount = fields.Float(string="Total Bid Value", compute="_compute_total", store=True)

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(line.subtotal for line in rec.line_ids)

class BoqSubmissionLine(models.Model):
    _name = 'kh.boq.line'
    _description = 'Submission Line'

    submission_id = fields.Many2one('kh.boq.submission')
    plan_line_id = fields.Many2one('kh.project.boq.plan', string="Item Ref")
    
    # جلب البيانات من المخطط الأصلي تلقائياً
    section_name = fields.Char(related='plan_line_id.section_name', store=True)
    item_description = fields.Char(related='plan_line_id.item_description', store=True)
    uom_id = fields.Char(related='plan_line_id.uom_id', string="Unit", store=True)
    
    # --- 3. الكمية والمجموع ---
    # نجعل الكمية تأتي أوتوماتيكياً من السطر الأصلي
    quantity = fields.Float(related='plan_line_id.quantity', string="Qty", store=True)
    unit_price = fields.Float(string="Unit Price")
    
    subtotal = fields.Float(string="Subtotal", compute="_compute_subtotal", store=True)

    @api.depends('quantity', 'unit_price')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = rec.quantity * rec.unit_price