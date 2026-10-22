# -*- coding: utf-8 -*-
from odoo import api, models

# Lead sources the sales team picks from on the dashboard cards. "Referral"
# ships with Odoo already; it's listed so it comes back if it was renamed.
KH_LEAD_SOURCES = ("WhatsApp", "Instagram", "Referral")


class UtmSource(models.Model):
    _inherit = "utm.source"

    @api.model
    def _kh_ensure_lead_sources(self):
        # Source names are unique (and Odoo silently renames a duplicate to
        # "Instagram [2]"), so only create the ones that aren't there yet,
        # whatever their capitalisation.
        for name in KH_LEAD_SOURCES:
            if not self.search([("name", "=ilike", name)], limit=1):
                self.create({"name": name})
