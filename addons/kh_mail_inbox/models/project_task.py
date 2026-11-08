from odoo import fields, models


class ProjectTask(models.Model):
    """A task made from a mailbox message on the dashboard. Closing it marks
    the message as followed up."""

    _inherit = "project.task"

    kh_mail_message_id = fields.Many2one(
        "kh.mail.message", string="Mailbox Message", readonly=True, copy=False,
        index="btree_not_null", ondelete="set null",
    )
    kh_mail_box_email = fields.Char(string="Mailbox", related="kh_mail_message_id.box_id.email", store=True)

    def write(self, vals):
        result = super().write(vals)
        if vals.get("state") == "1_done":
            messages = self.sudo().filtered("kh_mail_message_id").kh_mail_message_id
            messages.filtered(lambda m: not m.followed).write({"followed": True})
        return result
