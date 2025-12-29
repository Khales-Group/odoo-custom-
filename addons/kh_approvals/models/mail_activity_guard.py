# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError

class MailActivity(models.Model):
    _inherit = 'mail.activity'

    # --- Config knobs ---
    def _kh_guard_excluded_models(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'kh_approvals.activity_guard_exclude_models', ''
        ) or ''
        return {m.strip() for m in param.split(',') if m.strip()}

    def _kh_guard_enabled(self):
        return True

    def _kh_check_permission(self, action):
        """
        Guard for activity actions.
        """
        if not self._kh_guard_enabled():
            return

        user = self.env.user
        if self.env.is_superuser():
            return

        excluded = self._kh_guard_excluded_models()

        for act in self:
            if act.res_model in excluded:
                continue
            
            # 1. ALLOW SYSTEM WRITES IF MARKING DONE
            if action == 'write' and self.env.context.get('activity_mark_as_done'):
                continue

            # 2. CHECK SPECIFIC ACTIONS
            if action == 'done':
                if not act.user_id:
                    raise UserError(_("This activity is not assigned to anyone and cannot be marked as done."))
                if act.user_id.id != user.id:
                    raise UserError(_("Only the assigned user can mark this activity as done."))
            
            elif action == 'unlink':
                # UPDATE: Allow Assigned User OR Creator to cancel (delete)
                if act.create_uid.id != user.id and act.user_id.id != user.id:
                    raise UserError(_("Only the creator or the assigned user can cancel this activity."))

            elif action == 'write':
                # Keep Strict: Only Creator can edit details (deadline, etc.)
                if act.create_uid.id != user.id:
                    raise UserError(_("Only the creator of the activity can edit it."))

    # --- ORM Overrides ---
    def action_done(self):
        self._kh_check_permission('done')
        return super(MailActivity, self.with_context(activity_mark_as_done=True)).action_done()

    def action_feedback(self, feedback=False, attachment_ids=None):
        self._kh_check_permission('done')
        return super(MailActivity, self.with_context(activity_mark_as_done=True)).action_feedback(
            feedback=feedback, attachment_ids=attachment_ids)

    def write(self, vals):
        if self:
            self._kh_check_permission('write')
        return super().write(vals)

    def unlink(self):
        # If marking as done, the system is deleting it automatically -> Allow
        if self.env.context.get('activity_mark_as_done'):
            return super().unlink()
        
        # If manual delete (clicking X) -> Check Permission
        self._kh_check_permission('unlink')
        return super().unlink()