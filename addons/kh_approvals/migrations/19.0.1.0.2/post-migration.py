import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # كنا سابقاً بننشئ mail.activity حقيقية للمحاسب ("💰 Collection needed: ...")
    # على المشروع مباشرة كل ما في مبلغ متبقّي غير محصّل - شيلنا هذا من الكود
    # (طلب صاحب العمل صراحةً: موضوع التحصيل صار له صفحة/جدول مستقل برّا،
    # ما بدنا نكرره كـ Activity جوا المشروع كمان). هذا سكريبت ترحيل يشتغل
    # مرة واحدة بس، يمسح أي Activity قديمة من هذا النوع لسا عالقة بالداتابيز.
    _logger.info("kh_approvals 19.0.1.0.2: حذف أنشطة التحصيل القديمة (Collection needed) من المشاريع")
    env = api.Environment(cr, SUPERUSER_ID, {})
    activities = env['mail.activity'].search([
        ('res_model', '=', 'project.project'),
        ('summary', 'like', '💰 Collection needed:'),
    ])
    if activities:
        count = len(activities)
        activities.unlink()
        _logger.info("kh_approvals 19.0.1.0.2: تم حذف %d نشاط", count)
