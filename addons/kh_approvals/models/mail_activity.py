from odoo import models, api, fields, _
from odoo.exceptions import UserError
import ast

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

        if not self._kh_guard_enabled():

            return

        user = self.env.user

        if self.env.is_superuser():

            return

        excluded = self._kh_guard_excluded_models()



        for act in self:

            if act.res_model in excluded:

                continue

           

            # ALLOW SYSTEM WRITES IF MARKING DONE

            if action == 'write' and self.env.context.get('activity_mark_as_done'):

                continue



            # CHECK SPECIFIC ACTIONS

            if action == 'done':

                if not act.user_id:

                    raise UserError(_("This activity is not assigned to anyone and cannot be marked as done."))

                if act.user_id.id != user.id:

                    raise UserError(_("Only the assigned user can mark this activity as done."))

           

            elif action == 'unlink':

                if act.create_uid.id != user.id and act.user_id.id != user.id:

                    raise UserError(_("Only the creator or the assigned user can cancel this activity."))



            elif action == 'write':

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

        if self.env.context.get('activity_mark_as_done'):

            return super().unlink()

        self._kh_check_permission('unlink')

        return super().unlink()


class MailActivitySchedule(models.TransientModel):
    _inherit = 'mail.activity.schedule'

    x_attachment_ids = fields.Many2many('ir.attachment', string="إرفاق ملفات")

    def action_schedule_activities(self):
        note = self.note or ''

        if self.x_attachment_ids:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

            # تحسين جلب الـ ID: أودو يرسل res_ids أحياناً كـ String يحتوي على أقواس [123]
            target_id = False
            if self.res_ids:
                try:
                    # تحويل النص إلى قائمة بشكل آمن
                    ids_list = ast.literal_eval(self.res_ids)
                    if isinstance(ids_list, list) and ids_list:
                        target_id = ids_list[0]
                    elif isinstance(ids_list, int):
                        target_id = ids_list
                except:
                    pass

            links = []
            for attachment in self.x_attachment_ids:
                # 1. ربط الملف بالسجل الأصلي (sudo لضمان الصلاحية)
                if target_id and self.res_model:
                    attachment.sudo().write({
                        'res_model': self.res_model,
                        'res_id': target_id,
                        'public': True # اختيار اختياري لجعل الملف عاماً
                    })

                # 2. توليد توكن وصول (هذا هو السر!)
                # إذا لم يكن هناك توكن، نقوم بإنشائه
                if not attachment.access_token:
                    attachment.sudo().generate_access_token()

                # 3. تعديل الرابط ليشمل التوكن
                download_url = f'{base_url}/web/content/{attachment.id}?download=true&access_token={attachment.access_token}'

                link_html = f'''
                    <div style="margin-top:5px;">
                        <a href="{download_url}" target="_blank"
                           style="background-color: #f1f1f1; padding: 5px 10px; border-radius: 4px; text-decoration: none; color: #017e84; border: 1px solid #dee2e6;">
                           📎 تحميل: {attachment.name}
                        </a>
                    </div>'''
                links.append(link_html)

            self.note = note + "<br/><hr/><b>📂 ملفات مرفقة:</b>" + "".join(links)

        return super(MailActivitySchedule, self).action_schedule_activities()

