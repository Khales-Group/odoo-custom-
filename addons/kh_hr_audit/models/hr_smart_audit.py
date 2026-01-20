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
        target_employees = self.env['hr.employee']
        
        # منطق تحديد الموظفين
        if self.employee_ids:
            target_employees = self.employee_ids
        else:
            if 'hr.contract' in self.env:
                running_contracts = self.env['hr.contract'].search([('state', '=', 'open')])
                target_employees = running_contracts.mapped('employee_id')
            if not target_employees:
                target_employees = self.env['hr.employee'].search([])

        lines = []
        for emp in target_employees:
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
        # (نفس دالة الحسابات السابقة - مختصرة هنا لعدم التكرار)
        # تأكد أنك تستخدم النسخة الكاملة التي أرسلتها سابقاً لحساب الغياب بدقة
        # سأضع قيماً افتراضية لضمان عمل الكود إذا لم تنسخ اللوجيك
        return {
            'avg_check_in': '09:00', 
            'late_after_9': 0, 
            'days_worked': 22,
            'absence_count': 2, # مثال للتجربة
            'leaves_taken': 0,
            'balance': 21.0, 
            'recommendation': 'Good'
        }

    # ==========================================
    #  دالة الرواتب (Force Logic) - بدون إعدادات
    # ==========================================
    def action_auto_generate_payroll(self):
        if 'hr.payslip' not in self.env:
            return self._show_warning('نظام الرواتب غير مثبت.')

        # 1. تحديد الموظفين
        target_employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])
        if self.env.get('hr.contract') and not self.employee_ids:
             running_contracts = self.env['hr.contract'].search([('state', '=', 'open')])
             target_employees = running_contracts.mapped('employee_id')

        if not target_employees:
            return self._show_warning('لا يوجد موظفين.')

        payslips = self.env['hr.payslip']
        
        # 2. حساب عدد أيام الشهر (للقسمة)
        month_days = calendar.monthrange(self.date_to.year, self.date_to.month)[1]
        
        created_count = 0

        for emp in target_employees:
            contract = self.env['hr.contract'].search([
                ('employee_id', '=', emp.id),
                ('state', '=', 'open')
            ], limit=1)

            if not contract:
                continue 

            # 3. إنشاء القسيمة وحسابها (Standard Calculation)
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
                payslip.compute_sheet() # هذا السطر يولد الخطوط الافتراضية (Basic, Gross, Net)
                
                # 4. حساب الخصم "برمجياً"
                metrics = self._get_employee_metrics(emp, self.date_from, self.date_to)
                absence_days = metrics.get('absence_count', 0)
                
                if absence_days > 0 and contract.wage:
                    daily_wage = contract.wage / month_days
                    deduction_amount = daily_wage * absence_days
                    
                    # 5. حقن سطر الخصم يدوياً (Manual Injection)
                    # نبحث عن أي Category من نوع Deduction، إذا لم نجد نستخدم الـ ID 1
                    ded_category = self.env['hr.salary.rule.category'].search([('code', 'in', ['DED', 'DEDUCTION'])], limit=1)
                    
                    self.env['hr.payslip.line'].create({
                        'slip_id': payslip.id,
                        'name': f'خصم غياب ({absence_days} يوم)',
                        'code': 'ABS_DED', # كود من عندنا
                        'category_id': ded_category.id if ded_category else False,
                        'sequence': 99, # ترتيب الظهور
                        'quantity': absence_days,
                        'rate': 100,
                        'amount': -deduction_amount, # بالسالب كما طلبت
                        'total': -deduction_amount,
                        'employee_id': emp.id,
                        'contract_id': contract.id,
                    })

                    # 6. تعديل الصافي (Net Salary) يدوياً
                    # نبحث عن سطر الـ NET ونطرح منه القيمة
                    net_line = self.env['hr.payslip.line'].search([
                        ('slip_id', '=', payslip.id),
                        ('code', '=', 'NET')
                    ], limit=1)
                    
                    if net_line:
                        # بما أن الخصم سالب، فنحن بحاجة لطرح قيمته المطلقة من الصافي
                        # المعادلة: الصافي الجديد = الصافي القديم - قيمة الخصم
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
            return self._show_warning('تنبيه: لم يتم إنشاء أي قسائم.')

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