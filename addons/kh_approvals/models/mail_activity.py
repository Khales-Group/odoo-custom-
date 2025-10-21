# addons/kh_approvals/models/mail_activity.py
from odoo import models, _
from odoo.exceptions import UserError

PROTECTED_FIELDS = {
    "user_id", "res_model", "res_id", "activity_type_id",
    "summary", "note", "date_deadline", "recommended_activity_type_id",
}

class MailActivity(models.Model):
    _inherit = "mail.activity"

    # applies only to activities on our approval requests
    def _applies_to_kh_approval(self):
        self.ensure_one()
        return self.res_model == "kh.approval.request"

    def _bypass_guard(self):
        """Allow superuser, Approvals Manager group, or explicit context bypass."""
        return (
            self.env.su
            or self.env.user.has_group("kh_approvals.group_kh_approvals_manager")
            or self.env.context.get("kh_allow_activity_edit")
        )

    def _check_creator_guard_or_raise(self):
        """Only the creator of the activity is allowed to edit/cancel it."""
        for act in self:
            if act._applies_to_kh_approval() and not act._bypass_guard():
                if act.create_uid.id != self.env.uid:
                    raise UserError(
                        _("Only the user who created this activity can edit or cancel it.")
                    )

    # --- Delete (Cancel) ---
    def unlink(self):
        self._check_creator_guard_or_raise()
        return super().unlink()

    # --- Edit fields (but not 'Mark Done') ---
    def write(self, vals):
        if vals and (set(vals.keys()) & PROTECTED_FIELDS):
            self._check_creator_guard_or_raise()
        return super().write(vals)

    # --- Mark Done is allowed for the assignee as usual ---
    def action_feedback(self, feedback=False, attachment_ids=None, **kwargs):
        return super().action_feedback(feedback=feedback, attachment_ids=attachment_ids, **kwargs)
