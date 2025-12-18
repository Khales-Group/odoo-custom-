from odoo import models, fields, api

class ProjectEmailCategory(models.Model):
    _name = "project.email.category"
    _description = "Email Category"

    name = fields.Char(required=True)
    color = fields.Integer(string="Color Index")

class ProjectEmail(models.Model):
    _inherit = "project.email"

    # Tags for multiple labels
    category_ids = fields.Many2many("project.email.category", string="Categories")

    # CRITICAL: This field MUST exist for the sidebar to work
    folder = fields.Selection([
        ('main', 'Main (Info)'),
        ('owner', 'Owner'),
        ('consultant', 'Consultant'),
        ('contractor', 'Contractor'),
        ('internal', 'Internal / Team')
    ], string="Folder", default='main')

class Project(models.Model):
    _inherit = "project.project"

    contractor_email = fields.Char(string="Contractor Email")
    client_email = fields.Char(string="Client Official Email")
    x_studio_offical_email = fields.Char(string="Owner Email")
    x_studio_consultant_email = fields.Char(string="Consultant Email")
    x_studio_contractor_email = fields.Char(string="Contractor Email")
    x_studio_consultant = fields.Char(string="Consultant Name")

    email_ids = fields.One2many("project.email", "project_id", string="Emails")
    
    email_count = fields.Integer(compute='_compute_email_count', string="Email Count")

    @api.depends('email_ids')
    def _compute_email_count(self):
        for record in self:
            record.email_count = len(record.email_ids)

    def action_open_project_emails(self):
        self.ensure_one()
        return {
            'name': 'Project Emails',
            'type': 'ir.actions.act_window',
            'res_model': 'project.email',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
            'help': '&lt;p class="o_view_nocontent_smiling_face"&gt;No emails found.&lt;/p&gt;'
        }