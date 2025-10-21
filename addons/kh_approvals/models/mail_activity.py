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

    def _bypass_guard(self):
        """Allow superuser, Approvals Manager, or explicit context bypass."""
        return (
            self.env.su
            or self.env.user.has_group("kh_approvals.group_kh_approvals_manager")
            or self.env.context.get("kh_allow_activity_edit")
            or self.env.context.get("kh_from_mark_done")  # <- allow during Mark Done only
        )

    def _check_creator_guard_or_raise(self):
        for act in self:
            if act._applies_to_kh_approval() and not act._bypass_guard():
                if act.create_uid.id != self.env.uid:
                    raise UserError(
                        _("Only the user who created this activity can edit or cancel it.")
                    )

    # Cancel/Delete
    def unlink(self):
        self._check_creator_guard_or_raise()
        return super().unlink()

    # Edit (not Mark Done)
    def write(self, vals):
        if vals and (set(vals.keys()) & PROTECTED_FIELDS):
            self._check_creator_guard_or_raise()
        return super().write(vals)

    # Mark Done: allow, but only for this call path
    def action_feedback(self, feedback=False, attachment_ids=None, **kwargs):
        # Set a context flag so write()/unlink() during Mark Done are allowed.
        return super(
            MailActivity, self.with_context(kh_from_mark_done=True)
        ).action_feedback(feedback=feedback, attachment_ids=attachment_ids, **kwargs)
