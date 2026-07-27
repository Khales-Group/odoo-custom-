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

    def _register_hook(self):
        # Runs on every registry rebuild (module upgrade or server
        # restart), independent of any UI page loading. This exists so
        # the primary admin (id=2) can never be locked out of Settings by
        # this module's own project.task record rule - self-healing the
        # bypass flag doesn't depend on reaching the Users form that
        # normally sets it.
        super()._register_hook()
        admin = self.env["res.users"].sudo().browse(2)
        if admin.exists() and not admin.full_project_access:
            admin.write({"full_project_access": True})
