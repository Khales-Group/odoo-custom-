# -*- coding: utf-8 -*-
from odoo import fields, models


class ProjectSiteVisit(models.Model):
    _name = "project.site.visit"
    _description = "Project Site Visit"
    _order = "visit_date desc, id desc"
    _rec_name = "visit_date"

    project_id = fields.Many2one(
        "project.project", string="Project", required=True, ondelete="cascade", index=True
    )
    visit_date = fields.Date(string="Visit Date", required=True, default=fields.Date.context_today)
    note = fields.Text(string="Visit Note")


class ProjectProject(models.Model):
    _inherit = "project.project"

    visit_ids = fields.One2many("project.site.visit", "project_id", string="Site Visits")
    visit_count = fields.Integer(string="Site Visits Count", compute="_compute_visit_count")

    def _compute_visit_count(self):
        for rec in self:
            rec.visit_count = len(rec.visit_ids)
