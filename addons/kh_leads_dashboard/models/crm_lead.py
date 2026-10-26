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

    # Only the sales team's own sources can be picked (Instagram, Facebook,
    # WhatsApp, Referral, Direct Call - see utm_source.py) in the lead form.
    # The dashboard itself shows the Studio field x_studio_source instead.
    source_id = fields.Many2one(domain="[('kh_lead_source', '=', True)]")

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

    kh_last_activity_date = fields.Datetime(
        string="Last Update", compute="_compute_kh_last_activity_date"
    )

    @api.depends("stage_id")
    def _compute_kh_stage_group(self):
        for lead in self:
            lead.kh_stage_group = STAGE_GROUP_MAP.get(lead.stage_id.name, "capture")

    def _compute_kh_last_activity_date(self):
        # "Last update" = whichever is more recent: the lead's own last
        # write, or the last chatter entry on it (note, logged call, email) -
        # a chatter post alone doesn't bump write_date in standard Odoo.
        last_message_by_lead = {}
        if self.ids:
            last_message_by_lead = dict(self.env["mail.message"].sudo()._read_group(
                [("model", "=", "crm.lead"), ("res_id", "in", self.ids)],
                ["res_id"], ["date:max"],
            ))
        for lead in self:
            candidates = [lead.write_date, last_message_by_lead.get(lead.id)]
            candidates = [d for d in candidates if d]
            lead.kh_last_activity_date = max(candidates) if candidates else lead.write_date
