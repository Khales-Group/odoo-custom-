# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import ast
# المكتبة الضرورية لعرض الروابط كـ HTML حقيقي وليس كنص
from markupsafe import Markup 

# ---------------------------------------------------------
# 1. كلاس الصلاحيات (Activity Permissions)
# ---------------------------------------------------------
class MailActivity(models.Model):
    _inherit = 'mail.activity'

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
            
            # السماح للنظام بالكتابة عند إنهاء النشاط
            if action == 'write' and self.env.context.get('activity_mark_as_done'):
                continue

            if action == 'done':
                if not act.user_id:
                    raise UserError(_("هذا النشاط غير مسند لأحد ولا يمكن إنهاؤه."))
                if act.user_id.id != user.id and act.create_uid.id != user.id:
                    raise UserError(_("فقط المستخدم المسند إليه أو منشئ النشاط يمكنه إنهاؤه."))
            
            elif action == 'unlink':
                if act.create_uid.id != user.id and act.user_id.id != user.id:
                    raise UserError(_("فقط منشئ النشاط أو المستخدم المسند إليه يمكنه الحذف."))

            elif action == 'write':
                if act.create_uid.id != user.id:
                    raise UserError(_("فقط منشئ النشاط يمكنه تعديله."))

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
# 2. كلاس المرفقات (Activity Attachments & HTML Fix)
# ---------------------------------------------------------
class MailActivitySchedule(models.TransientModel):
    _inherit = 'mail.activity.schedule'

    x_attachment_ids = fields.Many2many('ir.attachment', string="إرفاق ملفات")

    def action_schedule_activities(self):
        """
        عند الجدولة، نربط الملفات بالسجل الأصلي وننشئ روابط تحميل آمنة
        """
        # استخدام Markup لضمان عدم تشفير أكواد الـ HTML
        note = Markup(self.note) if self.note else Markup('')
        
        if self.x_attachment_ids:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            
            # جلب معرف السجل المستهدف (Target Record ID)
            target_id = False
            if self.res_ids:
                try:
                    ids_list = ast.literal_eval(self.res_ids)
                    if isinstance(ids_list, list) and ids_list:
                        target_id = ids_list[0]
                    elif isinstance(ids_list, int):
                        target_id = ids_list
                except Exception:
                    pass

            links_html = []
            for attachment in self.x_attachment_ids:
                # 1. ربط الملف بالسجل لضمان الصلاحيات مستقبلاً
                if target_id and self.res_model:
                    attachment.sudo().write({'res_model': self.res_model, 'res_id': target_id})

                # 2. إنشاء Access Token إذا لم يكن موجوداً (للسماح بالتحميل للمستلم)
                if not attachment.access_token:
                    attachment.sudo().generate_access_token()

                # 3. بناء الرابط مع التوكن
                download_url = f'{base_url}/web/content/{attachment.id}?download=true&access_token={attachment.access_token}'
                
                # 4. تصميم الزر بشكل HTML منسق
                link_btn = f'''
                    <div style="margin-top:8px;">
                        <a href="{download_url}" target="_blank" 
                           style="background-color: #f8f9fa; padding: 6px 12px; border-radius: 4px; 
                                  text-decoration: none; color: #017e84; border: 1px solid #dee2e6; 
                                  display: inline-block; font-size: 13px; font-weight: bold;">
                           📎 تحميل: {attachment.name}
                        </a>
                    </div>'''
                links_html.append(link_btn)
            
            # دمج الملاحظة مع الروابط كـ Markup واحد
            footer = Markup("<br/><hr/><b>📂 ملفات مرفقة:</b>") + Markup("".join(links_html))
            self.note = note + footer

        # استكمال العملية الافتراضية لأودو
        return super(MailActivitySchedule, self).action_schedule_activities()