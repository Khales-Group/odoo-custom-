from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .x_reports_stage import DEPARTMENTS

# Star ratings: "0" is the empty state of the stars widget (not rated yet).
SCORES = [
    ("0", "بدون تقييم"),
    ("1", "ضعيف"),
    ("2", "مقبول"),
    ("3", "جيد"),
    ("4", "جيد جداً"),
    ("5", "ممتاز"),
]
CRITERIA_FIELDS = ("score_deadlines", "score_documents", "score_client")
RATED_FIELDS = CRITERIA_FIELDS + ("score_overall",)


class LawEvaluation(models.Model):
    _name = "kh.law.evaluation"
    _description = "تقييم دوري"
    _inherit = ["mail.thread"]
    _order = "date_from desc, id desc"

    user_id = fields.Many2one(
        "res.users", string="الموظف", required=True, tracking=True, domain=[("share", "=", False)]
    )
    department = fields.Selection(DEPARTMENTS, string="القسم", required=True, default="Law")
    period_type = fields.Selection(
        [("monthly", "شهري"), ("quarterly", "ربعي")],
        string="الفترة", required=True, default="monthly",
    )
    date_from = fields.Date(
        string="بداية الفترة", required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )
    evaluator_id = fields.Many2one(
        "res.users", string="المقيّم", required=True, readonly=True, default=lambda self: self.env.user
    )
    score_deadlines = fields.Selection(SCORES, string="الالتزام بالمواعيد", required=True, default="0")
    score_documents = fields.Selection(SCORES, string="جودة المستندات", required=True, default="0")
    score_client = fields.Selection(SCORES, string="رضا العميل", required=True, default="0")
    score_avg = fields.Float(
        string="معدل المعايير", compute="_compute_scores", store=True, aggregator="avg", digits=(3, 2),
        help="متوسط المعايير الثلاثة، يُحسب تلقائياً.",
    )
    score_overall = fields.Selection(
        SCORES, string="التقييم الإجمالي من المدير", required=True, default="0", tracking=True,
    )
    score_overall_value = fields.Float(
        string="التقييم الإجمالي", compute="_compute_scores", store=True, aggregator="avg", digits=(3, 2),
    )
    note = fields.Html(string="ملاحظات")

    @api.constrains(*RATED_FIELDS)
    def _check_scores(self):
        for rec in self:
            if any(int(rec[name] or 0) < 1 for name in RATED_FIELDS):
                raise ValidationError(self.env._(
                    "يرجى تقييم جميع المعايير والتقييم الإجمالي (نجمة واحدة على الأقل)."
                ))

    @api.depends(*RATED_FIELDS)
    def _compute_scores(self):
        for rec in self:
            rec.score_avg = sum(int(rec[name] or 0) for name in CRITERIA_FIELDS) / len(CRITERIA_FIELDS)
            rec.score_overall_value = int(rec.score_overall or 0)

    @api.depends("user_id", "period_type", "date_from")
    def _compute_display_name(self):
        for rec in self:
            period = rec.date_from.strftime("%m/%Y") if rec.date_from else ""
            rec.display_name = f"{rec.user_id.name or ''} - {period}"
