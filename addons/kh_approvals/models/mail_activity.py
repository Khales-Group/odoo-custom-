# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError

# Editing these fields counts as an edit of the activity
PROTECTED_FIELDS = {
    "user_id", "res_model", "res_id", "activity_type_id",
    "summary", "note", "date_deadline", "recommended_activity_type_id",
}

class MailActivity(models.Model):
    _inherit = "mail.activity"

    # Limit scope to our approvals model. Change to "return True" for global behavior.
    def _applies_to_kh_approval(self):
        self.ensure_one()
        return self.res_model == "kh.approval.request"

    def _assignee_not_creator(self):
        self.ensure_one()
        return self.user_id.id == self.env.uid and self.create_uid.id != self.env.uid

    # Block Cancel (unlink) for assignee≠creator, but allow when called from Mark Done
    def unlink(self):
        allow_done = self.env.context.get("allow_assignee_unlink_for_done")
        for act in self:
            if act._applies_to_kh_approval() and act._assignee_not_creator() and not allow_done:
                raise UserError(_("You can't cancel this activity because you didn't create it."))
        return super().unlink()

    # Block Edit for assignee≠creator
    def write(self, vals):
        if vals and (set(vals.keys()) & PROTECTED_FIELDS):
            for act in self:
                if act._applies_to_kh_approval() and act._assignee_not_creator():
                    raise UserError(_("You can't edit this activity because you didn't create it."))
        return super().write(vals)

    # Keep Mark Done working (super will unlink; we whitelist that via context)
    def action_feedback(self, feedback=False, attachment_ids=None, **kwargs):
        return super(MailActivity, self.with_context(
            allow_assignee_unlink_for_done=True
        )).action_feedback(feedback=feedback, attachment_ids=attachment_ids, **kwargs)
