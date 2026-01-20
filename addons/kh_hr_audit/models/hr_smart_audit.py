from odoo import models, fields, api
from dateutil.relativedelta import relativedelta
from datetime import datetime, time, timedelta
import calendar

class HrSmartAudit(models.TransientModel):
    _name = 'hr.smart.audit'
    _description = 'Smart HR Control Panel'

    date_from = fields.Date(string='من تاريخ', default=lambda self: fields.Date.today() - relativedelta(months=1))
    date_to = fields.Date(string='إلى تاريخ', default=fields.Date.today())
    employee_ids = fields.Many2many('hr.employee', string='تحديد موظفين')
    
    audit_line_ids = fields.One2many('hr.smart.audit.line', 'audit_id', string='نتائج التحليل')
    
    def action_analyze_data(self):
        self.audit_line_ids.unlink()
        
        # 1. جلب الموظفين
        # بدلاً من البحث في العقود، نجلب الموظفين ونفلترهم حسب العقد المرتبط بهم
        if self.employee_ids:
            all_employees = self.employee_ids
        else:
            all_employees = self.env['hr.employee'].search([])

        lines = []
        for emp in all_employees:
            # التحقق من العقد عن طريق ملف الموظف مباشرة
            # emp.contract_id هي العلاقة المباشرة في بروفايل الموظف
            contract = emp.contract_id
            
            # إذا لم نجد عقداً في الحقل المباشر، نحاول البحث في العقود المرتبطة (Just in case)
            if not contract and 'contract_ids' in emp._fields:
                 # نأخذ أول عقد مفتوح
                 contract = emp.contract_ids.filtered(lambda c: c.state == 'open')[:1]

            # (اختياري) إذا أردت استبعاد الموظفين الذين ليس لديهم عقود سارية، فعل هذا الشرط:
            # if not contract or contract.state != 'open':
            #    continue 

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
        
        # جلب الحضور
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', start_dt),
            ('check_in', '<=', end_dt)
        ])

        attendance_by_date = {}
        for att in attendances:
            if not att.check_in: continue
            local_check_in = fields.Datetime.context_timestamp(self, att.check_in)
            local_date = local_check_in.date()
            if local_date not in attendance_by_date:
                attendance_by_date[local_date] = {'hours': 0.0, 'check_ins': []}
            attendance_by_date[local_date]['check_ins'].append(local_check_in)
            if att.check_out:
                duration = (att.check_out - att.check_in).total_seconds() / 3600.0
                attendance_by_date[local_date]['hours'] += duration

        # جلب الإجازات
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
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

        late_count = 0
        days_worked = 0
        absence_count = 0
        leaves_taken_count = 0 
        total_check_in_minutes = 0
        check_in_days_count = 0

        current_day = date_from
        while current_day <= date_to:
            att_data = attendance_by_date.get(current_day, {'hours': 0.0, 'check_ins': []})
            worked_hours = att_data['hours']
            
            is_on_leave = current_day in leave_dates
            if is_on_leave:
                leaves_taken_count += 1

            if worked_hours > 0:
                days_worked += 1

            if att_data['check_ins']:
                first_check_in = min(att_data['check_ins'])
                check_in_minutes = first_check_in.hour * 60 + first_check_in.minute
                total_check_in_minutes += check_in_minutes
                check_in_days_count += 1
                
                if check_in_minutes > 9 * 60:
                    late_count += 1
            
            if worked_hours < 4.5:
                is_working_day = True
                if employee.resource_calendar_id:
                    day_start = datetime.combine(current_day, time.min)
                    day_end = datetime.combine(current_day, time.max)
                    expected_hours = employee.resource_calendar_id.get_work_hours_count(day_start, day_end, compute_leaves=True, domain=None)
                    if expected_hours <= 0:
                        is_working_day = False
                
                if is_working_day and not is_on_leave:
                    absence_count += 1
            
            current_day += timedelta(days=1)

        avg_check_in = '-'
        if check_in_days_count > 0:
            avg_val = total_check_in_minutes / check_in_days_count
            avg_check_in = '{:02d}:{:02d}'.format(int(avg_val // 60), int(avg_val % 60))
            
        balance = employee.remaining_leaves if 'remaining_leaves' in employee else 0.0
        
        if absence_count > 0:
            recommendation = 'خصم (غياب)'
        elif late_count > 3:
            recommendation = 'لفت نظر'
        else:
            recommendation = 'ممتاز'

        return {
            'avg_check_in': avg_check_in, 
            'late_after_9': late_count, 
            'days_worked': days_worked,
            'absence_count': absence_count,
            'leaves_taken': leaves_taken_count,
            'balance': balance, 
            'recommendation': recommendation
        }

    # الدالة الناقصة (تم إضافتها لتفادي الايرور)
    def action_send_report(self):
        pass

    # ==========================================
    #  دالة الرواتب المعدلة (بدون استدعاء hr.contract مباشرة)
    # ==========================================
    def action_auto_generate_payroll(self):
        if 'hr.payslip' not in self.env:
            return self._show_warning('نظام الرواتب غير مثبت.')

        # 1. تحديد الموظفين (من القائمة أو الكل)
        target_employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])

        if not target_employees:
            return self._show_warning('لا يوجد موظفين.')

        payslips = self.env['hr.payslip']
        month_days = calendar.monthrange(self.date_to.year, self.date_to.month)[1]
        created_count = 0

        for emp in target_employees:
            # ========================================================
            # التعديل هنا: استخدام العقد من بروفايل الموظف مباشرة
            # ========================================================
            contract = emp.contract_id
            
            # إذا لم يكن العقد موجوداً أو ليس في حالة "مفتوح"
            if not contract or contract.state != 'open':
                continue 

            # الآن contract هو "أوبجيكت" جاهز، نقدر نصل للـ wage منه مباشرة
            # contract.wage  <--- هذا هو الراتب
            
            payslip_vals = {
                'employee_id': emp.id,
                'contract_id': contract.id,
                'date_from': self.date_from,
                'date_to': self.date_to,
                'name': f'Salary Slip - {emp.name}',
                'company_id': emp.company_id.id or self.env.company.id,
                'struct_id': contract.structure_type_id.default_struct_id.id,
            }
            
            try:
                payslip = self.env['hr.payslip'].create(payslip_vals)
                payslip.compute_sheet() 
                
                # حساب الخصم
                metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
                absence_days = metrics.get('absence_count', 0)
                
                if absence_days > 0 and contract.wage:
                    daily_wage = contract.wage / month_days
                    deduction_amount = daily_wage * absence_days
                    
                    # حقن سطر الخصم
                    ded_category = self.env['hr.salary.rule.category'].search([('code', 'in', ['DED', 'DEDUCTION'])], limit=1)
                    
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
                        'contract_id': contract.id,
                    })

                    # تعديل الصافي
                    net_line = self.env['hr.payslip.line'].search([
                        ('slip_id', '=', payslip.id),
                        ('code', '=', 'NET')
                    ], limit=1)
                    
                    if net_line:
                        new_net = net_line.amount - deduction_amount
                        net_line.write({
                            'amount': new_net,
                            'total': new_net
                        })

                payslips += payslip
                created_count += 1
            except Exception as e:
                continue

        if created_count > 0:
            return {
                'name': 'Generated Payslips',
                'domain': [('id', 'in', payslips.ids)],
                'view_mode': 'list,form',
                'res_model': 'hr.payslip',
                'type': 'ir.actions.act_window',
            }
        else:
            return self._show_warning('تنبيه: لم يتم إنشاء أي قسائم (تأكد أن الموظفين لديهم عقود سارية في ملفاتهم).')

    def _show_warning(self, msg):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'System Info',
                'message': msg,
                'type': 'warning',
                'sticky': False,
            }
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