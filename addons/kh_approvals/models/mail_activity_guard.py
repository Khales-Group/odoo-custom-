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
        # ENABLE the guard so the permissions actually work
        return True

    def _kh_check_permission(self, action):
        """
        Guard for activity actions.
        - 'done': Can only be performed by the assigned user.
        - 'write', 'unlink': Can only be performed by the activity creator.
        Managers and superusers are always allowed.
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

            if action == 'done':
                if not act.user_id:
                    raise UserError(_("This activity is not assigned to anyone and cannot be marked as done."))
                if act.user_id.id != user.id:
                    raise UserError(_("Only the assigned user can mark this activity as done."))
            
            elif action in ['write', 'unlink']:
                if act.create_uid.id != user.id:
                    raise UserError(_("Only the creator of the activity can edit or delete it."))

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
        if self.env.context.get('activity_mark_as_done'):
            return super().unlink()
        
        self._kh_check_permission('unlink')
        return super().unlink()
