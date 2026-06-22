# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
try:
    from odoo.tools import Markup
except ImportError:
    from markupsafe import Markup

# ---------------------------------------------------------
# 1. كلاس الصلاحيات (كودك الأصلي مع تحسين بسيط)
# ---------------------------------------------------------
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
        # Majid (369) and his delegate (409) can manage any activity
        if user.id in {369, 409}:
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
                if act.user_id.id != user.id and act.create_uid.id != user.id:
                    raise UserError(_("Only the assigned user or activity creator can mark this activity as done."))
            
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


# ---------------------------------------------------------
# 2. كلاس حل مشكلة المرفقات (الجديد)
# ---------------------------------------------------------
class MailActivitySchedule(models.TransientModel):
    _inherit = 'mail.activity.schedule'

    # نضيف حقل مرفقات خاص بنافذة الجدولة
    x_attachment_ids = fields.Many2many('ir.attachment', string="إرفاق ملفات", domain=[('res_model', '!=', 'knowledge.article')])

    def action_schedule_activities(self):
        """
        عند الضغط على زر الجدولة، نأخذ الملفات ونضع روابطها داخل الملاحظة
        """
        # التأكد من وجود ملاحظة لتفادي الخطأ
        note = Markup(self.note or '')
        
        if self.x_attachment_ids:
            # FIX: Use Base URL for absolute links (Email support)
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            
            # FIX: Persist attachments by linking them to the target record
            target_id = False
            if self.res_ids:
                try:
                    ids_list = [int(x) for x in str(self.res_ids).split(',') if x.strip()]
                    if ids_list:
                        target_id = ids_list[0]
                except Exception:
                    pass

            links = []
            for attachment in self.x_attachment_ids:
                if target_id and self.res_model:
                    attachment.sudo().write({'res_model': self.res_model, 'res_id': target_id})

                # إنشاء رابط تحميل مباشر
                download_url = f'{base_url}/web/content/{attachment.id}?download=true'
                # تنسيق الرابط ليظهر بشكل واضح
                link_html = f'<div style="margin-top:5px;"><a href="{download_url}" target="_blank" style="background-color: #f1f1f1; padding: 5px; border-radius: 4px;">📎 تحميل: {attachment.name}</a></div>'
                links.append(link_html)
            
            # دمج الروابط في نهاية الملاحظ
            self.note = note + Markup("<br/><hr/><b>📂 ملفات مرفقة:</b>") + Markup("".join(links))

        # استكمال العملية الطبيعية لأودو
        return super(MailActivitySchedule, self).action_schedule_activities()