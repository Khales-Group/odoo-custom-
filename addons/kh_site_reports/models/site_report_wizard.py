import calendar
import datetime

from odoo import _, fields, models

MONTH_SELECTION = [
    (str(i), name)
    for i, name in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        start=1,
    )
]

MONTH_NAMES_AR = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]

LANGUAGE_SELECTION = [("en", "English"), ("ar", "العربية (Arabic)")]


class SiteReportWizard(models.TransientModel):
    _name = "kh.site.report.wizard"
    _description = "Generate Monthly Site Report"

    project_id = fields.Many2one("project.project", required=True)
    month = fields.Selection(
        MONTH_SELECTION, required=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    year = fields.Integer(required=True, default=lambda self: fields.Date.context_today(self).year)
    language = fields.Selection(LANGUAGE_SELECTION, required=True, default="en", string="Report Language")

    def action_generate(self):
        self.ensure_one()
        month = int(self.month)
        last_day = calendar.monthrange(self.year, month)[1]
        period_start = datetime.date(self.year, month, 1)
        period_end = datetime.date(self.year, month, last_day)
        if self.language == "ar":
            period_label = f"{MONTH_NAMES_AR[month - 1]} {self.year}"
        else:
            period_label = f"{dict(MONTH_SELECTION)[self.month]} {self.year}"

        self.project_id.action_generate_site_report(period_start, period_end, period_label, self.language)
        return {"type": "ir.actions.act_window_close"}
