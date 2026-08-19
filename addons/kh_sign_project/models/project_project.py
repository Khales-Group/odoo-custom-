from odoo import _, fields, models


class Project(models.Model):
    _inherit = "project.project"

    sign_request_ids = fields.One2many("sign.request", "project_id", string="Signature Requests")
    sign_template_ids = fields.One2many("sign.template", "project_id", string="Sign Documents")
    sign_request_count = fields.Integer(compute="_compute_sign_request_count")

    def _compute_sign_request_count(self):
        for project in self:
            project.sign_request_count = self.env["sign.request"].search_count(
                [("project_id", "=", project.id)]
            )

    def action_view_sign_requests(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Signature Requests"),
            "res_model": "sign.request",
            "view_mode": "kanban,list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }

    def action_new_sign_document(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Upload Document for Signature"),
            "res_model": "kh.sign.upload.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_project_id": self.id},
        }
