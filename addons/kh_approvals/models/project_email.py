from odoo import models, fields, api

# 1. Define Category Model Here (So it exists before we link to it)
class ProjectEmailCategory(models.Model):
    _name = "project.email.category"
    _description = "Email Category"
    name = fields.Char(required=True)
    color = fields.Integer(string="Color Index")

# 2. Define Project Email Model with ALL fields
class ProjectEmail(models.Model):
    _name = "project.email"
    _description = "Project Email"
    _order = "date desc"

    project_id = fields.Many2one("project.project", ondelete="cascade", required=True)
    
    subject = fields.Char(readonly=True)
    email_from = fields.Char(string="From", readonly=True)
    email_to = fields.Char(string="To", readonly=True)
    date = fields.Datetime(readonly=True)
    
    preview = fields.Text(string="Preview", readonly=True)
    body_html = fields.Html(string="Full Email Body", readonly=True, sanitize=True)
    
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments", readonly=True)

    # --- NEW FIELDS FOR UI ---
    # Many2many for tags
    category_ids = fields.Many2many("project.email.category", string="Categories")

    # Selection for the Sidebar (This prevents the Invalid Operation error)
    folder = fields.Selection([
        ('main', 'Main (Info)'),
        ('owner', 'Owner'),
        ('consultant', 'Consultant'),
        ('contractor', 'Contractor'),
        ('internal', 'Internal / Team')
    ], string="Folder", default='main')

# 3. PROJECT MODEL
class Project(models.Model):
    _inherit = "project.project"

    contractor_email = fields.Char(string="Contractor Email")
    client_email = fields.Char(string="Client Official Email")
    
    # === CRITICAL FIELDS ===
    # These must be here to fix the "Column does not exist" error
    x_studio_offical_email = fields.Char(string="Owner Email") # Note the spelling matches your error
    x_studio_consultant_email = fields.Char(string="Consultant Email")
    x_studio_contractor_email = fields.Char(string="Contractor Email")
    x_studio_consultant = fields.Char(string="Consultant Name")
    # =======================

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