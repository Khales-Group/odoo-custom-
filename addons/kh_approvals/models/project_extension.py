from odoo import models, fields, api

class Project(models.Model):
    _inherit = 'project.project'

    # Ensure this line is aligned with the _inherit line (usually 4 spaces)
    email_count = fields.Integer(compute='_compute_email_count', string="Email Count")

    def _compute_email_count(self):
        for project in self:
            # Your logic to count emails goes here
            # Example: project.email_count = self.env['mail.message'].search_count([...])
            project.email_count = 0