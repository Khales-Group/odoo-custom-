# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)

MAJID_ID = 369  # Majed - the manager


class ResUsers(models.Model):
    _inherit = "res.users"

    def _register_hook(self):
        # Runs on every registry rebuild, independent of any UI page loading -
        # keeps Majed and Karan in the Collection Access group even if it gets
        # cleared by accident, without relying on someone remembering to set
        # it manually after an install/upgrade.
        #
        # Wrapped defensively: this is a convenience, not a critical path -
        # it must never be able to take down registry loading for everyone.
        super()._register_hook()
        try:
            group = self.env.ref("kh_collection.group_kh_collection_user", raise_if_not_found=False)
            if not group:
                return
            majed = self.sudo().browse(MAJID_ID)
            karan = self.sudo().search([("name", "ilike", "karan")], limit=1)
            for user in (majed.exists() | karan):
                if group.id not in user.groups_id.ids:
                    user.write({"groups_id": [(4, group.id)]})
        except Exception:
            _logger.exception("kh_collection: could not ensure Collection Access group membership")
