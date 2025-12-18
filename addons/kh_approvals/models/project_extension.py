# addons/kh_approvals/models/project_extension.py

from odoo import models, fields, api

class ProjectEmail(models.Model):
    _inherit = "project.email"

    # Keep your existing tags for advanced filtering
    category_ids = fields.Many2many("project.email.category", string="Tags")

    # ADD THIS FOR THE SIDEBAR UI
    folder = fields.Selection([
        ('main', 'Main (Info)'),
        ('owner', 'Owner'),
        ('consultant', 'Consultant'),
        ('contractor', 'Contractor'),
        ('internal', 'Internal / Team')
    ], string="Folder", default='main', required=True)

class ProjectEmailCategory(models.Model):
    _name = "project.email.category"
    _description = "Email Category (Owner, Contractor, etc)"

    name = fields.Char(required=True)
    color = fields.Integer(string="Color Index")

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
    
    # 1. Field to store the count (e.g., "5")
    email_count = fields.Integer(compute='_compute_email_count', string="Email Count")

    @api.depends('email_ids')
    def _compute_email_count(self):
        for record in self:
            record.email_count = len(record.email_ids)

    # 2. Action to open the view when button is clicked
    def action_open_project_emails(self):
        self.ensure_one()
        return {
            'name': 'Project Emails',
            'type': 'ir.actions.act_window',
            'res_model': 'project.email',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
            # I removed the 'search_view_id' line below.
            # Odoo will automatically find the search panel we defined in XML.
            'help': """
                <p class="o_view_nocontent_smiling_face">
                    No emails found.
                </p>
            """
        }
