# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.tools import float_is_zero


class KhCollectionCase(models.Model):
    _inherit = "kh.collection.case"

    bonus_ids = fields.One2many("kh.incentive.claim", "collection_case_id", string="Bonuses")

    def write(self, vals):
        # Every time the collected amount goes up, whoever holds the case at
        # that moment (accountant / PRO / lawyer) gets a collection bonus on
        # the new money. Also fires when the PRO/lawyer updates the amount
        # on their Law & PRO file (it's synced back here). A correction down
        # gives a negative bonus, so the totals stay right.
        if "received_amount" not in vals:
            return super().write(vals)
        before = {
            rec.id: (rec.received_amount, rec.handler_role, rec.handler_id)
            for rec in self
        }
        res = super().write(vals)
        bonus_vals = []
        for rec in self:
            old_amount, role, user = before[rec.id]
            delta = rec.received_amount - old_amount
            if float_is_zero(delta, precision_digits=2) or not user:
                continue
            bonus_vals.append({
                "employee_id": user.id,
                "collection_role": role,
                "collection_case_id": rec.id,
                "project_id": rec.project_id.id,
                "amount_collected": delta,
                "currency_id": rec.currency_id.id,
                "note": _("Created automatically: %(amount)s collected on %(case)s.",
                          amount=delta, case=rec.name),
            })
        if bonus_vals:
            self.env["kh.incentive.claim"]._create_collection_bonuses(bonus_vals)
        return res
