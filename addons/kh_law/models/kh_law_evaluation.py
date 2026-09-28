from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .x_reports_stage import DEPARTMENTS

SCORE_FIELDS = ("score_deadlines", "score_documents", "score_client")


class LawEvaluation(models.Model):
    _name = "kh.law.evaluation"
    _description = "Periodic Evaluation"
    _inherit = ["mail.thread"]
    _order = "date_from desc, id desc"

    user_id = fields.Many2one(
        "res.users", string="Employee", required=True, tracking=True, domain=[("share", "=", False)]
    )
    department = fields.Selection(DEPARTMENTS, string="Department", required=True, default="Law")
    period_type = fields.Selection(
        [("monthly", "Monthly"), ("quarterly", "Quarterly")],
        string="Period", required=True, default="monthly",
    )
    date_from = fields.Date(
        string="Period Start", required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )
    evaluator_id = fields.Many2one(
        "res.users", string="Evaluated By", required=True, readonly=True, default=lambda self: self.env.user
    )
    score_deadlines = fields.Integer(string="Meeting Deadlines", required=True, default=3, help="1 (poor) to 5 (excellent)")
    score_documents = fields.Integer(string="Document Quality", required=True, default=3, help="1 (poor) to 5 (excellent)")
    score_client = fields.Integer(string="Client Satisfaction", required=True, default=3, help="1 (poor) to 5 (excellent)")
    score_avg = fields.Float(
        string="Overall Score", compute="_compute_score_avg", store=True, aggregator="avg", digits=(3, 2)
    )
    note = fields.Html(string="Comments")

    @api.constrains(*SCORE_FIELDS)
    def _check_scores(self):
        for rec in self:
            if any(not 1 <= rec[name] <= 5 for name in SCORE_FIELDS):
                raise ValidationError(self.env._("Scores must be between 1 and 5."))

    @api.depends(*SCORE_FIELDS)
    def _compute_score_avg(self):
        for rec in self:
            rec.score_avg = sum(rec[name] for name in SCORE_FIELDS) / len(SCORE_FIELDS)

    @api.depends("user_id", "period_type", "date_from")
    def _compute_display_name(self):
        for rec in self:
            period = rec.date_from.strftime("%m/%Y") if rec.date_from else ""
            rec.display_name = f"{rec.user_id.name or ''} - {period}"
