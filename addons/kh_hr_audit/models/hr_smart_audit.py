from odoo import models, fields, api
from odoo.exceptions import UserError
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

    # =========================================================
    #  الدماغ المحرك: دالة الحسابات الدقيقة
    # =========================================================
    def _get_employee_metrics(self, employee, date_from, date_to):
        # توحيد التوقيت
        start_dt = datetime.combine(date_from, time.min)
        end_dt = datetime.combine(date_to, time.max)
        
        # 1. جلب الحضور (Attendance)
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', start_dt),
            ('check_in', '<=', end_dt)
        ])
        
        # تجميع ساعات العمل حسب اليوم
        attendance_by_date = {}
        for att in attendances:
            if not att.check_in: continue
            # نعتمد على تاريخ الدخول لتحديد اليوم
            check_in_date = att.check_in.date()
            
            if check_in_date not in attendance_by_date:
                attendance_by_date[check_in_date] = {'hours': 0.0, 'check_ins': []}
            
            # حفظ وقت الدخول لحساب التأخير
            local_check_in = fields.Datetime.context_timestamp(self, att.check_in)
            attendance_by_date[check_in_date]['check_ins'].append(local_check_in)
            
            # حساب ساعات العمل
            if att.check_out:
                duration = (att.check_out - att.check_in).total_seconds() / 3600.0
                attendance_by_date[check_in_date]['hours'] += duration

        # 2. جلب الإجازات المعتمدة (Time Off)
        # نستخدم search بدقة للتداخل
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'), # فقط المعتمدة
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from)
        ])
        
        # تخزين تواريخ الإجازات في Set لسرعة البحث
        leave_dates = set()
        for leave in leaves:
            curr = max(leave.request_date_from, date_from)
            end = min(leave.request_date_to, date_to)
            while curr <= end:
                leave_dates.add(curr)
                curr += timedelta(days=1)

        # 3. المتغيرات للعد
        late_count = 0
        days_worked = 0
        absence_count = 0
        leaves_taken_count = 0 
        total_check_in_minutes = 0
        check_in_days_count = 0

        # 4. الحلقة الزمنية (يوم بيوم)
        current_day = date_from
        while current_day <= date_to:
            # هل الموظف في إجازة معتمدة اليوم؟
            is_on_leave = current_day in leave_dates
            
            # بيانات الحضور لهذا اليوم
            att_data = attendance_by_date.get(current_day, {'hours': 0.0, 'check_ins': []})
            worked_hours = att_data['hours']
            
            # --- السيناريو 1: الموظف في إجازة ---
            if is_on_leave:
                leaves_taken_count += 1
                # حتى لو داوم ساعتين وهو مجاز، لا نحسبه غياب ولا نحسبه تأخير
                # ننتقل لليوم التالي فوراً
                current_day += timedelta(days=1)
                continue 

            # --- السيناريو 2: هل هو يوم عمل رسمي؟ ---
            # نفحص جدول العمل (Resource Calendar) لنتأكد أنه ليس عطلة أسبوعية أو رسمية
            is_working_day = True
            if employee.resource_calendar_id:
                # هذه الدالة تعيد عدد الساعات المتوقعة (0 تعني عطلة)
                expected_hours = employee.resource_calendar_id.get_work_hours_count(
                    datetime.combine(current_day, time.min),
                    datetime.combine(current_day, time.max),
                    compute_leaves=True
                )
                if expected_hours <= 0:
                    is_working_day = False
            
            # إذا كان عطلة (جمعة/سبت/عيد)، ولم يداوم، لا نحسب شيء
            if not is_working_day and worked_hours == 0:
                current_day += timedelta(days=1)
                continue

            # --- السيناريو 3: الموظف داوم ---
            if worked_hours > 0:
                # نعتبره يوم عمل
                days_worked += 1
                
                # حساب التأخير (فقط في أيام العمل الفعلية)
                if att_data['check_ins']:
                    first_check_in = min(att_data['check_ins'])
                    # تحويل الوقت لدقائق (مثلاً 09:15 = 555 دقيقة)
                    mins = first_check_in.hour * 60 + first_check_in.minute
                    total_check_in_minutes += mins
                    check_in_days_count += 1
                    
                    # شرط التأخير (بعد الساعة 9:00 صباحاً)
                    # 9 * 60 = 540 دقيقة
                    if mins > 540: 
                        late_count += 1

                # فحص "الدوام الناقص" (Short Attendance)
                # إذا داوم أقل من 4 ساعات وهو يوم عمل وليس في إجازة -> قد نعتبره نصف يوم غياب
                # (يمكنك تعديل الرقم 4.0 حسب سياسة الشركة)
                if worked_hours < 4.0 and is_working_day:
                     # هنا نعتبره غياب غير مبرر (أو نصف غياب حسب رغبتك)
                     # الكود الحالي سيحسبه غياب لأنه لم يكمل النصاب
                     absence_count += 1

            # --- السيناريو 4: الموظف لم يداوم (0 ساعات) في يوم عمل ---
            else:
                if is_working_day:
                    absence_count += 1

            current_day += timedelta(days=1)

        # حساب معدل الدخول
        avg_check_in = '-'
        if check_in_days_count > 0:
            avg_val = total_check_in_minutes / check_in_days_count
            avg_check_in = '{:02d}:{:02d}'.format(int(avg_val // 60), int(avg_val % 60))
            
        return {
            'avg_check_in': avg_check_in, 
            'late_after_9': late_count, 
            'days_worked': days_worked, 
            'absence_count': absence_count, 
            'leaves_taken': leaves_taken_count, 
            'balance': employee.remaining_leaves if 'remaining_leaves' in employee else 0.0, 
            'recommendation': 'خصم' if absence_count > 0 else 'جيد'
        }

    def action_send_report(self):
        pass

    # =========================================================
    #  دالة الرواتب (تعمل بـ Safe Mode)
    # =========================================================
    def action_auto_generate_payroll(self):
        if 'hr.payslip' not in self.env:
            return self._show_warning('نظام الرواتب غير مثبت.')

        employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])
        created_count = 0
        
        try:
            ded_category = self.env['hr.salary.rule.category'].sudo().search([('code', 'in', ['DED', 'DEDUCTION'])], limit=1)
        except:
            ded_category = False

        for emp in employees:
            try:
                # الحصول على العقد بأمان
                contract_id = False
                c_id = getattr(emp, 'contract_id', False)
                if c_id: contract_id = c_id.id
                if not contract_id:
                    c_ids = getattr(emp, 'contract_ids', False)
                    if c_ids: contract_id = c_ids[0].id
                
                # البحث المباشر كحل أخير
                if not contract_id:
                    ContractEnv = self.env.get('hr.contract')
                    if ContractEnv:
                        found = ContractEnv.search([('employee_id', '=', emp.id)], limit=1, order='date_start desc')
                        if found: contract_id = found.id

                # إنشاء القسيمة
                payslip_vals = {
                    'employee_id': emp.id,
                    'date_from': self.date_from,
                    'date_to': self.date_to,
                    'name': f'Salary Slip - {emp.name}',
                    'company_id': emp.company_id.id or self.env.company.id,
                }
                if contract_id: payslip_vals['contract_id'] = contract_id

                payslip = self.env['hr.payslip'].create(payslip_vals)
                created_count += 1

                # الحساب والخصم
                try:
                    payslip.compute_sheet()
                    self._inject_deduction(emp, payslip, ded_category)
                except Exception as e:
                    _logger.warning(f"Calculation skipped for {emp.name}: {e}")
                    pass

            except Exception as e:
                _logger.error(f"Error for {emp.name}: {e}")
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
        """ دالة حقن الخصم بناءً على الغياب غير المبرر فقط """
        metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
        absence_days = metrics.get('absence_count', 0)
        
        # لا نخصم إذا كان 0 غياب
        if absence_days <= 0:
            return

        wage = getattr(emp, 'wage', 0.0)
        if wage == 0.0 and payslip.contract_id and hasattr(payslip.contract_id, 'wage'):
            wage = payslip.contract_id.wage
            
        if wage > 0:
            month_days = calendar.monthrange(self.date_to.year, self.date_to.month)[1]
            daily_wage = wage / month_days
            deduction_amount = daily_wage * absence_days
            
            self.env['hr.payslip.line'].create({
                'slip_id': payslip.id,
                'name': f'خصم غياب غير مبرر ({absence_days} يوم)',
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