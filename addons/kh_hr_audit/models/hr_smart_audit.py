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
        # دالة الحسابات كما هي
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

    # =========================================================
    #  دالة الرواتب الآمنة (Super Safe Mode)
    # =========================================================
    def action_auto_generate_payroll(self):
        # التحقق الأساسي فقط من Payslip
        if 'hr.payslip' not in self.env:
            return self._show_warning('نظام الرواتب غير مثبت.')

        employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])
        created_count = 0
        
        # محاولة جلب فئة الخصم مرة واحدة (اختياري)
        try:
            ded_category = self.env['hr.salary.rule.category'].sudo().search([('code', 'in', ['DED', 'DEDUCTION'])], limit=1)
        except:
            ded_category = False

        for emp in employees:
            try:
                # 1. محاولة آمنة جداً للحصول على العقد
                # نستخدم getattr لمنع ظهور الخطأ AttributeError
                contract_id = False
                
                # المحاولة أ: من حقل contract_id
                c_id = getattr(emp, 'contract_id', False)
                if c_id:
                    contract_id = c_id.id
                
                # المحاولة ب: من حقل contract_ids (الأرشيف)
                if not contract_id:
                    c_ids = getattr(emp, 'contract_ids', False)
                    if c_ids:
                        contract_id = c_ids[0].id
                
                # المحاولة ج: البحث المباشر (داخل Try لتجنب KeyError)
                if not contract_id:
                    try:
                        # نبحث في العقود إذا كان الموديل متاحاً
                        ContractEnv = self.env.get('hr.contract')
                        if ContractEnv:
                            found = ContractEnv.search([('employee_id', '=', emp.id)], limit=1, order='date_start desc')
                            if found:
                                contract_id = found.id
                    except:
                        pass

                # 2. إنشاء القسيمة (الأساسية فقط)
                payslip_vals = {
                    'employee_id': emp.id,
                    'date_from': self.date_from,
                    'date_to': self.date_to,
                    'name': f'Salary Slip - {emp.name}',
                    'company_id': emp.company_id.id or self.env.company.id,
                }
                
                # نضيف العقد فقط إذا وجدناه
                if contract_id:
                    payslip_vals['contract_id'] = contract_id

                # الإنشاء الفعلي
                payslip = self.env['hr.payslip'].create(payslip_vals)
                created_count += 1

                # 3. محاولة الحساب والخصم (اختيارية - لن توقف الإنشاء)
                try:
                    # محاولة الحساب التلقائي
                    payslip.compute_sheet()
                    
                    # محاولة حقن الخصم (فقط إذا نجح الحساب)
                    self._inject_deduction(emp, payslip, ded_category)
                except Exception as e:
                    # في حال فشل الحساب، نطبع الخطأ في اللوج لكن لا نوقف العملية
                    _logger.warning(f"Warning: Could not compute slip for {emp.name}: {e}")
                    pass

            except Exception as e:
                # خطأ قاتل في إنشاء القسيمة نفسها
                _logger.error(f"Error creating slip for {emp.name}: {e}")
                continue

        if created_count > 0:
            return {
                'name': 'Generated Payslips',
                'domain': [('id', 'in', [p.id for p in self.env['hr.payslip'].search([('date_from', '=', self.date_from)])])], # بحث عام للتأكد
                'view_mode': 'list,form',
                'res_model': 'hr.payslip',
                'type': 'ir.actions.act_window',
            }
        else:
            return self._show_warning('لم يتم إنشاء أي قسائم. راجع ملفات اللوج.')

    def _inject_deduction(self, emp, payslip, ded_category):
        """ دالة فرعية لحقن الخصم بشكل آمن """
        metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
        absence_days = metrics.get('absence_count', 0)
        
        # جلب الراتب بأمان
        wage = getattr(emp, 'wage', 0.0)
        if wage == 0.0 and payslip.contract_id and hasattr(payslip.contract_id, 'wage'):
            wage = payslip.contract_id.wage
            
        if absence_days > 0 and wage > 0:
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
            
            # تحديث الصافي
            net_line = self.env['hr.payslip.line'].search([('slip_id', '=', payslip.id), ('code', '=', 'NET')], limit=1)
            if net_line:
                new_net = net_line.amount - deduction_amount
                net_line.write({'amount': new_net, 'total': new_net})

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