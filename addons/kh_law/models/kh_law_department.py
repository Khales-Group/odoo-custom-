from datetime import timedelta

from odoo import fields, models

from .x_reports_stage import DEPARTMENTS

ACTIONS = {
    "Law": ("kh_law.action_x_reports_law", "kh_law.action_x_reports_law_analysis"),
    "PRO": ("kh_law.action_x_reports_pro", "kh_law.action_x_reports_pro_analysis"),
}


class LawDepartment(models.Model):
    """ Entry screen of the app: one card per department with its KPIs. """
    _name = "kh.law.department"
    _description = "قسم"
    _order = "sequence, id"

    name = fields.Char(string="الاسم", required=True, translate=True)
    code = fields.Selection(DEPARTMENTS, string="القسم", required=True)
    sequence = fields.Integer(string="الترتيب", default=10)
    color = fields.Integer(string="اللون")
    user_id = fields.Many2one(
        "res.users", string="الموظف المسؤول", domain=[("share", "=", False)],
        help="الموظف الذي يُقيَّم عن هذا القسم. إذا تُرك فارغاً، يُؤخذ المسؤول عن أكثر ملفات القسم.",
    )

    open_count = fields.Integer(string="مفتوحة", compute="_compute_stats")
    closed_count = fields.Integer(string="مغلقة", compute="_compute_stats")
    attention_count = fields.Integer(string="تحتاج متابعة", compute="_compute_stats")
    expiring_count = fields.Integer(string="تنتهي خلال 30 يوم", compute="_compute_stats")
    win_rate = fields.Float(string="نسبة الربح (%)", compute="_compute_stats", digits=(5, 1))
    on_time_rate = fields.Float(string="نسبة الإنجاز بالوقت (%)", compute="_compute_stats", digits=(5, 1))
    avg_duration = fields.Float(string="متوسط المدة (أيام)", compute="_compute_stats", digits=(6, 1))
    fine_count = fields.Integer(string="الغرامات", compute="_compute_stats")

    def _compute_stats(self):
        Report = self.env["x_reports"]
        today = fields.Date.context_today(self)
        for dept in self:
            base = [("x_studio_type", "=", dept.code)]
            dept.open_count = Report.search_count(base + [("kh_is_closed", "=", False)])
            closed = Report.search(base + [("kh_is_closed", "=", True)])
            dept.closed_count = len(closed)
            durations = closed.filtered("kh_close_date").mapped("kh_duration_days")
            dept.avg_duration = sum(durations) / len(durations) if durations else 0.0

            dept.win_rate = dept.on_time_rate = 0.0
            dept.fine_count = dept.expiring_count = 0
            if dept.code == "Law":
                decided = closed.filtered(lambda r: r.kh_case_outcome in ("won", "lost", "settled"))
                won = decided.filtered(lambda r: r.kh_case_outcome == "won")
                dept.win_rate = 100.0 * len(won) / len(decided) if decided else 0.0
                dept.attention_count = Report.search_count(base + [("kh_is_stale", "=", True)])
            else:
                timed = closed.filtered("kh_on_time")
                on_time = timed.filtered(lambda r: r.kh_on_time == "on_time")
                dept.on_time_rate = 100.0 * len(on_time) / len(timed) if timed else 0.0
                dept.attention_count = Report.search_count(base + [("kh_is_late", "=", True)])
                dept.expiring_count = Report.search_count(base + [
                    ("kh_is_closed", "=", False),
                    ("kh_expiry_date", "!=", False),
                    ("kh_expiry_date", "<=", today + timedelta(days=30)),
                ])
                dept.fine_count = sum(Report.search(base).mapped("kh_fine_count"))

    def _kh_employee(self):
        """ The employee evaluated for this department: the configured one,
        else the responsible of most of the department's files. """
        self.ensure_one()
        if self.user_id:
            return self.user_id
        groups = self.env["x_reports"]._read_group(
            [("x_studio_type", "=", self.code), ("x_studio_user_id", "!=", False)],
            ["x_studio_user_id"], ["__count"], order="__count desc", limit=1,
        )
        return groups[0][0] if groups else self.env["res.users"]

    def action_new_evaluation(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("kh_law.action_kh_law_evaluation")
        action.update({
            "views": [(False, "form")],
            "view_mode": "form",
            "context": {"default_department": self.code},
        })
        return action

    def _kh_action(self, index):
        self.ensure_one()
        return self.env["ir.actions.actions"]._for_xml_id(ACTIONS[self.code][index])

    def action_open_records(self):
        return self._kh_action(0)

    def action_open_reports(self):
        return self._kh_action(1)
