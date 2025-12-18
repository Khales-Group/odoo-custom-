from odoo import models, fields, api

# ==========================================
# 1. THE CATEGORY MODEL
# ==========================================
class ProjectEmailCategory(models.Model):
    _name = "project.email.category"
    _description = "Email Category"

    name = fields.Char(required=True)
    color = fields.Integer(string="Color Index")

# ==========================================
# 2. THE EMAIL MODEL (Where the 'folder' field belongs)
# ==========================================
class ProjectEmail(models.Model):
    _inherit = "project.email"

    # Tags for multiple labels
    category_ids = fields.Many2many(
        "project.email.category",
        string="Categories"
    )

    # The Field causing the crash (Now Safe)
    folder = fields.Selection([
        ('main', 'Main (Info)'),
        ('owner', 'Owner'),
        ('consultant', 'Consultant'),
        ('contractor', 'Contractor'),
        ('internal', 'Internal / Team')
    ], string="Folder", default='main', required=False) 

# ==========================================
# 3. THE PROJECT MODEL (Main App Extension)
# ==========================================
class Project(models.Model):
    _inherit = "project.project"

    contractor_email = fields.Char(string="Contractor Email")
    client_email = fields.Char(string="Client Official Email")
    
    # New fields for Logic
    x_studio_offical_email = fields.Char(string="Owner Email")
    x_studio_consultant_email = fields.Char(string="Consultant Email")
    x_studio_contractor_email = fields.Char(string="Contractor Email")
    x_studio_consultant = fields.Char(string="Consultant Name (Text)")
    
    email_ids = fields.One2many("project.email", "project_id", string="Emails")
    
    # Counter Logic
    email_count = fields.Integer(compute='_compute_email_count', string="Email Count")

    @api.depends('email_ids')
    def _compute_email_count(self):
        for record in self:
            record.email_count = len(record.email_ids)

    # Smart Button Action
    def action_open_project_emails(self):
        self.ensure_one()
        return {
            'name': 'Project Emails',
            'type': 'ir.actions.act_window',
            'res_model': 'project.email',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
            # Note: We rely on the XML default search view, not a specific ID
            'help': """
                <p class="o_view_nocontent_smiling_face">
                    No emails found.
                </p>
            """
        }