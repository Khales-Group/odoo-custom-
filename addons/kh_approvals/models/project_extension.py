from odoo import models, fields


class Project(models.Model):
    _inherit = "project.project"

    contractor_email = fields.Char(
        string="Contractor Email",
        help="Official contractor email used for communication"
    )

    client_email = fields.Char(
        string="Client Official Email",
        help="Client official email used for communication"
    )

    email_ids = fields.One2many(
        "project.email",
        "project_id",
        string="Emails"
    )
