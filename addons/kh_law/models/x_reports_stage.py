from odoo import fields, models

DEPARTMENTS = [("Law", "الشؤون القانونية"), ("PRO", "العلاقات العامة")]


class LawStage(models.Model):
    # Studio model taken over in code. Its Studio fields (x_name, ...) are not
    # redefined here and stay Studio-managed; only the new fields live here.
    _name = "x_reports_stage"
    _description = "مرحلة"
    _rec_name = "x_name"
    _order = "kh_sequence, id"
    _fold_name = "kh_fold"

    kh_department = fields.Selection(DEPARTMENTS, string="القسم", default="Law", index=True)
    kh_sequence = fields.Integer(string="الترتيب", default=10)
    kh_is_closed = fields.Boolean(
        string="مرحلة إغلاق",
        help="الملفات في هذه المرحلة تعتبر مغلقة (تُستخدم لحساب المدة ونسبة الربح والإنجاز بالوقت).",
    )
    kh_fold = fields.Boolean(string="مطوية في الكانبان")
