# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ProjectProject(models.Model):
    _inherit = 'project.project'

    # 1. الحقل الجديد الذي تريد إضافته
    contractor_email = fields.Char(string="Contractor Email")

    # 2. حقل منطقي (Boolean) لمعرفة هل المستخدم الحالي هو المدير أم لا
    is_current_user_manager = fields.Boolean(
        string="Is Current User Manager",
        compute='_compute_is_current_user_manager',
        store=False  # لا نحتاج لتخزينه في قاعدة البيانات، يتم حسابه لحظياً
    )

    @api.depends('user_id')
    def _compute_is_current_user_manager(self):
        for project in self:
            # إذا كان المستخدم الحالي (self.env.user) هو مدير المشروع (project.user_id)
            if project.user_id == self.env.user:
                project.is_current_user_manager = True
            else:
                project.is_current_user_manager = False