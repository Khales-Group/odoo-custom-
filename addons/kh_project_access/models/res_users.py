from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    full_project_access = fields.Boolean(
        string="Full Project Access",
        help="Bypasses the project restriction: sees every project and "
        "task company-wide, regardless of who manages or is assigned to "
        "them. Without this, a user only sees projects they manage or "
        "have a task assigned in - even with Project: Administrator "
        "access.",
    )
