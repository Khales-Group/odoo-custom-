# -*- coding: utf-8 -*-
from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    # بانر تحديث/صيانة عام - بيظهر أول ما يفتح أي يوزر أي تطبيق بـ Odoo
    # (مش مرتبط بموديل/تطبيق معيّن)، لأنه منضيفه على session_info نفسها
    # يلي بتتحمّل مرة وحدة لحظة فتح الـ Backend، وبنقرأها بالـ JS بمكوّن
    # عام (main_components) بيضل ظاهر بغض النظر شو فاتح المستخدم.
    # التفعيل/التعديل من Settings > Technical > System Parameters بمفتاحين:
    #   kh_approvals.maintenance_banner_active   -> True / False
    #   kh_approvals.maintenance_banner_message  -> نص الرسالة
    def session_info(self):
        info = super().session_info()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('kh_approvals.maintenance_banner_active') == 'True':
            info['kh_maintenance_banner'] = ICP.get_param(
                'kh_approvals.maintenance_banner_message'
            ) or 'النظام في حالة تحديث حالياً - ممكن تشوف بعض الأشياء غير مستقرة مؤقتاً.'
        else:
            info['kh_maintenance_banner'] = False
        return info
