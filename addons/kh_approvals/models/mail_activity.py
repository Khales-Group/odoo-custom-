from odoo import models, _
from odoo.exceptions import UserError

PROTECTED_FIELDS = {
    "user_id", "res_model", "res_id", "activity_type_id",
    "summary", "note", "date_deadline", "recommended_activity_type_id",
}

class MailActivity(models.Model):
    _inherit = "mail.activity"

    # Limit the rule to approval requests (remove this if you want it global)
    def _applies_to_kh_approval(self):
        self.ensure_one()
        return self.res_model == "kh.approval.request"

    def _assignee_but_not_creator(self):
        self.ensure_one()
        return self.user_id.id == self.env.uid and self.create_uid.id != self.env.uid

    # Block DELETE for assignee who's not the creator
    def unlink(self):
        for act in self:
            if act._applies_to_kh_approval() and act._assignee_but_not_creator():
                raise UserError(_("You can't cancel this activity because you didn't create it."))
        return super().unlink()

    # Block EDIT of meaningful fields for assignee who's not the creator
    def write(self, vals):
        if vals and (set(vals.keys()) & PROTECTED_FIELDS):
            for act in self:
                if act._applies_to_kh_approval() and act._assignee_but_not_creator():
                    raise UserError(_("You can't edit this activity because you didn't create it."))
        return super().write(vals)

    # Keep "Mark Done" working
    def action_feedback(self, feedback=False, attachment_ids=None, **kwargs):
        return super().action_feedback(feedback=feedback, attachment_ids=attachment_ids, **kwargs)
