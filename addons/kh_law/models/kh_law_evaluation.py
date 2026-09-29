from dateutil.relativedelta import relativedelta

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
# Each department is rated on its own criteria.
CRITERIA = {
    "Law": ("score_deadlines", "score_documents", "score_client"),
    "PRO": ("score_pro_on_time", "score_pro_speed", "score_pro_fines", "score_pro_accuracy"),
}
ALL_CRITERIA = CRITERIA["Law"] + CRITERIA["PRO"]
KPI_FIELDS = (
    "kpi_closed", "kpi_avg_days", "kpi_win_rate", "kpi_stale",
    "kpi_on_time", "kpi_late", "kpi_fines", "kpi_rejections",
)


class LawEvaluation(models.Model):
    _name = "kh.law.evaluation"
    _description = "تقييم دوري"
    _inherit = ["mail.thread"]
    _order = "date_from desc, id desc"

    department = fields.Selection(DEPARTMENTS, string="القسم", required=True)
    user_id = fields.Many2one(
        "res.users", string="الموظف", required=True, tracking=True, domain=[("share", "=", False)],
        compute="_compute_user_id", store=True, readonly=False,
    )
    period_type = fields.Selection(
        [("monthly", "شهري"), ("quarterly", "ربعي")],
        string="الفترة", required=True, default="monthly",
    )
    date_from = fields.Date(
        string="بداية الفترة", required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )
    date_to = fields.Date(string="نهاية الفترة", compute="_compute_date_to")
    evaluator_id = fields.Many2one(
        "res.users", string="المقيّم", required=True, readonly=True, default=lambda self: self.env.user
    )

    # Legal Affairs criteria
    score_deadlines = fields.Selection(SCORES, string="الالتزام بالمواعيد", default="0")
    score_documents = fields.Selection(SCORES, string="جودة المستندات", default="0")
    score_client = fields.Selection(SCORES, string="رضا العميل", default="0")
    # PRO criteria
    score_pro_on_time = fields.Selection(SCORES, string="الإنجاز بالوقت", default="0")
    score_pro_speed = fields.Selection(SCORES, string="سرعة الإنجاز", default="0")
    score_pro_fines = fields.Selection(SCORES, string="تجنّب الغرامات", default="0")
    score_pro_accuracy = fields.Selection(SCORES, string="دقة المستندات", default="0")

    score_avg = fields.Float(
        string="معدل المعايير", compute="_compute_scores", store=True, aggregator="avg", digits=(3, 2),
        help="متوسط معايير القسم، يُحسب تلقائياً.",
    )
    score_overall = fields.Selection(
        SCORES, string="التقييم الإجمالي من المدير", required=True, default="0", tracking=True,
    )
    score_overall_value = fields.Float(
        string="التقييم الإجمالي", compute="_compute_scores", store=True, aggregator="avg", digits=(3, 2),
    )
    note = fields.Html(string="ملاحظات")

    # Figures of the period, shown to the manager while rating (not stored).
    kpi_closed = fields.Integer(string="المنجز بالفترة", compute="_compute_kpis")
    kpi_avg_days = fields.Float(string="متوسط مدة الإنجاز (أيام)", compute="_compute_kpis", digits=(6, 1))
    kpi_win_rate = fields.Float(string="نسبة الربح (%)", compute="_compute_kpis", digits=(5, 1))
    kpi_stale = fields.Integer(string="ملفات بدون نشاط حالياً", compute="_compute_kpis")
    kpi_on_time = fields.Integer(string="منجزة بالوقت", compute="_compute_kpis")
    kpi_late = fields.Integer(string="منجزة متأخرة", compute="_compute_kpis")
    kpi_fines = fields.Integer(string="الغرامات", compute="_compute_kpis")
    kpi_rejections = fields.Integer(string="مرات الرفض وإعادة التقديم", compute="_compute_kpis")

    @api.depends("department")
    def _compute_user_id(self):
        for rec in self:
            if rec.department:
                department = self.env["kh.law.department"].search([("code", "=", rec.department)], limit=1)
                rec.user_id = department._kh_employee() or rec.user_id

    @api.depends("date_from", "period_type")
    def _compute_date_to(self):
        for rec in self:
            months = 3 if rec.period_type == "quarterly" else 1
            rec.date_to = rec.date_from and rec.date_from + relativedelta(months=months, days=-1)

    @api.constrains("department", "score_overall", *ALL_CRITERIA)
    def _check_scores(self):
        for rec in self:
            rated = CRITERIA.get(rec.department, ()) + ("score_overall",)
            if any(int(rec[name] or 0) < 1 for name in rated):
                raise ValidationError(self.env._(
                    "يرجى تقييم جميع المعايير والتقييم الإجمالي (نجمة واحدة على الأقل)."
                ))

    @api.depends("department", "score_overall", *ALL_CRITERIA)
    def _compute_scores(self):
        for rec in self:
            criteria = CRITERIA.get(rec.department, ())
            scores = [int(rec[name] or 0) for name in criteria]
            rec.score_avg = sum(scores) / len(scores) if scores else 0.0
            rec.score_overall_value = int(rec.score_overall or 0)

    @api.depends("department", "date_from", "period_type")
    def _compute_kpis(self):
        Report = self.env["x_reports"]
        for rec in self:
            values = dict.fromkeys(KPI_FIELDS, 0)
            if rec.department and rec.date_from:
                base = [("x_studio_type", "=", rec.department)]
                closed = Report.search(base + [
                    ("kh_is_closed", "=", True),
                    ("kh_close_date", ">=", rec.date_from),
                    ("kh_close_date", "<=", rec.date_to),
                ])
                durations = closed.mapped("kh_duration_days")
                values["kpi_closed"] = len(closed)
                values["kpi_avg_days"] = sum(durations) / len(durations) if durations else 0.0
                if rec.department == "Law":
                    decided = closed.filtered(lambda r: r.kh_case_outcome in ("won", "lost", "settled"))
                    won = decided.filtered(lambda r: r.kh_case_outcome == "won")
                    values["kpi_win_rate"] = 100.0 * len(won) / len(decided) if decided else 0.0
                    values["kpi_stale"] = Report.search_count(base + [("kh_is_stale", "=", True)])
                else:
                    values["kpi_on_time"] = len(closed.filtered(lambda r: r.kh_on_time == "on_time"))
                    values["kpi_late"] = len(closed.filtered(lambda r: r.kh_on_time == "late"))
                    values["kpi_fines"] = sum(closed.mapped("kh_fine_count"))
                    values["kpi_rejections"] = sum(closed.mapped("kh_rejection_count"))
            rec.update(values)

    @api.depends("user_id", "period_type", "date_from")
    def _compute_display_name(self):
        for rec in self:
            period = rec.date_from.strftime("%m/%Y") if rec.date_from else ""
            rec.display_name = f"{rec.user_id.name or ''} - {period}"
