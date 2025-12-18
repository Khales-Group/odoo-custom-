from odoo import models, fields

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