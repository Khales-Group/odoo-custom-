from odoo import fields, models


class SignTemplate(models.Model):
    _inherit = "sign.template"

    project_id = fields.Many2one(
        "project.project",
        string="Project",
        index=True,
        help="Signature requests created from this document inherit this project by default.",
    )
