from odoo import models, fields

class ResUsers(models.Model):
    _inherit = 'res.users'

    # Define the missing field so the database knows it exists
    automail = fields.Boolean(string="Receive Automails", default=True)