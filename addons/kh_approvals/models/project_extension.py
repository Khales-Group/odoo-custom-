from odoo import models, fields

class ProjectProject(models.Model):
    _inherit = 'project.project'

    contractor_email = fields.Char(string="Contractor Email")
