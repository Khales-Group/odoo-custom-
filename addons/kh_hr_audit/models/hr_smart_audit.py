from odoo import models, fields, api
from dateutil.relativedelta import relativedelta
from datetime import datetime, time, timedelta

class HrSmartAudit(models.TransientModel):
    _name = 'hr.smart.audit'
    _description = 'Smart HR Control Panel'

    date_from = fields.Date(string='من تاريخ', default=lambda self: fields.Date.today() - relativedelta(months=1))
    date_to = fields.Date(string='إلى تاريخ', default=fields.Date.today())
    employee_ids = fields.Many2many('hr.employee', string='تحديد موظفين')
    
    # تأكد من وجود هذا الحقل
    audit_line_ids = fields.One2many('hr.smart.audit.line', 'audit_id', string='نتائج التحليل')
    
    def action_analyze_data(self):
        # مسح النتائج القديمة
        self.audit_line_ids.unlink()
        
        target_employees = self.env['hr.employee']

        if self.employee_ids:
            target_employees = self.employee_ids
        else:
            # التصحيح هنا: البحث في العقود بدلاً من الموظف لتفادي الخطأ
            running_contracts = self.env['hr.contract'].search([('state', '=', 'open')])
            target_employees = running_contracts.mapped('employee_id')
            
            if not target_employees:
                target_employees = self.env['hr.employee'].search([])

        lines = []
        for emp in target_employees:
            # هنا دالة الحسابات
            metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
            
            lines.append((0, 0, {
                'employee_id': emp.id,
                'avg_check_in': metrics.get('avg_check_in', '-'),
                'late_count': metrics.get('late_after_9', 0),
                'days_worked': metrics.get('days_worked', 0),
                'absence_count': metrics.get('absence_count', 0),
                'leave_balance': metrics.get('balance', 0.0),
                'recommendation': metrics.get('recommendation', ''),
                'status': 'danger' if (metrics.get('late_after_9', 0) > 3 or metrics.get('absence_count', 0) > 0) else 'success'
            }))
            
        self.audit_line_ids = lines
        
        # إعادة تحميل الصفحة
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.smart.audit',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_employee_metrics(self, employee, date_from, date_to):
        # تحويل التواريخ إلى Datetime لضمان دقة البحث
        start_dt = datetime.combine(date_from, time.min)
        end_dt = datetime.combine(date_to, time.max)
        
        # 1. جلب سجلات الحضور وتجميع الساعات حسب اليوم
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', start_dt),
            ('check_in', '<=', end_dt)
        ])

        attendance_by_date = {}
        for att in attendances:
            if not att.check_in:
                continue
            
            # تحويل التوقيت للمنطقة الزمنية المحلية لتحديد "اليوم" بشكل صحيح
            local_check_in = fields.Datetime.context_timestamp(self, att.check_in)
            local_date = local_check_in.date()
            
            if local_date not in attendance_by_date:
                attendance_by_date[local_date] = {'hours': 0.0, 'check_ins': []}
            
            attendance_by_date[local_date]['check_ins'].append(local_check_in)
            
            # حساب ساعات العمل (إذا كان مسجلاً خروج)
            if att.check_out:
                duration = (att.check_out - att.check_in).total_seconds() / 3600.0
                attendance_by_date[local_date]['hours'] += duration

        # 2. جلب الإجازات المعتمدة في الفترة
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            # لا نضع شرط على holiday_status_id لنشمل جميع الأنواع (سنوي، مرضي، إلخ)
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from)
        ])
        
        leave_dates = set()
        for leave in leaves:
            curr = max(leave.request_date_from, date_from)
            end = min(leave.request_date_to, date_to)
            while curr <= end:
                leave_dates.add(curr)
                curr += timedelta(days=1)

        # 3. الحسابات اليومية
        late_count = 0
        days_worked = 0
        absence_count = 0
        total_check_in_minutes = 0
        check_in_days_count = 0

        # نمر على كل يوم في الفترة المحددة
        current_day = date_from
        while current_day <= date_to:
            att_data = attendance_by_date.get(current_day, {'hours': 0.0, 'check_ins': []})
            worked_hours = att_data['hours']
            
            # حساب أيام العمل (أي يوم حضر فيه)
            if worked_hours > 0:
                days_worked += 1

            # حساب التأخيرات (فقط للأيام التي حضر فيها)
            if att_data['check_ins']:
                first_check_in = min(att_data['check_ins'])
                check_in_minutes = first_check_in.hour * 60 + first_check_in.minute
                total_check_in_minutes += check_in_minutes
                check_in_days_count += 1
                
                if check_in_minutes > 9 * 60: # بعد 9:00 صباحاً
                    late_count += 1
            
            # منطق الغياب: عمل أقل من 4.5 ساعات
            if worked_hours < 4.5:
                # التحقق هل هو يوم عمل رسمي؟ (ليس عطلة أسبوعية وليس إجازة رسمية في الجدول)
                is_working_day = True
                if employee.resource_calendar_id:
                    # الدالة get_work_hours_count تعيد 0 إذا كان اليوم عطلة أو إجازة عامة (Global Time Off)
                    day_start = datetime.combine(current_day, time.min)
                    day_end = datetime.combine(current_day, time.max)
                    expected_hours = employee.resource_calendar_id.get_work_hours_count(day_start, day_end, compute_leaves=True, domain=None)
                    if expected_hours <= 0:
                        is_working_day = False
                
                # التحقق هل الموظف في إجازة شخصية (Leave)
                is_on_leave = current_day in leave_dates
                
                # إذا كان يوم عمل، وليس لديه إجازة، وساعاته أقل من 4.5 -> غياب
                if is_working_day and not is_on_leave:
                    absence_count += 1
            
            current_day += timedelta(days=1)

        # حساب المتوسط
        avg_check_in = '-'
        if check_in_days_count > 0:
            avg_val = total_check_in_minutes / check_in_days_count
            avg_check_in = '{:02d}:{:02d}'.format(int(avg_val // 60), int(avg_val % 60))
            
        # رصيد الإجازات (بشكل آمن)
        balance = employee.remaining_leaves if 'remaining_leaves' in employee else 0.0
        
        # التوصية
        if absence_count > 0:
            recommendation = 'خصم/تحقيق (غياب)'
        elif late_count > 3:
            recommendation = 'لفت نظر (تأخيرات)'
        elif late_count > 0:
            recommendation = 'تنبيه'
        else:
            recommendation = 'ممتاز'

        return {
            'avg_check_in': avg_check_in, 
            'late_after_9': late_count, 
            'days_worked': days_worked,
            'absence_count': absence_count,
            'balance': balance, 
            'recommendation': recommendation
        }

    def action_send_report(self):
        pass

    def action_auto_generate_payroll(self):
        pass

class HrSmartAuditLine(models.TransientModel):
    _name = 'hr.smart.audit.line'
    _description = 'Audit Result Line'

    audit_id = fields.Many2one('hr.smart.audit')
    employee_id = fields.Many2one('hr.employee', string='الموظف')
    avg_check_in = fields.Char(string='معدل الدخول')
    late_count = fields.Integer(string='تأخيرات')
    days_worked = fields.Integer(string='أيام العمل')
    absence_count = fields.Integer(string='غيابات')
    leave_balance = fields.Float(string='رصيد إجازات')
    recommendation = fields.Char(string='توصية')
    status = fields.Selection([('success', 'Good'), ('danger', 'Bad')], string='الحالة')