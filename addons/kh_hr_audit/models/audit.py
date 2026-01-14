from odoo import models, fields, api
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

class HrSmartAudit(models.TransientModel):
    _name = 'hr.smart.audit'
    _description = 'HR Smart Audit Notification'

    # ضع رقم الـ ID الخاص بالمدير هنا (مثلاً 2 للآدمن، أو الرقم اللي عندك)
    MANAGER_USER_ID = 2 

    def action_generate_audit_report(self):
        """ يتم استدعاؤها بواسطة الكرون جوب """
        end_date = fields.Date.today()
        start_date = end_date - relativedelta(days=30)
        
        employees = self.env['hr.employee'].search([('contract_id.state', '=', 'open')])
        
        # 1. بناء محتوى التقرير (HTML) يدوياً
        html_body = f"""
        <div dir="rtl" style="font-family: Arial, sans-serif;">
            <h3>📊 تقرير الرقابة الذكي (Smart Audit)</h3>
            <p><strong>الفترة:</strong> {start_date} إلى {end_date}</p>
            <table style="width: 100%; border-collapse: collapse; border: 1px solid #ddd;">
                <tr style="background-color: #f2f2f2; text-align: right;">
                    <th style="padding: 8px; border: 1px solid #ddd;">الموظف</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">معدل الدخول</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">تأخير > 9</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">رصيد الإجازات</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">مهام معلقة</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">التوصية</th>
                </tr>
        """

        for emp in employees:
            metrics = self._get_employee_metrics(emp, start_date, end_date)
            
            # تلوين التوصيات الخطيرة
            rec_style = "color: red; font-weight: bold;" if "Check" in metrics['recommendation'] else "color: green;"
            
            html_body += f"""
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">{metrics['name']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{metrics['avg_check_in']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{metrics['late_after_9']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{metrics['balance']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{metrics['pending_tasks']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; {rec_style}">{metrics['recommendation']}</td>
                </tr>
            """

        html_body += """
            </table>
            <br/>
            <p style="font-size: 12px; color: #777;">تم الإنشاء تلقائياً بواسطة نظام HR Smart Audit.</p>
        </div>
        """

        # 2. إرسال الإشعار للمدير
        self._send_odoo_notification(html_body)

    def _get_employee_metrics(self, employee, date_from, date_to):
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', date_from), ('check_in', '<=', date_to)
        ])
        late_count = sum(1 for att in attendances if fields.Datetime.context_timestamp(self, att.check_in).hour >= 9 and fields.Datetime.context_timestamp(self, att.check_in).minute > 0)
        
        return {
            'name': employee.name,
            'avg_check_in': '09:00', 
            'late_after_9': late_count,
            'balance': 21, 
            'pending_tasks': 5, 
            'recommendation': 'Check Lateness' if late_count > 3 else 'Good'
        }

    def _send_odoo_notification(self, html_content):
        """ إرسال رسالة خاصة للمدير في Odoo Discuss """
        manager_user = self.env['res.users'].browse(self.MANAGER_USER_ID)
        
        if not manager_user.exists():
            return 

        partner_id = manager_user.partner_id.id
        
        channel_obj = self.env.get('discuss.channel') or self.env.get('mail.channel')
        channel_info = channel_obj.channel_get([partner_id]) 
        channel_id = channel_info['id']
        
        channel = channel_obj.browse(channel_id)
        
        channel.message_post(
            body=html_content,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            author_id=self.env.user.partner_id.id 
        )