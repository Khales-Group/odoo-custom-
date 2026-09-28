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
    _description = "Law / PRO Department"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Selection(DEPARTMENTS, required=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer()

    open_count = fields.Integer(string="Open", compute="_compute_stats")
    closed_count = fields.Integer(string="Closed", compute="_compute_stats")
    attention_count = fields.Integer(string="Need Attention", compute="_compute_stats")
    expiring_count = fields.Integer(string="Expiring in 30 Days", compute="_compute_stats")
    win_rate = fields.Float(string="Win Rate (%)", compute="_compute_stats", digits=(5, 1))
    on_time_rate = fields.Float(string="On Time (%)", compute="_compute_stats", digits=(5, 1))
    avg_duration = fields.Float(string="Avg. Duration (Days)", compute="_compute_stats", digits=(6, 1))
    fine_count = fields.Integer(string="Fines", compute="_compute_stats")

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

    def _kh_action(self, index):
        self.ensure_one()
        return self.env["ir.actions.actions"]._for_xml_id(ACTIONS[self.code][index])

    def action_open_records(self):
        return self._kh_action(0)

    def action_open_reports(self):
        return self._kh_action(1)
