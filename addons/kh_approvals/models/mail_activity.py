from odoo import models, api, _
from odoo.exceptions import UserError


class MailActivity(models.Model):
    _inherit = "mail.activity"

    state = fields.Char(
        string="State",
        compute='_compute_state',
        store=True,
    )

    @api.depends('active') # Assuming 'active' field indicates if it's done or not
    def _compute_state(self):
        for activity in self:
            activity.state = 'done' if not activity.active else 'open'

