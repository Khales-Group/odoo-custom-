from odoo import fields, models


class SignUploadWizard(models.TransientModel):
    _name = "kh.sign.upload.wizard"
    _description = "Upload Document for Signature"

    name = fields.Char(required=True, string="Document Name")
    attachment = fields.Binary(required=True, string="PDF Document")
    attachment_filename = fields.Char(string="Filename")
    project_id = fields.Many2one("project.project", string="Project")

    def action_upload(self):
        self.ensure_one()
        attachment = self.env["ir.attachment"].create({
            "name": self.attachment_filename or self.name,
            "datas": self.attachment,
            "res_model": "sign.template",
            "mimetype": "application/pdf",
        })
        template = self.env["sign.template"].create({
            "name": self.name,
            "attachment_id": attachment.id,
            "project_id": self.project_id.id,
        })
        attachment.write({"res_id": template.id})
        return {
            "type": "ir.actions.act_window",
            "res_model": "sign.template",
            "res_id": template.id,
            "view_mode": "form",
            "target": "current",
        }
