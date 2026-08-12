import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # النظام القديم لحساب/تحقق التحصيل عبر AI (مطابقة partner_id، وبعدين
    # التحقق عبر mcp_server على فواتير Odoo) محذوف بالكامل من الكود - هذا
    # سكريبت ترحيل يشتغل مرة واحدة بس، لحظة الترقية لهذا الإصدار، عشان
    # يمسح أي أرقام/ملاحظات قديمة متبقّية بالداتابيز من ذاك النظام (كانت
    # عالقة لأنه compute field مخزّن ما بيعيد حسابه Odoo تلقائياً إلا لو
    # اعتمادياته تغيّرت فعلياً - ومشروع بدون سطر بجدول التحصيل اليدوي،
    # اعتماديته أصلاً ما تغيّرت).
    _logger.info("kh_approvals 19.0.1.0.1: تصفير أرقام/ملاحظات التحصيل القديمة (نظام AI المحذوف)")
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env['project.project'].search([])
    if not projects:
        return

    # تصفير الأرقام المالية القديمة فوراً - compute حقيقي هلق، رح يرجع
    # يحسبها صحيح من جدول التحصيل اليدوي (صفر لو المشروع بدون سطر بعد).
    projects._compute_ai_collection_from_tracker()

    # مسح ملاحظة التحصيل القديمة (نص AI قديم بيذكر فواتير/تحقق ملغى) +
    # تصفير بصمة التغيير، عشان أول مراجعة AI جاية لكل مشروع تُعتبر تغيير
    # حقيقي (مش تُتجاهل) وتولّد ملاحظة تحصيل جديدة تعكس الواقع الجديد.
    projects.write({
        'x_ai_collection_note': False,
        'x_ai_collection_note_preview': False,
        'x_ai_change_signature': False,
    })
    _logger.info("kh_approvals 19.0.1.0.1: تم تصفير %d مشروع", len(projects))
