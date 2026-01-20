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
        # جلب الموظفين
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
        attendances = self.env['hr.attendance'].search([('employee_id', '=', employee.id), ('check_in', '>=', start_dt), ('check_in', '<=', end_dt)])
        leaves = self.env['hr.leave'].search([('employee_id', '=', employee.id), ('state', '=', 'validate'), ('request_date_from', '<=', date_to), ('request_date_to', '>=', date_from)])
        
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
        attendance_by_date = {}
        for att in attendances:
            if not att.check_in: continue
            local_check_in = fields.Datetime.context_timestamp(self, att.check_in)
            local_date = local_check_in.date()
            if local_date not in attendance_by_date: attendance_by_date[local_date] = {'hours': 0.0, 'check_ins': []}
            attendance_by_date[local_date]['check_ins'].append(local_check_in)
            if att.check_out: attendance_by_date[local_date]['hours'] += (att.check_out - att.check_in).total_seconds() / 3600.0

        current_day = date_from
        while current_day <= date_to:
            att_data = attendance_by_date.get(current_day, {'hours': 0.0, 'check_ins': []})
            worked_hours = att_data['hours']
            if current_day in leave_dates: leaves_taken_count += 1
            if worked_hours > 0: days_worked += 1
            if att_data['check_ins']:
                first = min(att_data['check_ins'])
                mins = first.hour * 60 + first.minute
                total_check_in_minutes += mins
                check_in_days_count += 1
                if mins > 9 * 60: late_count += 1
            if worked_hours < 4.5:
                is_working = True
                if employee.resource_calendar_id:
                    expected = employee.resource_calendar_id.get_work_hours_count(datetime.combine(current_day, time.min), datetime.combine(current_day, time.max), compute_leaves=True)
                    if expected <= 0: is_working = False
                if is_working and current_day not in leave_dates: absence_count += 1
            current_day += timedelta(days=1)
        avg = '-'
        if check_in_days_count > 0:
            val = total_check_in_minutes / check_in_days_count
            avg = '{:02d}:{:02d}'.format(int(val // 60), int(val % 60))
        return {'avg_check_in': avg, 'late_after_9': late_count, 'days_worked': days_worked, 'absence_count': absence_count, 'leaves_taken': leaves_taken_count, 'balance': employee.remaining_leaves if 'remaining_leaves' in employee else 0.0, 'recommendation': ''}

    def action_send_report(self):
        pass

    # ==========================================
    #  دالة الرواتب (بدون hr.contract نهائياً)
    # ==========================================
    def action_auto_generate_payroll(self):
        if 'hr.payslip' not in self.env:
            return self._show_warning('نظام الرواتب غير مثبت.')

        employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])
        payslips = self.env['hr.payslip']
        month_days = calendar.monthrange(self.date_to.year, self.date_to.month)[1]
        
        # حماية ضد نقص الفئات
        ded_category = self.env['hr.salary.rule.category'].search([('code', 'in', ['DED', 'DEDUCTION'])], limit=1)
        
        created_count = 0
        errors = []

        for emp in employees:
            try:
                # 1. محاولة الحصول على العقد من حقل الموظف فقط
                # (ممنوع استخدام self.env['hr.contract'] لأنه يسبب الكراش)
                contract = False
                if 'contract_id' in emp._fields and emp.contract_id:
                    contract = emp.contract_id
                
                # إذا لم نجد العقد المباشر، نحاول البحث في القائمة (contract_ids)
                if not contract and 'contract_ids' in emp._fields and emp.contract_ids:
                    # نأخذ أول واحد بوجهنا
                    contract = emp.contract_ids[0]

                # 2. تجهيز بيانات القسيمة
                payslip_vals = {
                    'employee_id': emp.id,
                    'date_from': self.date_from,
                    'date_to': self.date_to,
                    'name': f'Salary Slip - {emp.name}',
                    'company_id': emp.company_id.id or self.env.company.id,
                    # إذا لقينا عقد بنحطه، ما لقينا بنحط False وبنخلي السيستم يجرب
                    'contract_id': contract.id if contract else False,
                }
                
                # محاولة إضافة الهيكل إذا كان موجود في العقد
                if contract and 'structure_type_id' in contract._fields and contract.structure_type_id:
                     if contract.structure_type_id.default_struct_id:
                         payslip_vals['struct_id'] = contract.structure_type_id.default_struct_id.id

                # 3. إنشاء القسيمة
                payslip = self.env['hr.payslip'].create(payslip_vals)

                # 4. محاولة الحساب (Compute)
                try:
                    payslip.compute_sheet()
                except:
                    pass

                # 5. حقن الخصم (من راتب الموظف)
                metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
                absence_days = metrics.get('absence_count', 0)
                
                # جلب الراتب من الموظف (آمن جداً)
                wage = getattr(emp, 'wage', 0.0)
                
                # إذا الموظف ما عنده راتب بملفه، بنجرب العقد (إذا كان موجود)
                if wage == 0.0 and contract and hasattr(contract, 'wage'):
                    wage = contract.wage
                
                if absence_days > 0 and wage > 0:
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
                        'contract_id': contract.id if contract else False,
                    })
                    
                    # تحديث الصافي
                    net_line = self.env['hr.payslip.line'].search([
                        ('slip_id', '=', payslip.id),
                        ('code', '=', 'NET')
                    ], limit=1)
                    
                    if net_line:
                        new_net = net_line.amount - deduction_amount
                        net_line.write({'amount': new_net, 'total': new_net})
                
                payslips += payslip
                created_count += 1

            except Exception as e:
                errors.append(f"{emp.name}: {str(e)}")
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
            msg = "\n".join(errors[:5])
            if not msg: msg = "فشل غير محدد، تأكد من وجود صلاحيات."
            return self._show_warning(f'لم يتم إنشاء قسائم.\nالأخطاء:\n{msg}')

    def _show_warning(self, msg):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'نتيجة العملية',
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