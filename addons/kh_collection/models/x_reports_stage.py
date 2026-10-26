# -*- coding: utf-8 -*-
from odoo import api, fields, models

from odoo.addons.kh_law.hooks import _set_name
from odoo.addons.kh_law.models.x_reports_stage import DEPARTMENTS

COLLECTION_STAGE_NAME = "تحصيل"


class XReportsStage(models.Model):
    _inherit = "x_reports_stage"

    kh_is_collection = fields.Boolean(
        string="مرحلة التحصيل",
        help="Files opened from the Collection app land in this stage of their department "
             "(PRO, and again in Law when the case is escalated to the lawyer).",
    )

    @api.model
    def _kh_ensure_collection_stages(self):
        # One "Collection" stage per department, shown first on the board.
        # Runs on every install/upgrade; only creates what's missing.
        langs = sorted({code for code, _name in self.env["res.lang"].get_installed()} | {"en_US"})
        Stage = self.with_context(active_test=False)
        for department, _label in DEPARTMENTS:
            if Stage.search_count([("kh_department", "=", department), ("kh_is_collection", "=", True)]):
                continue
            stage = Stage.create({
                "x_name": COLLECTION_STAGE_NAME,
                "kh_department": department,
                "kh_sequence": 1,
                "kh_is_collection": True,
            })
            _set_name(stage, COLLECTION_STAGE_NAME, langs)
