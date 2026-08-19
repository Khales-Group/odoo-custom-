from odoo import api, fields, models


class SignRequest(models.Model):
    _inherit = "sign.request"

    project_id = fields.Many2one(
        "project.project",
        string="Project",
        index=True,
        tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("project_id") and vals.get("template_id"):
                template = self.env["sign.template"].browse(vals["template_id"])
                if template.project_id:
                    vals["project_id"] = template.project_id.id
        return super().create(vals_list)
