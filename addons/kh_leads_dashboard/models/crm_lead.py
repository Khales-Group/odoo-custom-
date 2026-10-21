# -*- coding: utf-8 -*-
from odoo import api, fields, models

STAGE_GROUP_MAP = {
    "New": "capture",
    "Hold List": "capture",
    "Qualified": "verify",
    "Meeting Scheduled": "verify",
    "Proposal": "offer",
    "Open File": "offer",
    "Pending Documents": "offer",
    "Contract": "contract_delivery",
    "Won": "contract_delivery",
    "Completed": "contract_delivery",
    "Canceled": "lost",
}


class CrmLead(models.Model):
    _inherit = "crm.lead"

    kh_stage_group = fields.Selection(
        [
            ("capture", "Capture"),
            ("verify", "Verify"),
            ("offer", "Offer"),
            ("contract_delivery", "Contract & Delivery"),
            ("lost", "Lost"),
        ],
        string="Pipeline Stage Group",
        compute="_compute_kh_stage_group",
        store=True,
    )

    @api.depends("stage_id")
    def _compute_kh_stage_group(self):
        for lead in self:
            lead.kh_stage_group = STAGE_GROUP_MAP.get(lead.stage_id.name, "capture")
