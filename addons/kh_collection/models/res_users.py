# -*- coding: utf-8 -*-
from odoo import models

MAJID_ID = 369  # Majed - the manager


class ResUsers(models.Model):
    _inherit = "res.users"

    def _register_hook(self):
        # Runs on every registry rebuild, independent of any UI page loading -
        # keeps Majed and Karan in the Collection Access group even if it gets
        # cleared by accident, without relying on someone remembering to set
        # it manually after an install/upgrade.
        super()._register_hook()
        group = self.env.ref("kh_collection.group_kh_collection_user", raise_if_not_found=False)
        if not group:
            return
        majed = self.sudo().browse(MAJID_ID)
        karan = self.sudo().search([("name", "ilike", "karan")], limit=1)
        missing = (majed.exists() | karan) - group.users
        if missing:
            group.sudo().write({"users": [(4, user.id) for user in missing]})
