# -*- coding: utf-8 -*-
from odoo import api, fields, models

# The only sources the sales team picks from on a lead. "Facebook" and
# "Referral" ship with Odoo; the others are created if missing.
KH_LEAD_SOURCES = ("Instagram", "Facebook", "WhatsApp", "Referral", "Direct Call")


class UtmSource(models.Model):
    _inherit = "utm.source"

    kh_lead_source = fields.Boolean(
        string="Offered on Leads",
        help="Shown in the Source list of leads/opportunities. Other sources stay "
             "on the leads that already use them, but can't be picked anymore.",
    )

    @api.model
    def _kh_ensure_lead_sources(self):
        # Source names are unique (and Odoo silently renames a duplicate to
        # "Instagram [2]"), so reuse an existing one whatever its
        # capitalisation and only create what's missing. Nothing is deleted:
        # old sources are still referenced by leads and mailings.
        offered = self.browse()
        for name in KH_LEAD_SOURCES:
            source = self.search([("name", "=ilike", name)], limit=1) or self.create({"name": name})
            offered |= source
        offered.kh_lead_source = True
        self.search([("kh_lead_source", "=", True), ("id", "not in", offered.ids)]).kh_lead_source = False
