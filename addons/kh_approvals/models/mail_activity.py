from odoo import models, api, _
from odoo.exceptions import UserError


class MailActivity(models.Model):
    _inherit = "mail.activity"

    def _check_access_for_user(self, user):
        for act in self:
            if act.user_id != user and act.create_uid != user:
                raise UserError(_("Only the assigned user or the activity creator can modify or delete this activity."))

    def unlink(self):
        if not self.env.context.get('kh_from_mark_done'):
            self._check_access_for_user(self.env.user)
        return super(MailActivity, self).unlink()

    def write(self, vals):
        if not self.env.context.get('kh_from_mark_done'):
            self._check_access_for_user(self.env.user)
        return super(MailActivity, self).write(vals)

    def action_done(self):
        self._check_access_for_user(self.env.user)
        return super(MailActivity, self.with_context(kh_from_mark_done=True)).action_done()

    def action_feedback(self, feedback=False, attachment_ids=None, **kwargs):
        self._check_access_for_user(self.env.user)
        return super(MailActivity, self.with_context(kh_from_mark_done=True)).action_feedback(feedback=feedback, attachment_ids=attachment_ids, **kwargs)
