# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError

class MailActivity(models.Model):
    _inherit = 'mail.activity'

    # --- Config knobs ---
    # System parameter (optional): kh_approvals.activity_guard_exclude_models
    # Comma-separated model names to exclude from guard, e.g. "calendar.event,mail.channel"
    def _kh_guard_excluded_models(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'kh_approvals.activity_guard_exclude_models', ''
        ) or ''
        return {m.strip() for m in param.split(',') if m.strip()}

    def _kh_guard_enabled(self):
        # Allow explicit bypass from server code: with_context(kh_activity_guard_bypass=True)
        if self.env.context.get('kh_activity_guard_bypass'):
            return False
        return True

    def _kh_check_activity_permission(self):
        """
        Global guard (all apps, now and future):
        Only the assigned user, the creator, or Approvals Manager can complete / give feedback / delete activities.

        Safe exceptions:
          - SUPERUSER always allowed
          - Activities with no user assigned (user_id is False) -> anyone can’t complete; only creator/manager/superuser can
          - Models listed in system param 'kh_approvals.activity_guard_exclude_models' are ignored
        """
        if not self._kh_guard_enabled():
            return

        user = self.env.user
        if self.env.is_superuser():
            return
        is_manager = user.has_group('kh_approvals.group_kh_approvals_manager')
        if is_manager:
            return

        excluded = self._kh_guard_excluded_models()

        for act in self:
            # Skip excluded models
            if act.res_model in excluded:
                continue

            # An assignee who is NOT the creator is NOT allowed to modify/delete.
            # They can only mark as done or give feedback.
            if act.user_id and act.user_id.id == user.id and act.create_uid.id != user.id:
                raise UserError(_("As the assignee, you can mark this activity as done, but you cannot edit or delete it because you are not the creator."))

            # Allow if the user is the creator.
            if act.create_uid and act.create_uid.id == user.id:
                continue

            # Otherwise block
            raise UserError(_("Only the assigned user or the activity creator (or Approvals Manager) can complete or delete this activity."))

    # Guard all completion paths
    def action_done(self):
        self._kh_check_activity_permission()
        return super().action_done()

    def action_feedback(self, feedback=False, attachment_ids=None):
        self._kh_check_activity_permission()
        return super().action_feedback(feedback=feedback, attachment_ids=attachment_ids)

    def write(self, vals):
        # Catch status transitions done via write (e.g., state->done/cancel)
        if any(k in vals for k in ('res_model', 'res_id', 'user_id', 'summary', 'note', 'date_deadline')):
            self._kh_check_activity_permission()
        return super().write(vals)

    def unlink(self):
        self._kh_check_activity_permission()
        return super().unlink()
