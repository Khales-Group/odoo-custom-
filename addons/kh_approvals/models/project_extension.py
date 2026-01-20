from odoo import models, fields, api

class ProjectProject(models.Model):
    _inherit = 'project.project'

    contractor_email = fields.Char(string="Contractor Email")

    # حقل "شرطي" مخفي وظيفته الوحيدة هي الحماية
    is_manager = fields.Boolean(compute='_compute_is_manager')

    @api.depends('user_id')
    def _compute_is_manager(self):
        for rec in self:
            # الشرط: هل المستخدم الحالي == مدير المشروع؟
            # يمكنك إضافة 'or self.env.user.has_group("base.group_system")' للسماح للآدمن أيضاً
            rec.is_manager = (rec.user_id == self.env.user)