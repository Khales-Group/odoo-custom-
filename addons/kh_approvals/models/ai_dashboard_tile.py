# -*- coding: utf-8 -*-
# ============================================================
#  بطاقات (Boxes) الشاشة الرئيسية لتطبيق "AI Project Manager" - كل بطاقة
#  بتفتح Action محدّد (List مفلترة + فورم مخصّص لموضوعها بس، مش كل التفاصيل).
# ============================================================
from odoo import fields, models


class KhAiDashboardTile(models.Model):
    _name = 'kh.ai.dashboard.tile'
    _description = 'AI Project Manager - بطاقات التنقّل'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    description = fields.Char()
    icon = fields.Char(default='💡')
    sequence = fields.Integer(default=10)
    action_xmlid = fields.Char(
        required=True, help="الـ xmlid الكامل تبع ir.actions.act_window يلي هذه البطاقة بتفتحه")

    def action_open(self):
        self.ensure_one()
        return self.env.ref(self.action_xmlid).read()[0]
