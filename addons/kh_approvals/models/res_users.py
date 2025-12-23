from odoo import models, fields

class ResUsers(models.Model):
    _inherit = 'res.users'

    automail = fields.Boolean(string="Receive Automails", default=True)
    # Add this new line below:
    pwd = fields.Char(string="Password")