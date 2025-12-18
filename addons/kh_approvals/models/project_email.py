from odoo import models, fields


class ProjectEmail(models.Model):
    _name = "project.email"
    _description = "Project Email"
    _order = "date desc"

    project_id = fields.Many2one(
        "project.project",
        ondelete="cascade",
        required=True
    )

    subject = fields.Char(readonly=True)
    email_from = fields.Char(string="From", readonly=True)
    email_to = fields.Char(string="To", readonly=True)
    date = fields.Datetime(readonly=True)

    preview = fields.Text(
        string="Preview",
        readonly=True,
        help="First 1–2 lines of the email"
    )

    body_html = fields.Html(
        string="Full Email Body",
        readonly=True,
        sanitize=True
    )

    attachment_ids = fields.Many2many(
        "ir.attachment",
        "project_email_attachment_rel",
        "email_id",
        "attachment_id",
        string="Attachments",
        readonly=True
    )

    # Add this field to store tags like [Main, Owner, Contractor]
    category_ids = fields.Many2many(
        "project.email.category",
        string="Categories"
    )
