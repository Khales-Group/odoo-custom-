from odoo import models, fields, api
from odoo.exceptions import UserError

class ProjectProject(models.Model):
    _inherit = 'project.project'

    contractor_email = fields.Char(string="Contractor Email")

    is_manager = fields.Boolean(compute='_compute_is_manager')

    @api.depends('user_id')
    def _compute_is_manager(self):
        for rec in self:
            rec.is_manager = (rec.user_id == self.env.user)

    def write(self, vals):
        # قائمة بالحقول التي نريد حمايتها
        protected_fields = ['contractor_email', 'partner_id', 'date_start']

        for project in self:
            # التحقق: هل المستخدم الحالي هو المدير؟
            is_manager = project.user_id == self.env.user
            
            # التحقق: هل المستخدم يحاول تعديل أحد الحقول المحمية؟
            # نقوم بفحص ما إذا كان أي من الحقول المحمية موجوداً في القيم المرسلة للتعديل (vals)
            trying_to_edit_protected = any(field in vals for field in protected_fields)

            # إذا لم يكن المدير + ويحاول تعديل حقول محمية => اظهر خطأ
            if not is_manager and trying_to_edit_protected:
                raise UserError("عذراً! لا يمكنك تعديل هذه البيانات لأنك لست مدير المشروع.")

        return super(ProjectProject, self).write(vals)