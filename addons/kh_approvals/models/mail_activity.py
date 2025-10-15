from odoo import models, _
from odoo.exceptions import UserError

PROTECTED_FIELDS = {
    "user_id", "res_model", "res_id", "activity_type_id",
    "summary", "note", "date_deadline", "recommended_activity_type_id",
}

class MailActivity(models.Model):
    _inherit = "mail.activity"

    def _applies_to_kh_approval(self):
        self.ensure_one()
        return self.res_model == "kh.approval.request"

    def unlink(self):
        for act in self:
            if act._applies_to_kh_approval() and act.user_id.id == self.env.uid:
                raise UserError(_("You are the assignee of this activity. You cannot cancel/delete it."))
        return super().unlink()

    def write(self, vals):
        if vals and (set(vals.keys()) & PROTECTED_FIELDS):
            for act in self:
                if act._applies_to_kh_approval() and act.user_id.id == self.env.uid:
                    raise UserError(_("You are the assignee of this activity. You cannot edit it; please ask the creator or a manager."))
        return super().write(vals)

    def action_feedback(self, feedback=False, attachment_ids=None, **kwargs):
        return super().action_feedback(feedback=feedback, attachment_ids=attachment_ids, **kwargs)
