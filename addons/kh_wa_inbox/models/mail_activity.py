from odoo import models


class MailActivity(models.Model):
    """The decision maker marking an item's «بانتظار قرارك» To-Do done ends
    the item's wait for his decision."""

    _inherit = "mail.activity"

    def _action_done(self, feedback=False, attachment_ids=None):
        items = self.env["kh.wa.item"].sudo().search([("kh_decision_activity_id", "in", self.ids)])
        result = super()._action_done(feedback=feedback, attachment_ids=attachment_ids)
        if items:
            items._kh_decision_done()
        return result
