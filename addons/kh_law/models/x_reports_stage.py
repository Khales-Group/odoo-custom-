from odoo import fields, models

DEPARTMENTS = [("Law", "Legal Affairs"), ("PRO", "PRO")]


class LawStage(models.Model):
    # Studio model taken over in code. Its Studio fields (x_name, ...) are not
    # redefined here and stay Studio-managed; only the new fields live here.
    _name = "x_reports_stage"
    _description = "Law Stage"
    _rec_name = "x_name"
    _order = "kh_sequence, id"
    _fold_name = "kh_fold"

    kh_department = fields.Selection(DEPARTMENTS, string="Department", default="Law", index=True)
    kh_sequence = fields.Integer(string="Sequence", default=10)
    kh_is_closed = fields.Boolean(
        string="Closing Stage",
        help="Files in this stage count as closed (used for durations, win rate and on-time KPIs).",
    )
    kh_fold = fields.Boolean(string="Folded in Kanban")
