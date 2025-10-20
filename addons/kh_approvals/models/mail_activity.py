# -*- coding: utf-8 -*-
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

    def _assignee_not_creator(self):
        self.ensure_one()
        return self.user_id.id == self.env.uid and self.create_uid.id != self.env.uid

    def unlink(self):
        allow_done = self.env.context.get("allow_assignee_unlink_for_done")
        for act in self:
            if act._applies_to_kh_approval() and act._assignee_not_creator() and not allow_done:
                raise UserError(_("You can't cancel this activity because you didn't create it."))
        return super().unlink()

    def write(self, vals):
        if vals and (set(vals.keys()) & PROTECTED_FIELDS):
            for act in self:
                if act._applies_to_kh_approval() and act._assignee_not_creator():
                    raise UserError(_("You can't edit this activity because you didn't create it."))
        return super().write(vals)

    def action_feedback(self, feedback=False, attachment_ids=None, **kwargs):
        self = self.with_context(allow_assignee_unlink_for_done=True)
        return super().action_feedback(feedback=feedback, attachment_ids=attachment_ids, **kwargs)
