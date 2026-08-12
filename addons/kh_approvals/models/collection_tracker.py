# -*- coding: utf-8 -*-
from odoo import fields, models


class KhCollectionTracker(models.Model):
    _name = 'kh.collection.tracker'
    _description = 'متابعة التحصيل اليدوية (كشف المحاسب)'
    _order = 'recorded_date desc, id desc'
    _rec_name = 'company_name'

    company_name = fields.Char(string="الشركة/العميل (Company/Owner)", required=True)
    reference = fields.Char(string="المرجع/الوصف (Project/Reference)")
    project_id = fields.Many2one(
        'project.project', string="المشروع المرتبط بالنظام",
        help="لو تم التعرّف على مشروع حقيقي مطابق بـ Odoo - اختياري.")
    category = fields.Selection([
        ('project_payment', 'دفعة مشروع (Project Payment)'),
        ('design_fee', 'رسوم تصميم (Design Fee)'),
        ('supervision_fee', 'رسوم إشراف (Supervision Fee)'),
    ], string="التصنيف", default='project_payment', required=True)
    amount = fields.Float(string="المبلغ المستحق (Amount)")
    received_amount = fields.Float(string="المحصَّل (Received)")
    balance_amount = fields.Float(string="المتبقّي (Balance)")
    balance_note = fields.Char(
        string="ملاحظة على المتبقّي",
        help="لو القيمة بالكشف الأصلي نص غير رقمي (متل 'Old Pay' أو 'Dedcution') - اكتبها هون.")
    aging_status = fields.Char(string="الحالة/التوقيت المتوقع (Aging/Status)")
    recorded_date = fields.Date(string="تاريخ آخر تحديث بالكشف", default=fields.Date.context_today)
    source_note = fields.Char(string="المصدر", help="مثلاً: كشف المحاسب Excel بتاريخ 2026-08-10")
