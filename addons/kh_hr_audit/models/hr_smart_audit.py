from odoo import models, fields, api
from dateutil.relativedelta import relativedelta
from datetime import datetime, time, timedelta
import calendar
import logging

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
        start_dt = datetime.combine(date_from, time.min)
        end_dt = datetime.combine(date_to, time.max)
        
        # 1. الحضور
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', start_dt),
            ('check_in', '<=', end_dt)
        ])
        attendance_by_date = {}
        for att in attendances:
            if not att.check_in: continue
            local_check_in = fields.Datetime.context_timestamp(self, att.check_in)
            d = local_check_in.date()
            if d not in attendance_by_date: attendance_by_date[d] = {'hours': 0.0, 'check_ins': []}
            attendance_by_date[d]['check_ins'].append(local_check_in)
            if att.check_out:
                attendance_by_date[d]['hours'] += (att.check_out - att.check_in).total_seconds() / 3600.0

        # 2. الإجازات الخاصة (Leaves)
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from)
        ])
        personal_leave_dates = set()
        for leave in leaves:
            curr = max(leave.request_date_from, date_from)
            end = min(leave.request_date_to, date_to)
            while curr <= end:
                personal_leave_dates.add(curr)
                curr += timedelta(days=1)

        # 3. العطل الرسمية (Global Leaves) - بحث عام لكل الشركة
        # نبحث عن أي إجازة عامة غير مربوطة بمورد محدد (تطبق على الكل)
        global_leaves = self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),  # إجازة عامة
            ('date_from', '<=', end_dt),
            ('date_to', '>=', start_dt)
        ])
        public_holiday_dates = set()
        for gl in global_leaves:
            # تحويل التواريخ لمقارنة اليوم فقط
            g_start = fields.Datetime.context_timestamp(self, gl.date_from).date()
            g_end = fields.Datetime.context_timestamp(self, gl.date_to).date()
            curr = max(g_start, date_from)
            end = min(g_end, date_to)
            while curr <= end:
                public_holiday_dates.add(curr)
                curr += timedelta(days=1)

        late_count = 0
        days_worked = 0
        absence_count = 0
        leaves_taken_count = 0 
        total_check_in_minutes = 0
        check_in_days_count = 0

        # --- الفحص اليومي ---
        current_day = date_from
        while current_day <= date_to:
            
            # أ. فحص الإجازات الخاصة (Approved Leaves)
            if current_day in personal_leave_dates:
                leaves_taken_count += 1
                current_day += timedelta(days=1)
                continue 

            # ب. فحص العطل الرسمية (Public Holidays) - الأولوية الثانية
            if current_day in public_holiday_dates:
                current_day += timedelta(days=1)
                continue 

            # ج. فحص العطل الأسبوعية (Weekends)
            is_weekend = False
            if employee.resource_calendar_id:
                # نسأل الجدول: هل ساعات العمل اليوم > 0؟
                day_start = datetime.combine(current_day, time.min)
                day_end = datetime.combine(current_day, time.max)
                # compute_leaves=False لأننا حسبنا الإجازات فوق يدوياً
                hours = employee.resource_calendar_id.get_work_hours_count(day_start, day_end, compute_leaves=False)
                if hours <= 0:
                    is_weekend = True
            else:
                # fallback: الجمعة (4) والسبت (5) عطلة
                if current_day.weekday() in [4, 5]:
                    is_weekend = True
            
            if is_weekend:
                # لو داوم في الويكند نحسبله يوم عمل، بس لو غاب ما نحسب غياب
                if attendance_by_date.get(current_day, {}).get('hours', 0) > 0:
                    days_worked += 1
                current_day += timedelta(days=1)
                continue

            # د. فحص الدوام (يوم عمل رسمي)
            att_data = attendance_by_date.get(current_day, {'hours': 0.0, 'check_ins': []})
            worked_hours = att_data['hours']

            if worked_hours > 0:
                days_worked += 1
                
                # تأخير
                if att_data['check_ins']:
                    first = min(att_data['check_ins'])
                    mins = first.hour * 60 + first.minute
                    total_check_in_minutes += mins
                    check_in_days_count += 1
                    if mins > 9 * 60: late_count += 1
                
                # دوام ناقص (أقل من 4 ساعات)
                if worked_hours < 4.0:
                    absence_count += 1
            else:
                # يوم عمل - لا إجازة - لا عطلة - 0 ساعات = غياب
                absence_count += 1

            current_day += timedelta(days=1)

        avg = '-'
        if check_in_days_count > 0:
            val = total_check_in_minutes / check_in_days_count
            avg = '{:02d}:{:02d}'.format(int(val // 60), int(val % 60))
            
        return {
            'avg_check_in': avg, 
            'late_after_9': late_count, 
            'days_worked': days_worked, 
            'absence_count': absence_count, 
            'leaves_taken': leaves_taken_count, 
            'balance': employee.remaining_leaves if 'remaining_leaves' in employee else 0.0, 
            'recommendation': 'خصم' if absence_count > 0 else 'جيد'
        }

    def action_send_report(self):
        pass

    def action_auto_generate_payroll(self):
        if 'hr.payslip' not in self.env:
            return self._show_warning('نظام الرواتب غير مثبت.')

        employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])
        created_count = 0
        ded_category = False
        try:
            ded_category = self.env['hr.salary.rule.category'].sudo().search([('code', 'in', ['DED', 'DEDUCTION'])], limit=1)
        except: pass

        for emp in employees:
            try:
                # محاولة الحصول على عقد
                contract_id = False
                # 1. مباشر
                c_id = getattr(emp, 'contract_id', False)
                if c_id: contract_id = c_id.id
                # 2. أرشيف
                if not contract_id:
                    c_ids = getattr(emp, 'contract_ids', False)
                    if c_ids: contract_id = c_ids[0].id
                # 3. بحث
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
                except:
                    pass
            except Exception as e:
                _logger.error(f"Error creating slip for {emp.name}: {e}")
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
        metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
        absence_days = metrics.get('absence_count', 0)
        
        if absence_days <= 0: return

        wage = getattr(emp, 'wage', 0.0)
        if wage == 0.0 and payslip.contract_id and hasattr(payslip.contract_id, 'wage'):
            wage = payslip.contract_id.wage
            
        if wage > 0:
            month_days = calendar.monthrange(self.date_to.year, self.date_to.month)[1]
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