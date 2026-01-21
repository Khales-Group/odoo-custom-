# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta
from datetime import datetime, time, timedelta, date
import calendar
import logging
import pytz

_logger = logging.getLogger(__name__)

class HrSmartAudit(models.TransientModel):
    _name = 'hr.smart.audit'
    _description = 'Smart HR Control Panel'

    # =========================================================
    #  1. الحقول الأساسية
    # =========================================================
    date_from = fields.Date(string='من تاريخ', default=lambda self: fields.Date.today() - relativedelta(months=1))
    date_to = fields.Date(string='إلى تاريخ', default=fields.Date.today())
    employee_ids = fields.Many2many('hr.employee', string='تحديد موظفين')
    
    audit_line_ids = fields.One2many('hr.smart.audit.line', 'audit_id', string='نتائج التحليل')

    # =========================================================
    #  2. زر تحليل البيانات (مع حفظ التواريخ التفصيلية)
    # =========================================================
    def action_analyze_data(self):
        # تنظيف القديم
        self.audit_line_ids.unlink()
        
        employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])

        lines = []
        for emp in employees:
            # استدعاء دالة الحسابات التي ترجع الأرقام + النصوص التفصيلية
            metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
            
            lines.append((0, 0, {
                'employee_id': emp.id,
                'avg_check_in': metrics.get('avg_check_in', '-'),
                'late_count': metrics.get('late_after_9', 0),
                
                # الأرقام
                'days_worked': metrics.get('days_worked', 0),
                'absence_count': metrics.get('absence_count', 0),
                'leaves_taken': metrics.get('leaves_taken', 0),
                
                # التفاصيل النصية (التواريخ) - الإضافة الجديدة
                'work_details': metrics.get('work_log', ''),
                'absence_details': metrics.get('absence_log', ''),
                'holiday_details': metrics.get('holiday_log', ''),

                'leave_balance': metrics.get('balance', 0.0),
                'recommendation': metrics.get('recommendation', ''),
                'status': 'danger' if (metrics.get('late_after_9', 0) > 3 or metrics.get('absence_count', 0) > 0) else 'success'
            }))
            
        self.audit_line_ids = lines
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.smart.audit',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # =========================================================
    #  3. دالة الحسابات (معالجة التوقيت + تسجيل التواريخ)
    # =========================================================
    def _get_employee_metrics(self, employee, date_from, date_to):
        # تحديد التوقيت (Timezone) لضمان دقة العطل
        tz_name = employee.resource_calendar_id.tz or self.env.user.tz or 'Asia/Dubai'
        try:
            tz = pytz.timezone(tz_name)
        except:
            tz = pytz.utc

        # توسيع النطاق للحضور
        search_start = datetime.combine(date_from, time.min) - timedelta(days=1)
        search_end = datetime.combine(date_to, time.max) + timedelta(days=1)
        
        # أ. جلب الحضور
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', search_start),
            ('check_in', '<=', search_end)
        ])
        
        attendance_dates = set()
        attendance_details = {} 

        for att in attendances:
            if att.check_in:
                # تحويل للمحلي
                local_check_in = pytz.utc.localize(att.check_in).astimezone(tz)
                local_date = local_check_in.date()
                
                if date_from <= local_date <= date_to:
                    attendance_dates.add(local_date)
                    if local_date not in attendance_details:
                        attendance_details[local_date] = []
                    attendance_details[local_date].append(local_check_in)

        # ب. جلب الإجازات الخاصة
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from)
        ])
        personal_leave_dates = set()
        for leave in leaves:
            curr = leave.request_date_from
            end = leave.request_date_to
            while curr <= end:
                personal_leave_dates.add(curr)
                curr += timedelta(days=1)

        # ج. جلب العطل الرسمية (مع التحويل الزمني)
        global_leaves = self.env['resource.calendar.leaves'].sudo().search([
            ('resource_id', '=', False),
            ('date_from', '<=', search_end),
            ('date_to', '>=', search_start)
        ])
        
        public_holiday_dates = {} # قمت بتغييره لقاموس لنحفظ اسم العطلة
        for gl in global_leaves:
            g_start = pytz.utc.localize(gl.date_from).astimezone(tz).date()
            g_end = pytz.utc.localize(gl.date_to).astimezone(tz).date()
            
            curr = max(g_start, date_from)
            end = min(g_end, date_to)
            while curr <= end:
                public_holiday_dates[curr] = gl.name
                curr += timedelta(days=1)

        # المتغيرات (عدادات + قوائم تواريخ)
        late_count = 0
        days_worked = 0
        absence_count = 0
        leaves_taken_count = 0 
        
        # قوائم لتخزين النصوص (Log)
        work_log = []
        absence_log = []
        holiday_log = []

        # --- الحلقة اليومية ---
        current_day = date_from
        while current_day <= date_to:
            day_str = current_day.strftime("%d/%m") # تنسيق التاريخ يوم/شهر
            
            # 1. إجازة خاصة
            if current_day in personal_leave_dates:
                leaves_taken_count += 1
                current_day += timedelta(days=1)
                continue 

            # 2. عطلة رسمية (رأس السنة)
            if current_day in public_holiday_dates:
                holiday_name = public_holiday_dates[current_day]
                # لو داوم نسجله عمل
                if current_day in attendance_dates:
                    days_worked += 1
                    work_log.append(f"{day_str} (دوام بالعطلة)")
                    holiday_log.append(f"{day_str} {holiday_name} (حضر)")
                else:
                    holiday_log.append(f"{day_str} {holiday_name}")
                
                current_day += timedelta(days=1)
                continue 

            # 3. ويكند (جمعة/سبت)
            is_weekend = False
            if current_day.weekday() in [4, 5]: # 4=Fri, 5=Sat
                is_weekend = True
            
            # تحقق إضافي من الجدول
            if not is_weekend and employee.resource_calendar_id:
                try:
                    day_start = datetime.combine(current_day, time.min)
                    day_end = datetime.combine(current_day, time.max)
                    hours = employee.resource_calendar_id.get_work_hours_count(day_start, day_end, compute_leaves=False)
                    if hours <= 0:
                        is_weekend = True
                except:
                    pass

            if is_weekend:
                if current_day in attendance_dates:
                    days_worked += 1
                    work_log.append(f"{day_str} (ويكند)")
                current_day += timedelta(days=1)
                continue

            # 4. يوم عمل رسمي
            if current_day in attendance_dates:
                days_worked += 1
                work_log.append(day_str)
                
                # تأخير
                daily_checks = attendance_details.get(current_day, [])
                if daily_checks:
                    first_in = min(daily_checks)
                    if first_in.hour > 9 or (first_in.hour == 9 and first_in.minute > 0):
                        late_count += 1
            else:
                absence_count += 1
                absence_log.append(f"{day_str} ({current_day.strftime('%A')})")

            current_day += timedelta(days=1)

        # تحويل القوائم لنصوص للعرض
        return {
            'avg_check_in': '-', 
            'late_after_9': late_count, 
            'days_worked': days_worked, 
            'absence_count': absence_count, 
            'leaves_taken': leaves_taken_count,
            
            # هنا نرجع النصوص
            'work_log': ', '.join(work_log), 
            'absence_log': ', '.join(absence_log),
            'holiday_log': ', '.join(holiday_log),
            
            'balance': employee.remaining_leaves if 'remaining_leaves' in employee else 0.0, 
            'recommendation': 'خصم' if absence_count > 0 else 'جيد'
        }

    # =========================================================
    #  4. إنشاء الرواتب (لم يحذف، موجود كما هو)
    # =========================================================
    def action_auto_generate_payroll(self):
        if 'hr.payslip' not in self.env:
            raise UserError('نظام الرواتب غير مثبت.')

        employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])
        created_count = 0
        
        try:
            ded_category = self.env['hr.salary.rule.category'].sudo().search([('code', 'in', ['DED', 'DEDUCTION'])], limit=1)
        except:
            ded_category = False

        for emp in employees:
            try:
                contract_id = False
                c_id = getattr(emp, 'contract_id', False)
                if c_id: contract_id = c_id.id
                if not contract_id:
                    c_ids = getattr(emp, 'contract_ids', False)
                    if c_ids: contract_id = c_ids[0].id
                if not contract_id:
                    ContractEnv = self.env.get('hr.contract')
                    if ContractEnv:
                        found = ContractEnv.search([('employee_id', '=', emp.id)], limit=1, order='date_start desc')
                        if found: contract_id = found.id

                vals = {
                    'employee_id': emp.id,
                    'date_from': self.date_from,
                    'date_to': self.date_to,
                    'name': f'Salary Slip - {emp.name}',
                    'company_id': emp.company_id.id or self.env.company.id,
                }
                if contract_id: vals['contract_id'] = contract_id

                payslip = self.env['hr.payslip'].create(vals)
                created_count += 1

                try:
                    payslip.compute_sheet()
                    self._inject_deduction(emp, payslip, ded_category)
                except Exception as e:
                    _logger.warning(f"Error computing slip: {e}")

            except Exception as e:
                _logger.error(f"Failed creation: {e}")
                continue

        if created_count > 0:
            return {
                'name': 'Generated Payslips',
                'domain': [('id', 'in', [p.id for p in self.env['hr.payslip'].search([('date_from', '=', self.date_from)])])],
                'view_mode': 'list,form',
                'res_model': 'hr.payslip',
                'type': 'ir.actions.act_window',
            }
        else:
            return self._show_warning('لم يتم إنشاء قسائم.')

    # =========================================================
    #  5. حقن الخصم (موجود)
    # =========================================================
    def _inject_deduction(self, emp, payslip, ded_category):
        metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
        absence_days = metrics.get('absence_count', 0)
        
        if absence_days <= 0: return

        wage = getattr(emp, 'wage', 0.0)
        if wage == 0.0 and payslip.contract_id and hasattr(payslip.contract_id, 'wage'):
            wage = payslip.contract_id.wage
            
        if wage > 0:
            month_days = 30 
            daily_wage = wage / month_days
            deduction_amount = daily_wage * absence_days
            
            self.env['hr.payslip.line'].create({
                'slip_id': payslip.id,
                'name': f'خصم غياب ({absence_days} يوم)',
                'code': 'ABS_DED',
                'category_id': ded_category.id if ded_category else False,
                'sequence': 99, 
                'quantity': absence_days,
                'rate': 100,
                'amount': -deduction_amount,
                'total': -deduction_amount,
                'employee_id': emp.id,
                'contract_id': payslip.contract_id.id if payslip.contract_id else False,
            })
            
            net_line = self.env['hr.payslip.line'].search([('slip_id', '=', payslip.id), ('code', '=', 'NET')], limit=1)
            if net_line:
                new_net = net_line.amount - deduction_amount
                net_line.write({'amount': new_net, 'total': new_net})

    def _show_warning(self, msg):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'تنبيه', 'message': msg, 'type': 'warning', 'sticky': False}
        }
    
    def action_send_report(self):
        pass

# =========================================================
#  موديل العرض (تمت إضافة حقول التواريخ النصية)
# =========================================================
class HrSmartAuditLine(models.TransientModel):
    _name = 'hr.smart.audit.line'
    _description = 'Audit Result Line'

    audit_id = fields.Many2one('hr.smart.audit')
    employee_id = fields.Many2one('hr.employee', string='الموظف')
    
    avg_check_in = fields.Char(string='معدل الدخول')
    late_count = fields.Integer(string='تأخيرات')
    
    days_worked = fields.Integer(string='أيام العمل')
    work_details = fields.Text(string='تواريخ العمل') # <--- جديد: اعرض هذا الحقل لترى التواريخ
    
    absence_count = fields.Integer(string='غيابات (بدون عذر)')
    absence_details = fields.Text(string='تواريخ الغياب') # <--- جديد: اعرض هذا الحقل
    
    leaves_taken = fields.Integer(string='إجازات (أيام)')
    holiday_details = fields.Text(string='تواريخ العطل') # <--- جديد
    
    leave_balance = fields.Float(string='رصيد إجازات')
    recommendation = fields.Char(string='توصية')
    status = fields.Selection([('success', 'Good'), ('danger', 'Bad')], string='الحالة')