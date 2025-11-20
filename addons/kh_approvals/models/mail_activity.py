from odoo import models, api, _
from odoo.exceptions import UserError


class MailActivity(models.Model):
    _inherit = "mail.activity"

