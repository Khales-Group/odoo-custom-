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

    def _kh_check_activity_permission(self, for_write_or_unlink=False):
        """
        Global guard (all apps, now and future):
        Only the assigned user, the creator, or Approvals Manager can complete / give feedback / delete activities.

        Safe exceptions:
          - SUPERUSER always allowed
          - Activities with no user assigned (user_id is False) -> anyone can’t complete; only creator/manager/superuser can
          - Models listed in system param 'kh_approvals.activity_guard_exclude_models' are ignored

        :param for_write_or_unlink: If True, the check is stricter for assignees,
                                    preventing them from editing or deleting.
        """
        if not self._kh_guard_enabled():
            return

        user = self.env.user
        is_manager = user.has_group('kh_approvals.group_kh_approvals_manager')
        if is_manager:
            return

        excluded = self._kh_guard_excluded_models()

        for act in self:
            # Skip excluded models
            if act.res_model in excluded:
                continue

            is_assignee = act.user_id and act.user_id.id == user.id
            is_creator = act.create_uid and act.create_uid.id == user.id

            # A superuser who is also the creator should always be allowed to bypass further checks.
            # Otherwise, they must follow the same rules as others (e.g., being an assignee).
            if self.env.is_superuser() and is_creator:
                continue

            # If the check is for a write/unlink operation, an assignee who is not the
            # creator should be blocked.
            if for_write_or_unlink and is_assignee and not is_creator:
                raise UserError(_("As the assignee, you can only mark this activity as done or give feedback. You cannot edit or delete it."))

            # Allow if the user is the creator or the assignee.
            if is_creator or is_assignee:
                continue

            # Otherwise block
            raise UserError(_("Only the assigned user or the activity creator (or Approvals Manager) can complete or delete this activity."))

    # Guard all completion paths
    def action_done(self):
        self._kh_check_activity_permission(for_write_or_unlink=False)
        return super().action_done()

    def action_feedback(self, feedback=False, attachment_ids=None):
        self._kh_check_activity_permission(for_write_or_unlink=False)
        return super().action_feedback(feedback=feedback, attachment_ids=attachment_ids)

    def write(self, vals):
        # Catch status transitions done via write (e.g., state->done/cancel)
        if any(k in vals for k in ('res_model', 'res_id', 'user_id', 'summary', 'note', 'date_deadline')):
            self._kh_check_activity_permission(for_write_or_unlink=True)
        return super().write(vals)

    def unlink(self):
        self._kh_check_activity_permission(for_write_or_unlink=True)
        return super().unlink()
