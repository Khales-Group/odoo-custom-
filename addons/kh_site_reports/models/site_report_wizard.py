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


class SiteReportWizard(models.TransientModel):
    _name = "kh.site.report.wizard"
    _description = "Generate Monthly Site Report"

    project_id = fields.Many2one("project.project", required=True)
    month = fields.Selection(
        MONTH_SELECTION, required=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    year = fields.Integer(required=True, default=lambda self: fields.Date.context_today(self).year)

    def action_generate(self):
        self.ensure_one()
        month = int(self.month)
        last_day = calendar.monthrange(self.year, month)[1]
        period_start = datetime.date(self.year, month, 1)
        period_end = datetime.date(self.year, month, last_day)
        period_label = f"{dict(MONTH_SELECTION)[self.month]} {self.year}"

        self.project_id.action_generate_site_report(period_start, period_end, period_label)
        return {"type": "ir.actions.act_window_close"}
