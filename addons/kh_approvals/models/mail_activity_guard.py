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
        Only the assigned user or an Approvals Manager can complete, give feedback, edit, or delete activities.

        Safe exceptions:
          - SUPERUSER always allowed
          - Activities with no user assigned are blocked for everyone except managers.
          - Models listed in system param 'kh_approvals.activity_guard_exclude_models' are ignored.
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
            if act.res_model in excluded:
                continue

            # If an activity has an assigned user, only that user can interact with it.
            if act.user_id:
                if act.user_id.id != user.id:
                    raise UserError(_("Only the assigned user, or an Approvals Manager, can modify or complete this activity."))
            # If no user is assigned, block the action.
            else:
                raise UserError(_("This activity is not assigned to anyone and cannot be modified, except by an Approvals Manager."))

    # Guard all completion paths
    def action_done(self):
        self._kh_check_activity_permission()
        return super().action_done()

    def action_feedback(self, feedback=False, attachment_ids=None):
        self._kh_check_activity_permission()
        return super().action_feedback(feedback=feedback, attachment_ids=attachment_ids)

    def write(self, vals):
        # We need to check permissions before any modification.
        # The original check was too specific and missed cases.
        # This broader check ensures any attempt to write is guarded.
        if self:
            self._kh_check_activity_permission()
        return super().write(vals)

    def unlink(self):
        self._kh_check_activity_permission()
        return super().unlink()