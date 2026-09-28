from odoo import fields, models


class LawDocument(models.Model):
    _name = "kh.law.document"
    _description = "مستند مطلوب"
    _order = "sequence, id"

    report_id = fields.Many2one("x_reports", string="الملف", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(string="الترتيب", default=10)
    name = fields.Char(string="المستند", required=True)
    kh_is_received = fields.Boolean(string="مستلم")
    kh_note = fields.Char(string="ملاحظة")
