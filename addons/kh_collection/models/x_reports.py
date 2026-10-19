# -*- coding: utf-8 -*-
from odoo import fields, models


class XReports(models.Model):
    _inherit = "x_reports"

    kh_collection_case_id = fields.Many2one(
        "kh.collection.case", string="Collection Case", readonly=True, copy=False
    )

    def action_view_collection_case(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "kh.collection.case",
            "res_id": self.kh_collection_case_id.id,
            "view_mode": "form",
            "target": "current",
        }
