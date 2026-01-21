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

    date_from = fields.Date(string='من تاريخ', default=lambda self: fields.Date.today() - relativedelta(months=1))
    date_to = fields.Date(string='إلى تاريخ', default=fields.Date.today())
    employee_ids = fields.Many2many('hr.employee', string='تحديد موظفين')
    
    audit_line_ids = fields.One2many('hr.smart.audit.line', 'audit_id', string='نتائج التحليل')

    def action_analyze_data(self):
        self.audit_line_ids.unlink()
        employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])

        lines = []
        for emp in employees:
            metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
            
            lines.append((0, 0, {
                'employee_id': emp.id,
                'avg_check_in': metrics.get('avg_check_in', '-'),
                'late_count': metrics.get('late_after_9', 0),
                'days_worked': metrics.get('days_worked', 0),
                'absence_count': metrics.get('absence_count', 0),
                'leaves_taken': metrics.get('leaves_taken', 0),
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

    def _get_employee_metrics(self, employee, date_from, date_to):
        # توحيد المنطقة الزمنية
        tz = pytz.timezone(employee.resource_calendar_id.tz or 'UTC')
        
        # 1. جلب الحضور (Attendance)
        # نوسع النطاق قليلاً لتفادي مشاكل فروق التوقيت
        search_start = datetime.combine(date_from, time.min) - timedelta(days=1)
        search_end = datetime.combine(date_to, time.max) + timedelta(days=1)
        
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', search_start),
            ('check_in', '<=', search_end)
        ])
        
        attendance_dates = set()
        for att in attendances:
            if att.check_in:
                # تحويل وقت الدخول لتوقيت الموظف المحلي وأخذ التاريخ فقط
                local_dt = pytz.utc.localize(att.check_in).astimezone(tz)
                attendance_dates.add(local_dt.date())

        # 2. جلب الإجازات الخاصة (Leaves)
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

        # 3. جلب العطل الرسمية (Public Holidays)
        # نستخدم sudo() لضمان قراءة كل الإجازات
        # ونبحث عن الإجازات العامة (resource_id = False)
        global_leaves = self.env['resource.calendar.leaves'].sudo().search([
            ('resource_id', '=', False),
            ('date_from', '<=', search_end),
            ('date_to', '>=', search_start)
        ])
        
        public_holiday_dates = set()
        for gl in global_leaves:
            # تحويل تواريخ العطلة إلى تواريخ فقط (بدون وقت) لتسهيل المقارنة
            # نستخدم التوقيت المحلي للموظف للتأكد
            g_start_dt = pytz.utc.localize(gl.date_from).astimezone(tz).date()
            g_end_dt = pytz.utc.localize(gl.date_to).astimezone(tz).date()
            
            curr = max(g_start_dt, date_from)
            end = min(g_end_dt, date_to)
            
            while curr <= end:
                public_holiday_dates.add(curr)
                curr += timedelta(days=1)

        # المتغيرات
        late_count = 0
        days_worked = 0
        absence_count = 0
        leaves_taken_count = 0 
        check_in_days_count = 0

        # --- الحلقة اليومية ---
        current_day = date_from
        while current_day <= date_to:
            
            # A. هل هو إجازة خاصة؟
            if current_day in personal_leave_dates:
                leaves_taken_count += 1
                current_day += timedelta(days=1)
                continue 

            # B. هل هو عطلة رسمية (رأس السنة)؟
            if current_day in public_holiday_dates:
                # لو داوم بالعطلة نحسبله يوم عمل
                if current_day in attendance_dates:
                    days_worked += 1
                current_day += timedelta(days=1)
                continue 

            # C. هل هو ويكند (جمعة/سبت)؟
            is_weekend = False
            # الطريقة المضمونة: الفحص اليدوي للأيام
            # 4 = الجمعة، 5 = السبت
            if current_day.weekday() in [4, 5]:
                is_weekend = True
            
            # تأكيد إضافي من الجدول (إذا كان موجوداً)
            if not is_weekend and employee.resource_calendar_id:
                day_start = datetime.combine(current_day, time.min)
                day_end = datetime.combine(current_day, time.max)
                try:
                    # compute_leaves=False ليعطينا ساعات الجدول الصافية
                    hours = employee.resource_calendar_id.get_work_hours_count(day_start, day_end, compute_leaves=False)
                    if hours < 1: # إذا الساعات 0، فهو ويكند
                        is_weekend = True
                except:
                    pass

            if is_weekend:
                # لو داوم في الويكند
                if current_day in attendance_dates:
                    days_worked += 1
                current_day += timedelta(days=1)
                continue

            # D. يوم عمل عادي (ليس إجازة، ليس عطلة رسمية، ليس ويكند)
            if current_day in attendance_dates:
                days_worked += 1
                check_in_days_count += 1
                
                # حساب التأخير (تقريبي)
                # نحتاج الدخول لهذا اليوم بالتحديد
                today_att = attendances.filtered(lambda a: a.check_in and pytz.utc.localize(a.check_in).astimezone(tz).date() == current_day)
                if today_att:
                    # نأخذ أول دخول
                    first_in = min(today_att.mapped('check_in'))
                    local_in = pytz.utc.localize(first_in).astimezone(tz)
                    # بعد 9:00 صباحاً يعتبر متأخر
                    if local_in.hour > 9 or (local_in.hour == 9 and local_in.minute > 0):
                        late_count += 1
            else:
                # يوم عمل + لم يحضر = غياب
                absence_count += 1

            current_day += timedelta(days=1)

        return {
            'avg_check_in': '-', 
            'late_after_9': late_count, 
            'days_worked': days_worked, 
            'absence_count': absence_count, 
            'leaves_taken': leaves_taken_count, 
            'balance': employee.remaining_leaves if 'remaining_leaves' in employee else 0.0, 
            'recommendation': 'خصم' if absence_count > 0 else 'جيد'
        }

    # =========================================================
    #  إنشاء الرواتب + حقن الخصم (بدون أخطاء)
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
                # البحث عن العقد
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

                # إنشاء القسيمة
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

                # الحساب والخصم
                try:
                    payslip.compute_sheet()
                    self._inject_deduction(emp, payslip, ded_category)
                except Exception as e:
                    _logger.warning(f"Error computing slip for {emp.name}: {e}")

            except Exception as e:
                _logger.error(f"Failed for {emp.name}: {e}")
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

    def _inject_deduction(self, emp, payslip, ded_category):
        # نعيد الحساب للتأكد من عدد أيام الغياب الحالية
        metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
        absence_days = metrics.get('absence_count', 0)
        
        if absence_days <= 0: return

        wage = getattr(emp, 'wage', 0.0)
        if wage == 0.0 and payslip.contract_id and hasattr(payslip.contract_id, 'wage'):
            wage = payslip.contract_id.wage
            
        if wage > 0:
            month_days = 30 # اعتماد 30 يوم قياسي للرواتب (أو استخدم calendar.monthrange)
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

class HrSmartAuditLine(models.TransientModel):
    _name = 'hr.smart.audit.line'
    _description = 'Audit Result Line'

    audit_id = fields.Many2one('hr.smart.audit')
    employee_id = fields.Many2one('hr.employee', string='الموظف')
    avg_check_in = fields.Char(string='معدل الدخول')
    late_count = fields.Integer(string='تأخيرات')
    days_worked = fields.Integer(string='أيام العمل')
    absence_count = fields.Integer(string='غيابات (بدون عذر)')
    leaves_taken = fields.Integer(string='إجازات (أيام)')
    leave_balance = fields.Float(string='رصيد إجازات')
    recommendation = fields.Char(string='توصية')
    status = fields.Selection([('success', 'Good'), ('danger', 'Bad')], string='الحالة')