from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

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
                'leave_balance': metrics.get('balance', 0.0),
                'recommendation': metrics.get('recommendation', ''),
                'status': 'danger' if metrics.get('late_after_9', 0) > 3 else 'success'
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
        # دالة وهمية مبدئياً عشان ما يضرب ايرور، لاحقاً بنحط اللوجيك المعقد
        return {
            'avg_check_in': '08:55', 
            'late_after_9': 0, 
            'balance': 21.0, 
            'recommendation': 'Good'
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
    leave_balance = fields.Float(string='رصيد إجازات')
    recommendation = fields.Char(string='توصية')
    status = fields.Selection([('success', 'Good'), ('danger', 'Bad')], string='الحالة')