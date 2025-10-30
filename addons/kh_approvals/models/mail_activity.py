from odoo import models, api, _
from odoo.exceptions import UserError

class MailActivity(models.Model):
    _inherit = "mail.activity"

    # --- Config knobs from mail_activity_guard.py ---
    def _kh_guard_excluded_models(self):
        """Models to exclude from the global activity guard."""
        param = self.env['ir.config_parameter'].sudo().get_param(
            'kh_approvals.activity_guard_exclude_models', ''
        ) or ''
        return {m.strip() for m in param.split(',') if m.strip()}

    def _kh_guard_is_bypassed(self):
        """Check for various bypass conditions."""
        # Allow explicit bypass from server code: with_context(kh_activity_guard_bypass=True)
        if self.env.context.get('kh_activity_guard_bypass'):
            return True
        if self.env.is_superuser():
            return True
        if self.env.user.has_group('kh_approvals.group_kh_approvals_manager'):
            return True

    def _kh_check_activity_permission(self):
        """
        Global Guard: Only the assigned user or creator can complete/edit/delete.
        Managers and superusers are always allowed.
        Some models can be excluded via system parameter.
        """
        if self._kh_guard_is_bypassed():
            return

        user = self.env.user
        excluded_models = self._kh_guard_excluded_models()

        for act in self:
            # Skip excluded models
            if act.res_model in excluded_models:
                continue

            # Allow if current user is the assignee or the creator
            if act.user_id and act.user_id.id == user.id:
                continue
            if act.create_uid and act.create_uid.id == user.id:
                continue

            # If none of the above, block the operation
            raise UserError(_("Only the assigned user, the activity creator, or an Approvals Manager can modify or delete this activity."))

    # --- ORM Overrides to apply the guard ---

    def unlink(self):
        self._kh_check_activity_permission()
        return super().unlink()

    def write(self, vals):
        # Guard against unauthorized changes to key fields or state.
        if any(k in vals for k in ('state', 'res_model', 'res_id', 'user_id')):
            self._kh_check_activity_permission()
        return super().write(vals)

    def action_done(self):
        self._kh_check_activity_permission()
        return super().action_done()

    def action_feedback(self, feedback=False, attachment_ids=None):
        self._kh_check_activity_permission()
        return super().action_feedback(feedback=feedback, attachment_ids=attachment_ids)
