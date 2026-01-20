from odoo import models, fields, api

class ProjectProject(models.Model):
    _inherit = 'project.project'

    contractor_email = fields.Char(string="Contractor Email")
    
    # New computed field to check permissions
    is_current_user_manager = fields.Boolean(compute='_compute_is_current_user_manager')

    @api.depends('user_id')
    def _compute_is_current_user_manager(self):
        for project in self:
            # Check if the Project Manager (user_id) matches the current logged-in user
            project.is_current_user_manager = project.user_id == self.env.user