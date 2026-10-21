# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)

ADMIN_ID = 2
CEO_ID = 369  # Majed


class ResUsers(models.Model):
    _inherit = "res.users"

    def _register_hook(self):
        super()._register_hook()
        try:
            group = self.env.ref("kh_incentives.group_kh_incentives_manager", raise_if_not_found=False)
            if not group:
                return
            admin = self.sudo().browse(ADMIN_ID)
            ceo = self.sudo().browse(CEO_ID)
            for user in (admin.exists() | ceo.exists()):
                if group.id not in user.group_ids.ids:
                    user.write({"group_ids": [(4, group.id)]})
        except Exception:
            _logger.exception("kh_incentives: could not ensure Incentives Access group membership")
