# -*- coding: utf-8 -*-
# ============================================================
#  مدير المشاريع الذكي (AI Project Manager)
#  الأرقام والقوائم (تاسكات مفتوحة/متأخرة، أكتفيتيز متأخرة، إسناد المهام،
#  التحصيل المالي) محسوبة تلقائياً بالكود وتظهر فوراً بدون أي زر - مافي
#  شي منها يحتاج استدعاء AI. زر "🤖 تشغيل مراجعة AI" الوحيد المطلوب هو
#  فقط للجزء المكلف: تحليل Claude النصي (تقييم الحالة + الخطوات التالية).
# ============================================================
import json
import logging
import re
import time
from collections import defaultdict

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext
from odoo.tools.safe_eval import safe_eval

# نعيد استخدام نفس محرّك الأدوات تبع الشات العام (mcp_server) للتحقق المالي -
# هذا المحرّك أثبت فعلياً إنه بيجيب الأرقام الصحيحة (find_customer +
# search_records على account.move)، بعكس منطقنا الحتمي بالأسفل (مطابقة
# partner_id مباشرة) يلي ثبت إنه غلط 3 مرات على بيانات حقيقية. القرار (من
# صاحب العمل): "بلاش نحسب مالياً بمنطقنا - خلي Claude يستخدم نفس أدوات
# الشات العام يلي جابت الرقم الصحيح فعلياً، وحطها بتبع المدير الذكي".
from odoo.addons.mcp_server.controllers import ai_tools as mcp_ai_tools

_logger = logging.getLogger(__name__)

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    _logger.warning("KH_AI_MANAGER: anthropic package not installed.")

DIGEST_DAYS = 60
DEFAULT_MODEL = 'claude-opus-4-8'
DONE_STATES = ('03_approved', '1_done', '1_canceled')
MAX_AGENTIC_ITERATIONS = 9
# لو دورة الدفعة (كل المشاريع) أخذت أكتر من هذا الوقت، منوقف نفسنا بلطف
# (commit لكل يلي خلص، ونوقف) بدل ما ننتظر السيرفر يقتلنا هو (Worker
# Timeout) بمنتصف مشروع - توقف نظيف بمنتصف الدفعة أفضل من قطع قسري بدون
# أي تحكم. الترتيب حسب الأقدم مراجعة (_kh_ai_target_projects) بيضمن إنه
# المشاريع يلي ما وصلها الدور هالمرة، هي أول يلي بتاخد الأولوية الدورة الجاية.
CRON_BATCH_TIME_BUDGET_SECONDS = 240
# جزء من "بصمة" التغيير (_kh_ai_build_change_signature) - لو عدّلنا البرومبت/
# الـ schema بشكل بيغيّر النتيجة المتوقعة (متل تقوية next_steps هلق)، لازم
# نرفع هذا الرقم. هيك أي مشروع (حتى لو ما تغيّر عليه أي شي فعلياً) بتتغيّر
# بصمته تلقائياً وبتاخد مراجعة فعلية جديدة بالـ Cron العادي - بدون ما نحتاج
# نطلب من المستخدم يفرض (force) المراجعة يدوياً لكل مشروع قديم لحاله.
_KH_AI_PROMPT_VERSION = 6

# نماذج مسموحة للأداة الاستكشافية (Agentic) - قراءة فقط، بدون أي كتابة/حذف.
# هذا نطاق مخصّص لهذا الفيتشر بس (منفصل بالكامل عن mcp_server وحظره الصارم
# لـ account.*/purchase.* - هون كل هذا مفتوح لمدير المشاريع الذكي بقرار واعي
# من الإدارة، لكن قراءة بس دايماً).
KH_AI_TOOL_MODELS = (
    'project.project', 'project.task', 'mail.activity', 'mail.message',
    'account.move', 'account.move.line', 'account.analytic.account',
    'purchase.order', 'purchase.order.line',
    'crm.lead', 'kh.approval.request', 'res.partner',
)


class ProjectAiManager(models.Model):
    _inherit = 'project.project'

    # ---- محسوبة، ومخزّنة (store=True) - لازم store عشان نقدر نستخدمها
    # بـ domain فلترة (بطاقة "التحصيل")، الحقل غير المخزّن ما بينحوّل SQL.
    # بتنعمل fresh عند كل تشغيل مراجعة AI (يدوي أو الـ Cron الساعي) - مش
    # عند كل فتح صفحة (كانت هيك قبل، بس هذا أرخص وأسرع لعرض القوائم). ----
    x_ai_work_done = fields.Float(
        string="نسبة الإنجاز حسب Odoo (AI)", compute='_compute_ai_financials', store=True)
    x_ai_contract_value = fields.Float(
        string="قيمة العقد (AI)", compute='_compute_ai_financials', store=True)
    # ملاحظة مهمة: هذول التلاتة تحت مش compute fields (عمداً) - قيمتهم
    # الموثوقة الوحيدة جايّة من التحقق المالي الحقيقي عبر mcp_server
    # (_kh_ai_apply_financial_verification)، مش من حساب حتمي بالكود (ثبت
    # غلطه مرات عديدة على بيانات حقيقية - راجع _kh_ai_verify_financials_via_mcp).
    # لو كانوا compute fields مرتبطين بـ _compute_ai_financials، كل تشغيل
    # مراجعة (كل ربع ساعة) كان رح "يصفّرهم"/يرجّعهم لتخمين حتمي غلط قبل ما
    # يُعاد التحقق المالي (المخفّف لمرة كل 24 ساعة) - يعني الرقم الصحيح كان
    # يظهر لحظة التحقق وبعدها يرجع يتبدّل بالغلط الساعة اللي بعدها. هلق
    # بيبقوا كما هم بالضبط لحد ما تحقق مالي جديد يعدّلهم فعلياً.
    x_ai_invoiced_amount = fields.Float(string="المفوتر (AI)", readonly=True, copy=False)
    x_ai_collected_amount = fields.Float(string="المحصّل فعلياً (AI)", readonly=True, copy=False)
    x_ai_outstanding_amount = fields.Float(string="المتبقّي غير المحصّل (AI)", readonly=True, copy=False)
    x_ai_financial_data_note = fields.Char(
        string="ملاحظة بيانات مالية", compute='_compute_ai_financials', store=True)

    x_ai_work_done_tasks = fields.Float(
        string="نسبة الإنجاز حسب التاسكات (AI)", compute='_compute_ai_task_metrics', store=True)
    x_ai_open_tasks_count = fields.Integer(
        string="تاسكات مفتوحة (AI)", compute='_compute_ai_task_metrics', store=True)
    x_ai_overdue_tasks_count = fields.Integer(
        string="تاسكات متأخرة (AI)", compute='_compute_ai_task_metrics', store=True)
    x_ai_overdue_activities_count = fields.Integer(
        string="أكتفيتيز متأخرة (AI)", compute='_compute_ai_task_metrics', store=True)
    x_ai_assignment_summary = fields.Html(
        string="إسناد المهام (AI)", compute='_compute_ai_task_metrics', store=True, sanitize=False)
    x_ai_debug_note = fields.Char(
        string="🔍 تشخيص مؤقت (AI)", compute='_compute_ai_task_metrics', store=True)

    # ---- قوائم التاسكات المفلترة فعلياً بالكود (مش عبر domain على task_ids -
    # الأخير بيعرض كل التاسكات المرتبطة بالمشروع بدون فلترة فعلية بفورم الـ
    # one2many مهما حددنا domain، فاستبدلناها بحقول Many2many محسوبة تحتوي
    # فقط على الـ ids الصحيحة). ---
    x_ai_overdue_task_ids = fields.Many2many(
        'project.task', compute='_compute_ai_task_metrics', string="التاسكات المتأخرة (AI)")
    x_ai_next_task_ids = fields.Many2many(
        'project.task', compute='_compute_ai_task_metrics', string="التاسكات التالية (AI)")
    x_ai_done_task_ids = fields.Many2many(
        'project.task', compute='_compute_ai_task_metrics', string="التاسكات المنجزة (AI)")

    # ---- الوحيدة يلي بتحتاج استدعاء Claude فعلي - بتتحدّث تلقائياً كل ساعة
    # (Cron) أو فوراً لو ضغطت الزر، بدون أي Spam على الشاتر (الشاتر بس
    # بالتقرير الأسبوعي) ----
    x_ai_last_review_date = fields.Datetime(string="آخر مراجعة AI", readonly=True, copy=False)
    # آخر مرة صار فيها فعلياً تحقق مالي حقيقي عبر mcp_server (حلقة Agentic
    # مكلفة وبطيئة) - منفصل عن x_ai_last_review_date لأنه هذا الجزء بس
    # بدنا نخفّف وتيرته لمرة/يوم، بعكس المراجعة الرئيسية (ملخّص/تنبيهات/
    # خطوات) يلي لازم تبقى كل ساعة.
    x_ai_last_financial_check_date = fields.Datetime(string="آخر تحقق مالي حقيقي (AI)", readonly=True, copy=False)
    # "بصمة" الوضع الحالي (تاسكات مفتوحة/متأخرة/أكتفيتيز متأخرة/تاسكات
    # راكدة/آخر رسالة شاتر/آخر تعديل تاسك/المتبقّي المالي) وقت آخر مراجعة
    # AI ناجحة - لو نفس البصمة لسا هي هي، يعني ما صار أي جديد حقيقي على
    # المشروع، فمنتجنّب استدعاء Claude (مكلف وبطيء) بلا فايدة ونحتفظ بنفس
    # النتيجة القديمة. مجرد نص داخلي (مش معروض بالواجهة).
    x_ai_change_signature = fields.Char(readonly=True, copy=False)
    x_ai_today_summary = fields.Html(string="ملخّص اليوم (AI)", readonly=True, copy=False, sanitize=False)
    x_ai_collection_note = fields.Html(string="التحصيل مع المحاسب (AI)", readonly=True, copy=False, sanitize=False)
    x_ai_alerts = fields.Html(string="التنبيهات (AI)", readonly=True, copy=False, sanitize=False)
    x_ai_next_steps = fields.Html(string="الخطوات التالية المقترحة (AI)", readonly=True, copy=False, sanitize=False)
    # معاينات نصية بسيطة (بدون HTML) - لعرض نظيف بالـ List views (عرض HTML
    # خام جوا خلية List بيطلع فيه وسم <style> مكرّر بكل صف، شكله مش منظّم).
    x_ai_today_summary_preview = fields.Char(string="معاينة ملخّص اليوم", readonly=True, copy=False)
    x_ai_collection_note_preview = fields.Char(string="معاينة التحصيل", readonly=True, copy=False)
    x_ai_alerts_preview = fields.Char(string="معاينة التنبيهات", readonly=True, copy=False)
    x_ai_next_steps_preview = fields.Char(string="معاينة الخطوات التالية", readonly=True, copy=False)

    # ------------------------------------------------------------------
    # اكتشاف حقول Odoo Studio ديناميكياً (اسمها التقني مش موجود بالكود،
    # موجود بس بالداتابيز الحية) - نفس أسلوب proj_html_fields المستخدم
    # بـ khales_ai_report.py، معمّم لأي وصف/نوع حقل.
    # ------------------------------------------------------------------
    def _kh_ai_find_studio_field(self, keywords, ttypes):
        Fields = self.env['ir.model.fields'].sudo()
        candidates = Fields.search([('model', '=', 'project.project'), ('ttype', 'in', ttypes)])
        kw_low = [k.lower() for k in keywords]
        for f in candidates:
            desc = (f.field_description or '').lower()
            name = (f.name or '').lower()
            if any(k in desc or k in name for k in kw_low):
                return f.name
        return False

    def _kh_ai_read_studio_value(self, field_name):
        if not field_name or field_name not in self._fields:
            return False
        try:
            return self[field_name]
        except Exception:
            return False

    def _kh_ai_analytic_account_field_name(self):
        for fname, f in self._fields.items():
            if f.type == 'many2one' and getattr(f, 'comodel_name', None) == 'account.analytic.account':
                return fname
        return False

    # ------------------------------------------------------------------
    # اكتشاف المحاسب "Karan" ديناميكياً بالاسم (مش id ثابت بالكود) - عشان
    # لو تغيّر شي بالنظام ما ينكسر، ولأننا ما نعرف id الحقيقي أصلاً.
    # ------------------------------------------------------------------
    def _kh_ai_find_accountant_user(self):
        return self.env['res.users'].sudo().search([('name', 'ilike', 'karan')], limit=1)

    # ------------------------------------------------------------------
    # اكتشاف المدير العام ديناميكياً بالاسم (مش id ثابت) - نفس أسلوب
    # الاكتشاف تبع المحاسب فوق. شرطين (Majed + Alkindi) بدل الاسم الكامل
    # تفادياً لأي فرق بالتشكيل/الترتيب بالاسم المسجّل فعلياً بـ Odoo.
    # ------------------------------------------------------------------
    def _kh_ai_find_general_manager(self):
        return self.env['res.users'].sudo().search([
            ('name', 'ilike', 'Majed'), ('name', 'ilike', 'Alkindi'),
        ], limit=1)

    # ------------------------------------------------------------------
    # فحوصات استباقية بالكود (مش بانتظار Claude يلاحظها): مشروع بدون أي
    # تحديث/زيارة ميدانية موثّقة بالشاتر منذ فترة، وتاسكات مفتوحة ما تحرّكت
    # (write_date) منذ فترة طويلة - "معلومات مش موجودة" و"تاسكات ما تحدّثت".
    # ------------------------------------------------------------------
    def _kh_ai_check_staleness(self, open_tasks):
        self.ensure_one()
        last_msg = self.env['mail.message'].sudo().search([
            ('model', '=', 'project.project'),
            ('res_id', '=', self.id),
            ('message_type', 'in', ['comment', 'email']),
        ], order='date desc', limit=1)
        days_since_update = None
        if last_msg and last_msg.date:
            days_since_update = (fields.Datetime.now() - last_msg.date).days

        now = fields.Datetime.now()
        stale_tasks = open_tasks.filtered(
            lambda t: t.write_date and (now - t.write_date).days >= 14)

        return days_since_update, stale_tasks

    # ------------------------------------------------------------------
    # نشاط فعلي داخل التاسكات - نوتس (شاتر على التاسك نفسه، مش على المشروع)
    # وساعات تايمشيت مسجّلة. قبل هذا، الديجست كان يقرا شاتر المشروع بس
    # ويتجاهل كلياً أي نوت/تايمشيت مسجّل جوا تاسك لحاله - فجوة حقيقية (موظف
    # ممكن يكتب تفاصيل دقيقة جوا التاسك وين النظام "ما بيشوفها"). النطاق:
    # أي تاسك عليه مسؤول (assign) - بدون شرط مفتوح/مغلق أو مدة زمنية (بطلب
    # صاحب العمل تحديداً) - وبس التاسكات يلي فعلياً فيها نوت أو ساعات
    # مسجّلة تظهر بالنص (تاسك مسندة وهادئة تماماً مش مفيدة نكررها هون).
    # ------------------------------------------------------------------
    def _kh_ai_build_task_activity_digest(self, all_tasks, limit=60):
        candidate_tasks = all_tasks.filtered(lambda t: t.user_ids)
        if not candidate_tasks:
            return ''

        notes_by_task = {}
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'project.task'),
            ('res_id', 'in', candidate_tasks.ids),
            ('message_type', 'in', ['comment', 'email']),
        ], order='date desc')
        for m in messages:
            if m.res_id in notes_by_task:
                continue
            text = html2plaintext(m.body or '').strip()
            if text:
                notes_by_task[m.res_id] = (text[:300], str(m.date)[:16])

        hours_by_task = {}
        if 'timesheet_ids' in candidate_tasks._fields:
            Timesheet = self.env['account.analytic.line'].sudo()
            lines = Timesheet.search([('task_id', 'in', candidate_tasks.ids)])
            for line in lines:
                hours_by_task[line.task_id.id] = hours_by_task.get(line.task_id.id, 0.0) + line.unit_amount

        rows = []
        for t in candidate_tasks:
            note = notes_by_task.get(t.id)
            hours = hours_by_task.get(t.id)
            if not note and not hours:
                continue
            assignees = ', '.join(t.user_ids.mapped('name'))
            parts = ['📌 %s | المكلّف: %s' % (t.name, assignees)]
            if hours:
                parts.append('ساعات مسجّلة: %.1f' % hours)
            if note:
                parts.append('آخر ملاحظة (%s): %s' % (note[1], note[0]))
            rows.append('  ' + ' | '.join(parts))

        if not rows:
            return ''
        extra = ''
        if len(rows) > limit:
            extra = '\n  ... و %d تاسك زيادة فيها نشاط مسجّل (مش معروضين لتوفير المساحة).' % (len(rows) - limit)
            rows = rows[:limit]
        return '\n'.join(rows) + extra

    # ------------------------------------------------------------------
    # تاسكات "جارية" (بلشت وما خلصت، ولسا قبل موعدها - مش متأخرة بالمعنى
    # المعتاد) بس استهلكت 80%+ من وقتها المخصّص (planned_date_begin →
    # date_deadline) بدون أي نشاط مسجّل عليها إطلاقاً (لا نوت ولا
    # تايمشيت) - إشارة مبكرة لخطر تأخر قريب، قبل ما يفوت الموعد فعلياً.
    # بترجع لستة (task, elapsed_ratio).
    # ------------------------------------------------------------------
    def _kh_ai_pacing_risk_tasks(self, all_tasks, today_str):
        candidates = all_tasks.filtered(
            lambda t: not self._kh_ai_is_task_done(t) and t.planned_date_begin and t.date_deadline
            and str(t.planned_date_begin)[:10] <= today_str <= str(t.date_deadline)[:10]
        )
        if not candidates:
            return []

        today_date = fields.Date.from_string(today_str)
        ratios = {}
        for t in candidates:
            begin_date = fields.Date.from_string(str(t.planned_date_begin)[:10])
            end_date = fields.Date.from_string(str(t.date_deadline)[:10])
            total_days = (end_date - begin_date).days
            if total_days <= 0:
                continue
            ratio = (today_date - begin_date).days / total_days
            if ratio >= 0.8:
                ratios[t.id] = ratio
        if not ratios:
            return []

        risky_tasks = candidates.filtered(lambda t: t.id in ratios)
        has_activity_ids = set(self.env['mail.message'].sudo().search([
            ('model', '=', 'project.task'),
            ('res_id', 'in', risky_tasks.ids),
            ('message_type', 'in', ['comment', 'email']),
        ]).mapped('res_id'))
        if 'timesheet_ids' in risky_tasks._fields:
            has_activity_ids |= set(self.env['account.analytic.line'].sudo().search([
                ('task_id', 'in', risky_tasks.ids),
            ]).mapped('task_id.id'))

        return [(t, ratios[t.id]) for t in risky_tasks if t.id not in has_activity_ids]

    # ------------------------------------------------------------------
    # هل التاسك منجزة؟ - state وx_custom_state طلعوا فاضيين لمعظم التاسكات
    # (جرّبنا الاثنين وما جابوا نتيجة). العدّاد الأصلي لـ Odoo (يلي طالع
    # بالهيدر "236/271") غالباً بيعتمد على fold تبع الـ Kanban Stage (المرحلة
    # المطوية = منجزة/ملغاة) - هذا أكتر إشارة موثوقة بـ Odoo الأساسي، نتحقق
    # منها أول شي، وبعدها الإشارات الثانوية الباقية.
    # ------------------------------------------------------------------
    @staticmethod
    def _kh_ai_is_task_done(task):
        if task.stage_id and task.stage_id.fold:
            return True
        task_state = task.state or task.x_custom_state or ''
        if task_state in DONE_STATES:
            return True
        if task.stage_id and 'done' in (task.stage_id.name or '').lower():
            return True
        return False

    # ------------------------------------------------------------------
    # ملاحظة تشخيصية مؤقتة: بما إنو أول محاولتين (x_custom_state وstate)
    # طلعوا مافيهم بيانات، منعرض هون بالضبط شو موجود فعلياً بكل تاسك عشان
    # نعرف بدقة شو الحقل/الإشارة الصحيحة بدل التخمين.
    # ------------------------------------------------------------------
    def _kh_ai_build_debug_note(self, all_tasks):
        total = len(all_tasks)
        if not total:
            return False
        fold_true = len(all_tasks.filtered(lambda t: t.stage_id and t.stage_id.fold))
        state_filled = len(all_tasks.filtered(lambda t: t.state))
        xstate_filled = len(all_tasks.filtered(lambda t: t.x_custom_state))
        stage_names = sorted(set(all_tasks.mapped('stage_id.name')) - {False})
        return (
            '🔍 تشخيص مؤقت: من أصل %d تاسك — فيها stage.fold=True: %d | فيها state معبّى: %d '
            '(قيم موجودة: %s) | فيها x_custom_state معبّى: %d | أسماء المراحل (Stages) الموجودة: %s'
            % (total, fold_true, state_filled,
               ', '.join(sorted(set(all_tasks.filtered(lambda t: t.state).mapped('state')))) or '-',
               xstate_filled, ', '.join(stage_names) or '-')
        )

    # ------------------------------------------------------------------
    # التحصيل المالي ونسبة الإنجاز - محسوبة تلقائياً (compute غير مخزّنة)،
    # بتتحدّث لحالها بكل مرة تنفتح، بدون أي زر. اكتشاف حقول Studio (اسم
    # الحقل بس، مش القيمة) يصير مرة وحدة للدفعة كلها مش لكل مشروع لحاله.
    # ------------------------------------------------------------------
    @api.depends()
    def _compute_ai_financials(self):
        work_done_field = self._kh_ai_find_studio_field(
            ['work done', 'إنجاز', 'انجاز', 'progress', 'completion', '% complete', 'percent complete'],
            ['float', 'integer', 'monetary'])
        contract_value_field = self._kh_ai_find_studio_field(
            ['contract value', 'قيمة العقد', 'contract amount', 'project value', 'قيمة المشروع', 'total contract'],
            ['float', 'integer', 'monetary'])
        analytic_field = self._kh_ai_analytic_account_field_name()

        notes = []
        if not work_done_field:
            notes.append('⚠️ ما لقيت حقل "نسبة الإنجاز" على project.project بهذا النظام.')
        if not contract_value_field:
            notes.append('⚠️ ما لقيت حقل "قيمة العقد" على project.project بهذا النظام.')
        note = ' '.join(notes)

        for project in self:
            project.x_ai_work_done = project._kh_ai_read_studio_value(work_done_field) or 0.0
            project.x_ai_contract_value = project._kh_ai_read_studio_value(contract_value_field) or 0.0
            project_note = note
            if not project.partner_id and not (analytic_field and project._kh_ai_read_studio_value(analytic_field)):
                extra = '⚠️ هذا المشروع بدون عميل (partner_id) وبدون حساب تحليلي - ما بقدر ألقى فواتيره تلقائياً (بس ممكن Claude يلاقيه لحاله عبر find_customer).'
                project_note = (project_note + ' ' + extra).strip()
            if not project.x_ai_last_financial_check_date:
                extra = '⏳ لسا ما انعمل تحقق مالي حقيقي لهذا المشروع - رح يصير بأول مراجعة AI.'
                project_note = (project_note + ' ' + extra).strip()
            project.x_ai_financial_data_note = project_note or False

    # ------------------------------------------------------------------
    # لو Claude فعلياً دقّق بفواتير حقيقية (عبر search_odoo_records) ولقى
    # أرقام مختلفة عن الحساب الآلي (متل حالة Contact مختلف) - منستبدل
    # الأرقام الرسمية بالأرقام المؤكّدة، ومنسجّل الملاحظة ليكون واضح إنها
    # صُحّحت. هذا الاستبدال الوحيد المسموح لـ AI على الأرقام المالية،
    # وبس لما يقول صراحة "confident".
    # ------------------------------------------------------------------
    def _kh_ai_apply_financial_verification(self, verification):
        if not isinstance(verification, dict) or not verification.get('confident'):
            return
        try:
            invoiced = verification.get('invoiced_amount')
            collected = verification.get('collected_amount')
            contract = verification.get('contract_value')
            source = (verification.get('source_note') or '').strip()

            if invoiced is not None:
                self.x_ai_invoiced_amount = float(invoiced)
            if collected is not None:
                self.x_ai_collected_amount = float(collected)
            if contract:
                self.x_ai_contract_value = float(contract)
            self.x_ai_outstanding_amount = self.x_ai_invoiced_amount - self.x_ai_collected_amount

            note = '✅ صُحّحت الأرقام أعلاه من AI بعد تدقيق حقيقي.' + (' (%s)' % source if source else '')
            existing = self.x_ai_financial_data_note or ''
            self.x_ai_financial_data_note = (note + ' ' + existing).strip()
        except Exception:
            _logger.exception('KH_AI_MANAGER: applying financial verification failed')

    # ------------------------------------------------------------------
    # حلقة Agentic عامة تعيد استخدام محرّك أدوات mcp_server (نفس الأدوات يلي
    # الشات العام يستخدمها: find_customer/search_records/list_enabled_models
    # الخ) بدل أداتنا الخاصة - القرار: نعتمد على نفس المحرّك المُثبَت صحته،
    # ونصمّم فقط "برومبت جاهز" مركّز لكل حاجة (طلب واحد = برومبت واحد +
    # أداة نتيجة نهائية واحدة)، بدل حلقة عامة تحاول تعمل كل شي بمرة واحدة.
    # execute_tool بيتطلب env تبع اليوزر الحقيقي (مش sudo) عشان صلاحياته
    # الفعلية تنطبق تماماً متل الشات العام - هذا هو نفس مبدأ "الصلاحيات
    # حسب اليوزر مش حسب Claude" يلي طلبه صاحب العمل.
    # بيرجع (data_dict, error_message) - وحدة منهم دايماً None/فاضي.
    # ------------------------------------------------------------------
    def _kh_ai_run_mcp_prompt(self, prompt, result_tool, extra_content_blocks=None, max_iterations=None, exclude_tools=None):
        if not HAS_ANTHROPIC:
            return None, 'مكتبة anthropic غير مثبّتة.'

        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('mcp_server.anthropic_api_key')
        model = ICP.get_param('mcp_server.anthropic_model') or DEFAULT_MODEL
        if not api_key:
            return None, 'مفتاح mcp_server.anthropic_api_key غير موجود في إعدادات Odoo.'

        # exclude_tools مش بس تعليمات بالبرومبت - هذا حذف فعلي للأداة من القائمة
        # يلي Claude شايفها، يعني مستحيل يستخدمها أصلاً (مش بس "ممنوع" بالنص).
        # مفيد لحالات متل خلق تاسكات جديدة غلط بدل تحديث الموجودة.
        tools = [t for t in mcp_ai_tools.build_tool_definitions(self.env) if t['name'] not in (exclude_tools or ())]
        tools.append(result_tool)
        # extra_content_blocks بيسمح بإرفاق صورة/PDF (متل تايم لاين مقاول ممسوح)
        # جنب النص بأول رسالة - نفس آلية Claude Vision/Documents العادية.
        first_content = (list(extra_content_blocks) + [{'type': 'text', 'text': prompt}]) if extra_content_blocks else prompt
        messages = [{'role': 'user', 'content': first_content}]
        iterations = max_iterations or MAX_AGENTIC_ITERATIONS

        try:
            client = anthropic.Anthropic(api_key=api_key)
            for _ in range(iterations):
                resp = client.messages.create(
                    model=model, max_tokens=3000, tools=tools, messages=messages)
                messages.append({'role': 'assistant', 'content': resp.content})

                tool_uses = [b for b in (resp.content or []) if getattr(b, 'type', '') == 'tool_use']
                if not tool_uses:
                    break

                final_call = next((b for b in tool_uses if b.name == result_tool['name']), None)
                if final_call:
                    return (final_call.input or {}), None

                tool_results = []
                for block in tool_uses:
                    result, is_error = mcp_ai_tools.execute_tool(
                        self.env, self.env.user, block.name, block.input or {})
                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': block.id,
                        'content': json.dumps(result, default=str, ensure_ascii=False)[:8000],
                        'is_error': is_error,
                    })
                messages.append({'role': 'user', 'content': tool_results})

            return None, 'وصل الحد الأقصى لعدد التكرارات (%d) بدون نتيجة نهائية.' % iterations
        except Exception as e:
            _logger.exception('KH_AI_MANAGER: MCP-based prompt call failed')
            return None, 'فشل استدعاء Claude عبر أدوات mcp_server: %s' % str(e)[:200]

    _KH_AI_FINANCIAL_TOOL = {
        'name': 'report_financials',
        'description': (
            'أرجع نتيجة التحقق المالي النهائية بعد التأكد من فواتير حقيقية - '
            'استدعِ هذه الأداة فقط لما تكون خلصت التحقق (أو تأكدت إنه ما بقدر تتحقق).'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'confident': {
                    'type': 'boolean',
                    'description': 'true فقط إذا فعلياً جمعت أرقام حقيقية من نتائج search_records على account.move.',
                },
                'invoiced_amount': {'type': 'number', 'description': 'إجمالي الفواتير الصحيح (لو confident).'},
                'collected_amount': {'type': 'number', 'description': 'إجمالي المحصّل فعلياً الصحيح (لو confident).'},
                'contract_value': {'type': 'number', 'description': 'قيمة العقد الصحيحة لو لقيتها (اختياري).'},
                'source_note': {
                    'type': 'string',
                    'description': 'اسم الـ Contact/العميل الصحيح المستخدم بالتحقق، وملخّص قصير كيف توصلت للرقم.',
                },
            },
            'required': ['confident'],
        },
    }

    # ------------------------------------------------------------------
    # البرومبت الجاهز المركّز الأول: التحقق المالي - بديل كامل لحسابنا
    # الحتمي القديم (partner_id مطابقة مباشرة) يلي ثبت غلطه مرات عديدة على
    # بيانات حقيقية، وتم حذفه بالكامل. بيستخدم find_customer (لحل اختلاف اسم الـ Contact عن اسم
    # العميل بالمشروع) بعدها search_records على account.move.
    # ------------------------------------------------------------------
    def _kh_ai_verify_financials_via_mcp(self):
        self.ensure_one()
        partner_name = self.partner_id.name if self.partner_id else '-'
        partner_id = self.partner_id.id if self.partner_id else '-'
        prompt = (
            "أنت محاسب مدقّق بشركة إماراتية. مطلوب منك تتحقق من الوضع المالي الحقيقي "
            "لمشروع اسمه \"%s\". العميل المسجّل بالمشروع بالنظام: \"%s\" (partner_id=%s) - "
            "بس هذا الاسم ممكن يكون مختلف شوي عن اسم الـ Contact الحقيقي بالمحاسبة (لغة "
            "مختلفة، أو Contact تابع بس بنفس المجموعة)، فلازم تتأكد بنفسك مش تفترض.\n\n"
            "الخطوات:\n"
            "1) استخدم أداة find_customer بالاسم \"%s\" (وجرّب أسماء قريبة لو الأول ما رجّع "
            "نتيجة واضحة) لتحدّد الـ partner_id الصحيح فعلياً.\n"
            "2) استخدم أداة search_records على account.move بـ domain يحتوي "
            "[\"partner_id\", \"=\", <الid الصحيح يلي لقيته>], [\"state\", \"=\", \"posted\"], "
            "[\"move_type\", \"in\", [\"out_invoice\", \"out_refund\"]] واطلب الحقول "
            "amount_total_signed وamount_residual_signed.\n"
            "3) اجمع amount_total_signed لكل الفواتير = المفوتر الكلي. المحصّل فعلياً = "
            "المفوتر الكلي - مجموع amount_residual_signed.\n"
            "4) لو الـ partner_id الأول ما طلع منه فواتير، جرّب اسم قريب تاني (شركة أم/فرد "
            "تابع) قبل ما تستسلم.\n"
            "5) استدعِ report_financials بالنتيجة. ممنوع تخترع رقم أو تقدّره - لو ما قدرت "
            "تتأكد فعلياً من فواتير حقيقية، خلّي confident=false وبلاش تعبّي الأرقام."
            % (self.name, partner_name, partner_id, partner_name or self.name)
        )
        data, error = self._kh_ai_run_mcp_prompt(prompt, self._KH_AI_FINANCIAL_TOOL)
        if error:
            _logger.warning(
                'KH_AI_MANAGER: financial MCP verification failed for project %s (%s): %s',
                self.id, self.name, error)
            return None
        return data

    _KH_AI_TIMELINE_TOOL = {
        'name': 'report_timeline_integration',
        'description': (
            'أرجع ملخّص نهائي لعملية مطابقة تايم لاين المقاول مع تاسكات المشروع. '
            'استدعِ هذه الأداة فقط بعد ما تتأكد إنه ما في ولا تاسك فاضي بأي مرحلة طابقتها.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'tasks_updated_count': {'type': 'integer', 'description': 'إجمالي عدد التاسكات يلي حدّثتها.'},
                'stages_updated': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'stage_name': {'type': 'string'},
                            'date_start': {'type': 'string'},
                            'date_end': {'type': 'string'},
                            'tasks_count': {'type': 'integer'},
                        },
                        'required': ['stage_name', 'date_start', 'date_end', 'tasks_count'],
                    },
                    'description': 'كل مرحلة طابقتها بنشاط/أنشطة المقاول، بالنافذة الزمنية وعدد التاسكات.',
                },
                'skipped_stages': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'أسماء المراحل يلي تركتها بدون تاريخ + السبب (مثلاً: مرحلة تصميم ما بيغطّيها جدول المقاول).',
                },
                'summary_note': {
                    'type': 'string',
                    'description': 'فقرة قصيرة (عربي) تلخّص العملية - رح تُنشر على شاتر المشروع كما هي.',
                },
            },
            'required': ['tasks_updated_count', 'stages_updated', 'skipped_stages', 'summary_note'],
        },
    }

    # ------------------------------------------------------------------
    # مطابقة تايم لاين المقاول (صورة/PDF) مع تاسكات المشروع - نفس فكرة
    # التحقق المالي (برومبت مركّز يستخدم أدوات mcp_server)، بس هون مع
    # مرفق (صورة/PDF) بأول رسالة كمان (Claude Vision/Documents)، مش نص بس.
    # مهمة أثقل من العادي (بحث + قراءة كل التاسكات + كتابة دفعات لكل
    # مرحلة) فمنعطيها سقف تكرارات أعلى من الافتراضي.
    # ------------------------------------------------------------------
    def _kh_ai_integrate_contractor_timeline(self, file_b64, filename, media_type):
        self.ensure_one()
        user = self.env.user
        prompt = (
            "أنت مساعد مدير مشاريع بشركة إنشاءات. عندك تايم لاين (Gantt) مرفق قدّمه "
            "المقاول لمشروع \"%s\" (project_id=%d) - افحصه وطابقه مع تاسكات المشروع "
            "الموجودة فعلياً بـ Odoo. لازم تخلّص هذا بمرة واحدة، بدون ما تحتاج طلب متابعة.\n\n"
            "⚠️ قاعدة مهمة: المشروع فيه عشرات التاسكات التفصيلية بكل مرحلة (checklist "
            "items) - هذا متوقع وطبيعي. لو نشاط المقاول له مرحلة/تاسكات مطابقة فعلياً "
            "بالمشروع (وهذا الغالب)، حدّث تواريخ التاسكات الموجودة (write_record) - "
            "ممنوع تخلق تاسك جديد/ملخّص بدل ما تعبّي الموجود، وممنوع تسيب تاسك فاضي "
            "بمرحلة طابقتها. **بس** لو نشاط معيّن ما له أي مرحلة أو تاسك مطابق بالمشروع "
            "إطلاقاً (يعني فعلياً مافي شي موجود له)، مقبول تستخدم create_record وتخلق "
            "تاسك جديد له - هذا استثناء مقبول، مش الافتراضي.\n\n"
            "الخطوات:\n"
            "1) اقرأ كل نشاط (Bar) بالمرفق وتاريخ بدايته/نهايته التقريبي.\n"
            "2) استخدم search_records على project.task بـ domain "
            "[[\"project_id\", \"=\", %d]] واطلب الحقول name, stage_id, "
            "planned_date_begin, date_deadline, user_ids - وتأكد جبت كل التاسكات "
            "(استخدم limit عالي وكرّر البحث لو في صفحات زيادة)، مجمّعة حسب stage_id.\n"
            "3) طابق كل نشاط مقاول مع المرحلة (stage) المقابلة بالمشروع. مرحلة واحدة "
            "ممكن تقابل أكتر من نشاط مقاول (مثلاً Tiling = Floor Tile + Wall Tile) - "
            "بهذا الحال استخدم أبكر تاريخ بداية وأبعد تاريخ نهاية بين الأنشطة المتطابقة.\n"
            "4) لكل مرحلة طابقتها - استخدم أداة align_project_tasks_with_stage_dates "
            "(الأفضل، بتحدّث كل تاسكات المرحلة بنداء واحد، بترجّعلك عدد التاسكات "
            "المحدّثة فعلياً، وبتعيّن %s (اليوزر الطالب) تلقائياً على كل تاسك حدّثته - "
            "بدون ما تحتاج تمرر أي user_id) بدل write_record لتاسك لتاسك. مرّرلها "
            "project_keyword وstage_name وdate_start وdate_end بس. ممنوع تسيب ولا "
            "تاسك فاضي بمرحلة طابقتها - قبل ما تنادي report_timeline_integration، "
            "أعد البحث (search_records) وتأكد الصفر تاسكات فاضية بالمراحل المطابقة.\n"
            "5) المراحل يلي مافيها أي نشاط مطابق بجدول المقاول (عادة مراحل التصميم/"
            "الموافقات قبل بدء التنفيذ) سيبها بدون تاريخ - سجّلها بـ skipped_stages مع السبب.\n"
            "6) استدعِ report_timeline_integration بالنتيجة النهائية."
            % (self.name, self.id, self.id, user.name)
        )
        content_block = {
            'type': 'document' if media_type == 'application/pdf' else 'image',
            'source': {'type': 'base64', 'media_type': media_type, 'data': file_b64},
        }
        data, error = self._kh_ai_run_mcp_prompt(
            prompt, self._KH_AI_TIMELINE_TOOL, extra_content_blocks=[content_block], max_iterations=25,
            exclude_tools=['unlink_record'])
        if error:
            raise UserError('فشلت مطابقة تايم لاين المقاول: %s' % error)

        summary = (data.get('summary_note') or '').strip()
        stages = data.get('stages_updated') or []
        skipped = data.get('skipped_stages') or []
        stages_html = ''.join(
            '<li>%s: %s → %s (%s تاسك)</li>' % (
                escape(str(s.get('stage_name', '-'))), escape(str(s.get('date_start', '-'))),
                escape(str(s.get('date_end', '-'))), escape(str(s.get('tasks_count', '-'))))
            for s in stages if isinstance(s, dict)
        )
        skipped_html = ''.join('<li>%s</li>' % escape(str(s)) for s in skipped)
        report_html = (
            '<div dir="rtl" style="text-align:right;">'
            '<h5 style="color:#714B67;">🗓️ مطابقة تايم لاين المقاول (AI)</h5>'
            '<p>%s</p>'
            '<p><strong>إجمالي التاسكات المحدّثة:</strong> %s</p>'
            '%s'
            '%s'
            '</div>'
            % (escape(summary) if summary else '-', escape(str(data.get('tasks_updated_count', '-'))),
               ('<p><strong>المراحل المطابقة:</strong></p><ul>%s</ul>' % stages_html) if stages_html else '',
               ('<p><strong>مراحل تُركت بدون تاريخ:</strong></p><ul>%s</ul>' % skipped_html) if skipped_html else '')
        )
        self.message_post(body=Markup(report_html), message_type='comment', subtype_xmlid='mail.mt_comment')
        return data

    # ------------------------------------------------------------------
    # تاسكات مفتوحة/متأخرة + أكتفيتيز متأخرة + إسناد المهام - محسوبة
    # ومخزّنة (store=True) وبتتحدّث لحالها لما التاسكات/تواريخها تتغيّر،
    # بدون أي زر.
    # ------------------------------------------------------------------
    @api.depends('task_ids', 'task_ids.date_deadline', 'task_ids.state', 'task_ids.x_custom_state',
                 'task_ids.stage_id', 'task_ids.user_ids',
                 'activity_ids.date_deadline', 'task_ids.activity_ids.date_deadline')
    def _compute_ai_task_metrics(self):
        today_str = str(fields.Date.context_today(self))
        for project in self:
            all_tasks = project.task_ids
            open_tasks = all_tasks.filtered(lambda t: not project._kh_ai_is_task_done(t))
            overdue_tasks = open_tasks.filtered(lambda t: t.date_deadline and str(t.date_deadline) < today_str)
            overdue_proj_acts = project.activity_ids.filtered(
                lambda a: a.date_deadline and str(a.date_deadline) < today_str)
            overdue_task_acts = all_tasks.activity_ids.filtered(
                lambda a: a.date_deadline and str(a.date_deadline) < today_str)

            # نسبة إنجاز محسوبة فعلياً من التاسكات (بدون الملغاة) - بديل/مقارنة
            # مستقلة عن حقل Studio اليدوي، لأنه هالأخير ممكن يكون فاضي أو ما تحدّث.
            countable_tasks = all_tasks.filtered(lambda t: (t.state or t.x_custom_state or '') != '1_canceled')
            done_tasks = countable_tasks.filtered(lambda t: project._kh_ai_is_task_done(t))
            project.x_ai_work_done_tasks = (
                (len(done_tasks) / len(countable_tasks) * 100.0) if countable_tasks else 0.0
            )

            project.x_ai_open_tasks_count = len(open_tasks)
            project.x_ai_overdue_tasks_count = len(overdue_tasks)
            project.x_ai_overdue_activities_count = len(overdue_proj_acts) + len(overdue_task_acts)
            project.x_ai_assignment_summary = project._kh_ai_build_assignment_summary(open_tasks, today_str)
            project.x_ai_debug_note = project._kh_ai_build_debug_note(all_tasks)

            project.x_ai_overdue_task_ids = overdue_tasks
            project.x_ai_next_task_ids = open_tasks - overdue_tasks
            project.x_ai_done_task_ids = all_tasks - open_tasks

    def _kh_ai_build_assignment_summary(self, open_tasks, today_str):
        counts = defaultdict(lambda: [0, 0])
        unassigned = [0, 0]
        for t in open_tasks:
            is_overdue = bool(t.date_deadline and str(t.date_deadline) < today_str)
            if not t.user_ids:
                unassigned[0] += 1
                if is_overdue:
                    unassigned[1] += 1
            for u in t.user_ids:
                counts[u.name][0] += 1
                if is_overdue:
                    counts[u.name][1] += 1

        if not counts and not unassigned[0]:
            return '<p dir="rtl" style="text-align:right;color:#999;">لا يوجد تاسكات مفتوحة.</p>'

        rows = ''.join(
            '<tr><td>%s</td><td style="text-align:center;">%d</td>'
            '<td style="text-align:center;color:%s;">%d</td></tr>'
            % (name, c[0], '#E74C3C' if c[1] else '#888', c[1])
            for name, c in sorted(counts.items(), key=lambda kv: -kv[1][0])
        )
        if unassigned[0]:
            rows += (
                '<tr><td style="color:#E74C3C;">⚠️ غير مسندة</td>'
                '<td style="text-align:center;">%d</td>'
                '<td style="text-align:center;color:#E74C3C;">%d</td></tr>'
                % (unassigned[0], unassigned[1])
            )
        return (
            '<table dir="rtl" style="width:100%%;border-collapse:collapse;font-size:13px;text-align:right;">'
            '<thead><tr><th style="text-align:right;">المكلّف</th>'
            '<th style="text-align:center;">مفتوحة</th><th style="text-align:center;">متأخرة</th></tr></thead>'
            '<tbody>%s</tbody></table>' % rows
        )

    # ------------------------------------------------------------------
    # التنسيق البصري بالكامل بالكود (Python)، مش عند Claude - نطلب منه
    # محتوى (نصوص عادية بسيطة بس)، ونحن يلي نبني الـ HTML/CSS بشكل ثابت
    # ومضمون دايماً بنفس الشكل، بدل ما نعتمد على التزامه بوسوم/style
    # في كل مرة (يلي ثبت إنه مش مضمون).
    # ------------------------------------------------------------------
    _KH_AI_STYLE = (
        '<style>'
        '.kh_ai_box{line-height:1.8;font-size:14px;direction:rtl;text-align:right;}'
        '.kh_ai_box p{margin:0 0 10px 0;}'
        '.kh_ai_box ul,.kh_ai_box ol{padding-right:22px;margin:0 0 12px 0;}'
        '.kh_ai_box li{margin-bottom:8px;}'
        '.kh_ai_alert{padding:8px 12px;border-radius:4px;margin-bottom:8px;border-right:3px solid;}'
        '.kh_ai_alert_missing_update{background:#fdecea;border-color:#E74C3C;}'
        '.kh_ai_alert_stale_task{background:#fff3cd;border-color:#E67E22;}'
        '.kh_ai_alert_overdue{background:#fdecea;border-color:#E74C3C;}'
        '.kh_ai_alert_unassigned{background:#fff3cd;border-color:#E67E22;}'
        '.kh_ai_alert_financial{background:#fff8e6;border-color:#E67E22;}'
        '.kh_ai_alert_other{background:#eef2ff;border-color:#714B67;}'
        '</style>'
    )

    _KH_AI_ALERT_ICONS = {
        'missing_update': '📭',
        'stale_task': '🕰️',
        'overdue': '⏰',
        'unassigned': '👤',
        'financial': '💰',
        'other': '💡',
    }

    @staticmethod
    def _kh_ai_as_list(value):
        # بعض المرات Claude يرجّع الحقول من نوع array كنص JSON مكتوب (string)
        # بدل array حقيقية - لو تعاملنا معه كـ list مباشرة، بايثون بيكرّر
        # على كل حرف لحاله (string قابلة للتكرار). هذا الحل يطبّع الحالتين.
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
            return [value]
        return []

    @staticmethod
    def _kh_ai_truncate(text, length=140):
        text = (text or '').strip()
        return (text[:length] + '…') if len(text) > length else text

    @staticmethod
    def _kh_ai_html_to_plain(html_content):
        # html2plaintext ما بيشيل محتوى وسم <style> (بس التاجات نفسها) -
        # وحقولنا المخزّنة (x_ai_today_summary/x_ai_alerts) فيها _KH_AI_STYLE
        # مدمج بالداخل، فكانت الـ CSS الخام عم تسرّب كنص عادي بالتقارير
        # (نفس الغلطة يلي صحّحناها قبل بتاسك Karan - هون فاتت لأنه مكان
        # جديد). الحل: نشيل وسم <style> بالكامل (مع محتواه) قبل التحويل.
        html_content = re.sub(r'(?is)<style.*?</style>', '', html_content or '')
        return html2plaintext(html_content).strip()

    def _kh_ai_render_simple_html(self, text):
        text = (text or '').strip()
        if not text:
            return ''
        return '<div class="kh_ai_box" dir="rtl">%s<p>%s</p></div>' % (self._KH_AI_STYLE, escape(text))

    # ------------------------------------------------------------------
    # قسم "ملخّص اليوم" بفقرتين واضحتين ومنفصلتين بصرياً - عام (general_status)
    # واليوم تحديداً (today_update) - عشان ما يظل القسم قراءته "ملخّص عام"
    # بس بينما اسمه "اليوم". لو today_update فاضي (Claude ما امتثل)، منعرض
    # الوضع العام بس بدون قسم يوم فاضي.
    # ------------------------------------------------------------------
    def _kh_ai_render_today_html(self, data, today_str):
        general_status = (data.get('general_status') or '').strip()
        today_update = (data.get('today_update') or '').strip()
        if not general_status and not today_update:
            return ''
        parts = ['<div class="kh_ai_box" dir="rtl">', self._KH_AI_STYLE]
        if general_status:
            parts.append(
                '<p><strong>📌 الوضع العام:</strong> %s</p>' % escape(general_status))
        if today_update:
            parts.append(
                '<p><strong>📅 اليوم (%s):</strong> %s</p>' % (today_str, escape(today_update)))
        parts.append('</div>')
        return ''.join(parts)

    def _kh_ai_render_alerts_html(self, data):
        alerts = self._kh_ai_as_list(data.get('alerts'))
        rows = []
        for a in alerts:
            if isinstance(a, dict):
                a_type = a.get('type') or 'other'
                message = a.get('message') or ''
            else:
                a_type, message = 'other', str(a)
            if not message.strip():
                continue
            icon = self._KH_AI_ALERT_ICONS.get(a_type, self._KH_AI_ALERT_ICONS['other'])
            rows.append('<div class="kh_ai_alert kh_ai_alert_%s">%s %s</div>' % (
                a_type if a_type in self._KH_AI_ALERT_ICONS else 'other', icon, escape(message)))
        if not rows:
            return '<div class="kh_ai_box" dir="rtl">%s<p style="color:#27AE60;">✅ لا يوجد تنبيهات حالياً.</p></div>' % self._KH_AI_STYLE
        return '<div class="kh_ai_box" dir="rtl">%s%s</div>' % (self._KH_AI_STYLE, ''.join(rows))

    def _kh_ai_render_next_steps_html(self, data):
        steps = [s for s in self._kh_ai_as_list(data.get('next_steps')) if s and str(s).strip()]
        if not steps:
            return ''
        return (
            '<div class="kh_ai_box" dir="rtl">%s<ol>%s</ol></div>'
            % (self._KH_AI_STYLE, ''.join('<li>%s</li>' % escape(s) for s in steps))
        )

    # ------------------------------------------------------------------
    # خطوات تالية احتياطية (بدون AI) - مبنية بالكامل من حقائق جاهزة عندنا،
    # مستخدمة بس لما Claude يرجّع next_steps فاضية رغم تعليمات البرومبت
    # (يصير مع مشاريع هادية بدون تنبيهات). هدفها ضمان إنه هذا القسم دايماً
    # مليان بنفس لحظة باقي أقسام المشروع، بدل ما يفضل فاضي بانتظار امتثال
    # الـ LLM.
    # ------------------------------------------------------------------
    def _kh_ai_fallback_next_steps(self, open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts,
                                    stale_tasks, days_since_update, accountant):
        steps = []
        if overdue_tasks:
            steps.append('تابع مع الفريق التاسكات المتأخرة: %s' % ', '.join(overdue_tasks.mapped('name')[:3]))
        if overdue_proj_acts or overdue_task_acts:
            steps.append('راجع الأكتفيتيز المتأخرة وحدّد لها موعد جديد أو أنجزها.')
        if stale_tasks:
            steps.append('تواصل مع المسؤولين عن التاسكات الراكدة لتحديث حالتها الفعلية.')
        unassigned = open_tasks.filtered(lambda t: not t.user_ids)
        if unassigned:
            steps.append('حدّد مسؤول للتاسكات المفتوحة بدون مسؤول (%d تاسك).' % len(unassigned))
        if (self.x_ai_outstanding_amount or 0.0) > 0:
            who = accountant.name if accountant else 'المحاسب'
            steps.append('تابع مع %s ملف التحصيل - المتبقّي %.2f.' % (who, self.x_ai_outstanding_amount))
        if days_since_update is None or (days_since_update or 0) >= 7:
            steps.append('حدّث سجل المشروع بآخر التطورات مع العميل/الفريق.')
        if not steps:
            steps = [
                'تأكد من متابعة الجدول الزمني للمشروع مع الفريق.',
                'تواصل مع العميل لتأكيد آخر التطورات إذا لزم.',
            ]
        return steps[:5]

    # ------------------------------------------------------------------
    # أداة استكشاف حرّة لـ Claude (Agentic) - قراءة فقط، على النماذج المسموحة
    # (KH_AI_TOOL_MODELS) بس. منفصلة كلياً عن mcp_server - هذا نطاق خاص بمدير
    # المشاريع الذكي بقرار من الإدارة، بدون حظر account.*/purchase.* يلي
    # موجود بالمحرّك العام.
    # ------------------------------------------------------------------
    _KH_AI_SEARCH_TOOL = {
        'name': 'search_odoo_records',
        'description': (
            'ابحث واقرأ سجلات Odoo (قراءة فقط - ممنوع كتابة/تعديل) من النماذج التالية بس: '
            + ', '.join(KH_AI_TOOL_MODELS) + '. استخدمها لما تحتاج معلومة إضافية غير موجودة '
            'بالبيانات المرفقة - مثل عروض/فرص CRM، أوامر شراء (Purchase Orders)، طلبات اعتماد '
            '(Approvals)، أو تفاصيل فواتير إضافية.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'model': {'type': 'string', 'description': 'الاسم التقني للموديل، مثلاً purchase.order'},
                'domain': {
                    'type': 'string',
                    'description': 'دومين Odoo كنص Python، مثلاً [["partner_id", "=", 5]] - اختياري.',
                },
                'fields': {
                    'type': 'array', 'items': {'type': 'string'},
                    'description': 'أسماء الحقول المطلوبة - اختياري، لو فاضي بيرجع الحقول الأساسية.',
                },
                'limit': {'type': 'integer', 'description': 'أقصى عدد سجلات (حد أعلى 30).'},
            },
            'required': ['model'],
        },
    }

    def _kh_ai_execute_search_tool(self, tool_input):
        model_name = (tool_input or {}).get('model') or ''
        if model_name not in KH_AI_TOOL_MODELS:
            return {'error': 'موديل غير مسموح لهذه الأداة: %s' % model_name}
        try:
            domain_str = (tool_input or {}).get('domain') or '[]'
            domain = safe_eval(domain_str) if isinstance(domain_str, str) else (domain_str or [])
            if not isinstance(domain, list):
                domain = []
            limit = min(int((tool_input or {}).get('limit') or 20), 30)
            field_names = (tool_input or {}).get('fields') or []

            Model = self.env[model_name].sudo()
            records = Model.search(domain, limit=limit)
            data = records.read(field_names) if field_names else records.read()
            return {'count': len(data), 'records': data}
        except Exception as e:
            return {'error': str(e)[:300]}

    # ------------------------------------------------------------------
    # الميثود الوحيدة يلي بتستدعي Claude - بتشتغل تلقائياً كل ساعة (Cron)
    # أو فوراً لو ضغطت الزر، وبتحدّث 4 أقسام: ملخّص اليوم، التحصيل مع
    # المحاسب، التنبيهات، الخطوات التالية. post_report=True (التقرير
    # الأسبوعي بس) هو الوقت الوحيد يلي بننشر بالشاتر - تفادياً لـ Spam
    # لو صار التشغيل كل ساعة.
    # ------------------------------------------------------------------
    def action_run_ai_review_manual(self):
        # الزر اليدوي وأداة "تشغيل مراجعة AI" الجماعية - لازم يفرضوا مراجعة
        # فعلية دايماً (force=True)، بعكس الـ Cron التلقائي، لأنه المستخدم
        # كبس بنفسه توقّعاً لنتيجة جديدة فوراً - مش منطقي "نتجاهلها" لأنه
        # نفس البصمة القديمة، وبالأخص لو تحسّن البرومبت وبدنا نتأكد إنه
        # المشروع بياخد فايدة التحسين فوراً بدل ما يستنى تغيير خارجي.
        return self.action_run_ai_review(force=True)

    def action_open_timeline_import_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '🗓️ مطابقة تايم لاين المقاول',
            'res_model': 'kh.ai.timeline.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_project_id': self.id},
        }

    def action_run_ai_review(self, post_report=False, force=False):
        self.ensure_one()
        self._compute_ai_financials()  # فريش (store=True بدون depends تلقائي - لازم نطلبه يدوياً)
        today_str = str(fields.Date.context_today(self))
        date_from = fields.Datetime.to_string(
            fields.Datetime.subtract(fields.Datetime.now(), days=DIGEST_DAYS)
        )

        all_tasks = self.task_ids
        open_tasks = all_tasks.filtered(lambda t: not self._kh_ai_is_task_done(t))
        overdue_tasks = open_tasks.filtered(lambda t: t.date_deadline and str(t.date_deadline) < today_str)
        overdue_proj_acts = self.activity_ids.filtered(lambda a: a.date_deadline and str(a.date_deadline) < today_str)
        overdue_task_acts = all_tasks.activity_ids.filtered(
            lambda a: a.date_deadline and str(a.date_deadline) < today_str)
        days_since_update, stale_tasks = self._kh_ai_check_staleness(open_tasks)
        accountant = self._kh_ai_find_accountant_user()

        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'project.project'),
            ('res_id', '=', self.id),
            ('date', '>=', date_from),
            ('message_type', 'in', ['comment', 'email', 'notification']),
        ], order='date desc', limit=40)

        # التحقق المالي عبر برومبت مخصّص يستخدم أدوات mcp_server (find_customer +
        # search_records) - المصدر الوحيد للأرقام المالية هلق (حذفنا الحساب
        # الحتمي القديم كلياً لأنه ثبت غلطه). لازم يصير قبل بناء الـ digest عشان الأرقام
        # المصحّحة توصل لبرومبت المراجعة الرئيسي كمان، مش بس تتحدّث بالفورم بعدين.
        # هذا الجزء هو الأبطأ (حلقة Agentic كاملة تانية) - الفواتير ما بتتغيّر
        # كل ساعة، فمنشغّله مرة كل 24 ساعة بس لكل مشروع (مش كل مرة تشتغل
        # المراجعة الساعية)، عشان نوفّر وقت/تكلفة بدون فايدة حقيقية إضافية.
        now = fields.Datetime.now()
        needs_financial_check = (
            force
            or not self.x_ai_last_financial_check_date
            or (now - self.x_ai_last_financial_check_date).total_seconds() >= 24 * 3600
        )
        if needs_financial_check:
            try:
                mcp_verification = self._kh_ai_verify_financials_via_mcp()
            except Exception:
                _logger.exception('KH_AI_MANAGER: financial MCP verification crashed for project %s', self.id)
                mcp_verification = None
            if mcp_verification:
                self._kh_ai_apply_financial_verification(mcp_verification)
            self.x_ai_last_financial_check_date = now

        # لو ما صار أي جديد حقيقي على المشروع (نفس عدد التاسكات المفتوحة/
        # المتأخرة/الأكتفيتيز/الراكدة، آخر رسالة/تعديل تاسك، والمتبقّي المالي)
        # من آخر مراجعة AI ناجحة - ما في فايدة نعيد استدعاء Claude بلا أي جديد
        # يحلله. منحتفظ بنفس النتيجة القديمة، وبس منحدّث الأنشطة (رخيصة،
        # بدون Claude) عشان تبقى متزامنة مع الأرقام الحالية.
        signature = self._kh_ai_build_change_signature(
            all_tasks, open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts,
            stale_tasks, days_since_update, messages, today_str)
        if not force and self.x_ai_last_review_date and signature == self.x_ai_change_signature:
            _logger.info('KH_AI_MANAGER: skipping AI review for project %s (%s) - nothing changed since last review.',
                          self.id, self.name)
            if post_report:
                report_html = self._kh_ai_build_weekly_report_html(
                    today_str, open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts,
                    self.x_ai_today_summary, self.x_ai_collection_note,
                    self.x_ai_alerts, self.x_ai_next_steps)
                # mt_note (ملاحظة داخلية) لا mt_comment - نحتفظ بالسجل التاريخي
                # على شاتر كل مشروع بدون ما ننبّه كل المتابعين (متل المدير
                # العام لو كان متابع لعشرات المشاريع) - التقرير المجمّع الوحيد
                # يلي المفروض يوصله فعلياً هو _kh_ai_send_gm_weekly_digest.
                self.message_post(body=Markup(report_html), message_type='comment', subtype_xmlid='mail.mt_note')
            self._kh_ai_notify_pm_if_needed(open_tasks)
            self._kh_ai_notify_accountant_if_needed(accountant)
            return True

        digest = self._kh_ai_build_digest(
            self.x_ai_work_done, self.x_ai_work_done_tasks, self.x_ai_contract_value,
            self.x_ai_invoiced_amount, self.x_ai_collected_amount,
            open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts, messages, today_str,
            days_since_update, stale_tasks, accountant,
            task_activity_text=self._kh_ai_build_task_activity_digest(all_tasks))

        data, error_html = self._kh_ai_claude_review(digest)
        if error_html:
            today_html, collection_html, alerts_html, next_steps_html = error_html, '', '', ''
            data = {}
        else:
            data = data or {}
            today_html = self._kh_ai_render_today_html(data, today_str)
            collection_html = self._kh_ai_render_simple_html(data.get('collection_note'))
            # حقيقة جاهزة بالكود (مش معتمدة على ملاحظة Claude) - قيمة العقد
            # لازم تكون معبّأة، لأنها ضرورية لحساب نسبة التحصيل الحقيقية
            # ومقارنتها بالإنجاز. منضيفها دايماً لو فاضية، مش نتكل على إنه
            # Claude يلاحظها لحاله (نفس مبدأ next_steps الاحتياطية فوق).
            if not self.x_ai_contract_value:
                data['alerts'] = [{
                    'type': 'financial',
                    'message': (
                        'قيمة العقد (Contract Value) غير معبّأة بسجل المشروع - '
                        'لازم تُدخل، لأنها ضرورية لحساب نسبة التحصيل الحقيقية ومقارنتها بالإنجاز.'
                    ),
                }] + self._kh_ai_as_list(data.get('alerts'))
            # حقيقة جاهزة بالكود كمان - تاسك جاري (بلش وما خلص، ولسا قبل
            # موعده) استهلك 80%+ من وقته المخصّص بدون أي نشاط مسجّل عليه
            # (نوت/تايمشيت) - إشارة مبكرة لخطر تأخر قريب، قبل ما يفوت
            # الموعد فعلياً ويصير "متأخر" بالمعنى المعتاد.
            pacing_risks = self._kh_ai_pacing_risk_tasks(all_tasks, today_str)
            if pacing_risks:
                pacing_alerts = [{
                    'type': 'other',
                    'message': (
                        'تاسك "%s" استهلك %.0f%% من وقته المخصّص بدون أي نشاط مسجّل عليه '
                        '(نوت أو تايمشيت) - خطر تأخر قريب رغم إنه ما فات موعده لسا.'
                        % (t.name, ratio * 100)
                    ),
                } for t, ratio in pacing_risks]
                data['alerts'] = pacing_alerts + self._kh_ai_as_list(data.get('alerts'))
            alerts_html = self._kh_ai_render_alerts_html(data)
            # ضمان بالكود (مش تعليمات برومبت بس) إنه next_steps ما تطلع فاضية
            # أبداً - جرّبنا نطلب من Claude يضمنها بالبرومبت وبقيت أحياناً
            # فاضية للمشاريع الهادية. هلق لو رجعت فاضية فعلياً، منولّد خطوات
            # افتراضية معقولة من الحقائق الجاهزة (بدون AI)، عشان القسم هذا
            # يتحدث مع باقي أقسام المشروع دايماً بنفس اللحظة، مش يفضل فاضي.
            if not [s for s in self._kh_ai_as_list(data.get('next_steps')) if s and str(s).strip()]:
                data['next_steps'] = self._kh_ai_fallback_next_steps(
                    open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts,
                    stale_tasks, days_since_update, accountant)
            next_steps_html = self._kh_ai_render_next_steps_html(data)

        alerts_list = self._kh_ai_as_list(data.get('alerts'))
        if alerts_list:
            first_msgs = '؛ '.join(
                (a.get('message') if isinstance(a, dict) else str(a)) for a in alerts_list[:2])
            alerts_preview = '%d تنبيه: %s' % (len(alerts_list), first_msgs)
        else:
            alerts_preview = '✅ لا يوجد تنبيهات'
        next_steps_preview = ' | '.join(str(s) for s in self._kh_ai_as_list(data.get('next_steps')))

        self.x_ai_today_summary = today_html
        self.x_ai_collection_note = collection_html
        self.x_ai_alerts = alerts_html
        self.x_ai_next_steps = next_steps_html
        # المعاينة بالقائمة بتركّز على "اليوم" تحديداً (هذا الغرض من البوكس) -
        # لو ما رجعت today_update لأي سبب (خطأ/امتثال)، ترجع للوضع العام.
        self.x_ai_today_summary_preview = self._kh_ai_truncate(
            data.get('today_update') or data.get('general_status'))
        self.x_ai_collection_note_preview = self._kh_ai_truncate(data.get('collection_note'))
        self.x_ai_alerts_preview = self._kh_ai_truncate(alerts_preview)
        self.x_ai_next_steps_preview = self._kh_ai_truncate(next_steps_preview)
        self.x_ai_last_review_date = fields.Datetime.now()
        if not error_html:
            # منسجّل البصمة بس لما ينجح النداء فعلياً - لو صار خطأ عابر
            # (شبكة/API)، منسيب البصمة القديمة عشان تُعاد المحاولة الساعة
            # الجاية بدل ما تُعتبر "بلا تغيير" وتتجاهل للأبد.
            self.x_ai_change_signature = signature

        if self.user_id and self.user_id.partner_id:
            self.message_subscribe(partner_ids=self.user_id.partner_id.ids)

        if post_report:
            report_html = self._kh_ai_build_weekly_report_html(
                today_str, open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts,
                today_html, collection_html, alerts_html, next_steps_html)
            # نفس السبب فوق - mt_note بدل mt_comment، تفادياً لإشعار كل
            # المتابعين (بما فيهم المدير العام لو كان مدير/متابع لعدد كبير
            # من المشاريع) بكل تقرير أسبوعي لكل مشروع لحاله.
            self.message_post(body=Markup(report_html), message_type='comment', subtype_xmlid='mail.mt_note')

        self._kh_ai_notify_pm_if_needed(open_tasks)
        self._kh_ai_notify_accountant_if_needed(accountant)
        return True

    # ------------------------------------------------------------------
    # "بصمة" الوضع الحالي - أي تغيير حقيقي (تاسك جديد/متأخر، رسالة شاتر
    # جديدة، تعديل تاسك، تغيير حالة المشروع، أو فرق بالمتبقّي المالي)
    # بيغيّر هذي البصمة، وبالتالي بيلغي تجاهل المراجعة. مقارنة بسيطة كنص
    # (مش تخزين تفاصيل) - كافية تماماً لسؤال "تغيّر شي ولا لأ؟".
    # ------------------------------------------------------------------
    def _kh_ai_build_change_signature(self, all_tasks, open_tasks, overdue_tasks, overdue_proj_acts,
                                       overdue_task_acts, stale_tasks, days_since_update, messages, today_str):
        # ملاحظة مهمة: ممنوع نستخدم self.write_date هون - كودنا نفسه بيكتب
        # على x_ai_last_review_date بكل تشغيل ناجح، وهذا لحاله بيرفع
        # write_date تبع المشروع كل مرة، فبتصير البصمة "تغيّرت" دايماً
        # حتى لو صفر تغيير خارجي حقيقي - وهيك بتنكسر الفايدة كلها. لهذا
        # منعتمد بس على حقول مصادرها خارجية (تاسكات/رسائل/مرحلة/أرقام).
        self.ensure_one()
        last_task_write = max(all_tasks.mapped('write_date') or [False]) or ''
        last_message_date = messages[0].date if messages else ''

        # نوتس/تايمشيت جوا التاسكات ما بتحرّك write_date تبع التاسك نفسه
        # (سجلات مختلفة كلياً) - لازم فحص منفصل رخيص (limit=1) هون، وإلا
        # بصمة المشروع ما رح "تحس" بنوت/ساعة جديدة، وبتضل تتجاهل المراجعة.
        assigned_task_ids = all_tasks.filtered(lambda t: t.user_ids).ids
        last_task_note_date = ''
        last_timesheet_date = ''
        if assigned_task_ids:
            last_note = self.env['mail.message'].sudo().search([
                ('model', '=', 'project.task'),
                ('res_id', 'in', assigned_task_ids),
                ('message_type', 'in', ['comment', 'email']),
            ], order='date desc', limit=1)
            last_task_note_date = last_note.date if last_note else ''
            if 'timesheet_ids' in all_tasks._fields:
                last_ts = self.env['account.analytic.line'].sudo().search([
                    ('task_id', 'in', assigned_task_ids),
                ], order='write_date desc', limit=1)
                last_timesheet_date = last_ts.write_date if last_ts else ''

        # عدد تاسكات "خطر التأخر القريب" (pacing risk) - بيتغيّر بمرور الوقت
        # لحاله (بدون أي write حقيقي)، تماماً متل overdue_tasks، فلازم يكون
        # جوا البصمة عشان عبور نسبة 80% ما يفوت لو باقي كل شي ثابت.
        pacing_risk_count = len(self._kh_ai_pacing_risk_tasks(all_tasks, today_str))

        return '|'.join(str(x) for x in [
            _KH_AI_PROMPT_VERSION,
            len(open_tasks), len(overdue_tasks),
            len(overdue_proj_acts) + len(overdue_task_acts), len(stale_tasks),
            days_since_update, last_message_date, last_task_write,
            last_task_note_date, last_timesheet_date, pacing_risk_count,
            self.stage_id.id,
            round(self.x_ai_outstanding_amount or 0.0, 2),
        ])

    # ------------------------------------------------------------------
    # HTML التقرير الأسبوعي الكامل لمشروع واحد (يستخدم سواء صارت مراجعة
    # جديدة أو تم تجاهلها لعدم وجود جديد - بالحالة الثانية بيستخدم آخر
    # نتيجة محفوظة).
    # ------------------------------------------------------------------
    def _kh_ai_build_weekly_report_html(self, today_str, open_tasks, overdue_tasks, overdue_proj_acts,
                                         overdue_task_acts, today_html, collection_html, alerts_html, next_steps_html):
        return (
            '<div dir="rtl" style="text-align:right;border:2px solid #714B67;border-radius:8px;padding:12px;margin-bottom:10px;">'
            '<h4 style="margin:0 0 8px;color:#714B67;">🤖 التقرير الأسبوعي - مدير المشاريع الذكي - %s</h4>'
            '<p style="color:#666;font-size:12px;">تاسكات مفتوحة: %d | متأخرة: %d | أكتفيتيز متأخرة: %d</p>'
            '<h5 style="color:#714B67;margin:10px 0 4px;">📋 ملخّص</h5>%s'
            '<h5 style="color:#714B67;margin:10px 0 4px;">💰 التحصيل</h5>%s'
            '<h5 style="color:#714B67;margin:10px 0 4px;">⚠️ التنبيهات</h5>%s'
            '<h5 style="color:#714B67;margin:10px 0 4px;">➡️ الخطوات التالية</h5>%s</div>'
            % (today_str, len(open_tasks), len(overdue_tasks),
               len(overdue_proj_acts) + len(overdue_task_acts),
               today_html or '', collection_html or '', alerts_html or '', next_steps_html or '')
        )

    # ------------------------------------------------------------------
    # تنبيه فوري لمدير المشروع (Activity Odoo قياسية - بتفعّل تذكير إيميل
    # حسب تفضيلاته الشخصية) إذا في متأخرات أو تاسكات بدون مسؤول. بتحدّث
    # نفس التنبيه بدل ما تكرره كل يوم لو التشغيل صار Cron يومي.
    # ------------------------------------------------------------------
    def _kh_ai_notify_pm_if_needed(self, open_tasks):
        self.ensure_one()
        if not self.user_id:
            return

        issues = []
        if self.x_ai_overdue_tasks_count:
            issues.append('%d تاسك متأخر' % self.x_ai_overdue_tasks_count)
        if self.x_ai_overdue_activities_count:
            issues.append('%d أكتفيتي متأخر' % self.x_ai_overdue_activities_count)
        unassigned_count = len(open_tasks.filtered(lambda t: not t.user_ids))
        if unassigned_count:
            issues.append('%d تاسك بدون مسؤول' % unassigned_count)

        today = fields.Date.context_today(self)
        existing = self.env['mail.activity'].search([
            ('res_model', '=', 'project.project'),
            ('res_id', '=', self.id),
            ('user_id', '=', self.user_id.id),
            ('summary', 'like', '⚠️ تنبيه AI:'),
        ], limit=1)

        if not issues:
            if existing:
                existing.unlink()
            return

        summary = '⚠️ تنبيه AI: ' + '، '.join(issues)
        if existing:
            existing.write({'summary': summary, 'note': self.x_ai_alerts or self.x_ai_today_summary or '', 'date_deadline': today})
        else:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=summary,
                note=self.x_ai_alerts or self.x_ai_today_summary or '',
                user_id=self.user_id.id,
                date_deadline=today,
            )

    # ------------------------------------------------------------------
    # تاسك حقيقي (mail.activity) للمحاسب (Karan) على هذا المشروع بالتحديد
    # لما يكون في مبلغ متبقّي غير محصّل - مش مجرد ذكر اسمه بالنص، هذا تاسك
    # فعلي بالـ Activities تبعه بـ Odoo. بتحدّث نفس التاسك (مش تكرره) كل
    # مرة تتغيّر فيها الأرقام، وبتحذفه أوتوماتيكياً لو المبلغ تحصّل بالكامل.
    # بالإنجليزي بالكامل (مش عربي) - Karan ما بيحكي عربي. وبأرقام صافية
    # بدون أي HTML/CSS (مش عبر html2plaintext على الحقل المنسّق - هذا كان
    # عم يسرّب نص الـ <style> الخام كنص عادي، لأنه html2plaintext هون ما
    # بيشيل محتوى وسم style).
    # ------------------------------------------------------------------
    def _kh_ai_notify_accountant_if_needed(self, accountant):
        self.ensure_one()
        if not accountant:
            return

        today = fields.Date.context_today(self)
        existing = self.env['mail.activity'].search([
            ('res_model', '=', 'project.project'),
            ('res_id', '=', self.id),
            ('user_id', '=', accountant.id),
            ('summary', 'like', '💰 Collection needed:'),
        ], limit=1)

        outstanding = self.x_ai_outstanding_amount or 0.0
        if outstanding <= 0:
            if existing:
                existing.unlink()
            return

        summary = '💰 Collection needed: %s - Outstanding %.2f' % (self.name, outstanding)
        note = (
            'Invoiced: %.2f | Collected: %.2f | Outstanding: %.2f\n'
            'Please follow up on collection for this project.'
            % (self.x_ai_invoiced_amount or 0.0, self.x_ai_collected_amount or 0.0, outstanding)
        )
        if existing:
            existing.write({'summary': summary, 'note': note, 'date_deadline': today})
        else:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=summary,
                note=note,
                user_id=accountant.id,
                date_deadline=today,
            )

    # ------------------------------------------------------------------
    # ترتيب حسب "الأقدم مراجعة" (والمشاريع يلي ما انراجعت أبداً NULL - أول
    # شي) - لازم هذا الترتيب لأنه كل مشروع بياخد وقت حقيقي (حلقتين Agentic
    # كاملتين)، فلو دورة كاملة (كل المشاريع) أطول من ساعة، بدون هذا
    # الترتيب رح تتكرر معالجة نفس المشاريع الأولى بترتيب البحث الافتراضي
    # كل ساعة، والمشاريع الأخيرة بالقائمة ما توصلها المراجعة أبداً. هيك
    # كل ساعة بتاخد أولوية المشاريع الأكتر تأخّراً بالمراجعة، وبتغطّي كل
    # المشاريع أكيد ولو أخذ الأمر أكتر من دورة واحدة.
    # ------------------------------------------------------------------
    def _kh_ai_target_projects(self):
        return self.search([
            ('active', '=', True),
            ('stage_id.name', 'in', ['Under Processing', 'Sign & Design']),
        ], order='x_ai_last_review_date asc nulls first')

    # ------------------------------------------------------------------
    # التشغيل التلقائي كل ساعة (ir.cron) - تحديث صامت لكل المشاريع النشطة
    # (بدون نشر بالشاتر، بس تحديث الحقول + تنبيه المدير لو في مشكلة حقيقية).
    # كل مشروع بحلقتين Agentic كاملتين (مراجعة رئيسية + تحقق مالي) - يعني
    # ممكن ياخد عشرات الثواني لكل مشروع لحاله. لهذا لازم commit() بعد كل
    # مشروع نجح على حدا (مش بانتظار خلاص كل الدفعة) - لو صار قطع اتصال أو
    # الـ worker انقتل بالنص (متل Connection Lost)، المشاريع يلي خلصت قبل
    # القطع بتبقى محفوظة، بدل ما ترجع كلها صفر لأنها كلها كانت transaction
    # واحدة. فشل مشروع واحد (استثناء) بيتراجع (rollback) لحاله بس، وبيكمل
    # عالتالي - ما بوقف الباقي.
    # ------------------------------------------------------------------
    def _cron_run_ai_review_batch(self):
        batch_start = time.time()
        projects = self._kh_ai_target_projects()
        done = 0
        for project in projects:
            if time.time() - batch_start > CRON_BATCH_TIME_BUDGET_SECONDS:
                _logger.info(
                    'KH_AI_MANAGER: hourly batch time budget (%ds) reached after %d/%d projects - '
                    'stopping cleanly here, the rest have priority next cycle.',
                    CRON_BATCH_TIME_BUDGET_SECONDS, done, len(projects))
                break
            start = time.time()
            try:
                project.action_run_ai_review(post_report=False)
                self.env.cr.commit()
                done += 1
                _logger.info('KH_AI_MANAGER: hourly review OK for project %s (%s) in %.1fs',
                              project.id, project.name, time.time() - start)
            except Exception:
                self.env.cr.rollback()
                _logger.exception('KH_AI_MANAGER: hourly review failed for project %s (%s) after %.1fs',
                                   project.id, project.name, time.time() - start)

    # ------------------------------------------------------------------
    # التقرير الأسبوعي (ir.cron أسبوعي) - نفس التحديث، بس بينشر بالشاتر
    # (المكان الوحيد يلي بيتكرر فيه النشر - تفادياً لـ Spam من التشغيل الساعي).
    # نفس مبدأ commit()/rollback() لكل مشروع لحاله (شرح فوق).
    # ------------------------------------------------------------------
    def _cron_weekly_report_batch(self):
        batch_start = time.time()
        projects = self._kh_ai_target_projects()
        for project in projects:
            if time.time() - batch_start > CRON_BATCH_TIME_BUDGET_SECONDS:
                _logger.info(
                    'KH_AI_MANAGER: weekly batch time budget (%ds) reached - stopping cleanly, '
                    'the rest have priority next cycle. GM digest still uses latest available data.',
                    CRON_BATCH_TIME_BUDGET_SECONDS)
                break
            start = time.time()
            try:
                project.action_run_ai_review(post_report=True)
                self.env.cr.commit()
                _logger.info('KH_AI_MANAGER: weekly report OK for project %s (%s) in %.1fs',
                              project.id, project.name, time.time() - start)
            except Exception:
                self.env.cr.rollback()
                _logger.exception('KH_AI_MANAGER: weekly report failed for project %s (%s) after %.1fs',
                                   project.id, project.name, time.time() - start)
        try:
            self._kh_ai_send_gm_weekly_digest(projects)
            self.env.cr.commit()
        except Exception:
            self.env.cr.rollback()
            _logger.exception('KH_AI_MANAGER: GM weekly digest failed')

    # ------------------------------------------------------------------
    # فقرة سردية لمشروع واحد - مستخدمة بالتقرير الأسبوعي والملخّص اليومي
    # للمدير العام سوا: "شو صار" (من x_ai_today_summary المحفوظ - فيه
    # الوضع العام + آخر تحديث فعلي) و"شو عالق" (من x_ai_alerts المحفوظة).
    # قراءة بس من حقول محفوظة أصلاً - بدون أي استدعاء Claude جديد هون.
    # ------------------------------------------------------------------
    def _kh_ai_render_digest_project_block(self, project, extra_line=''):
        today_text = self._kh_ai_html_to_plain(project.x_ai_today_summary) or 'لا يوجد ملخّص محفوظ بعد.'
        alerts_text = self._kh_ai_html_to_plain(project.x_ai_alerts) or 'لا يوجد تنبيهات.'
        header = '%s (%.0f%% إنجاز' % (project.name, project.x_ai_work_done_tasks)
        if (project.x_ai_outstanding_amount or 0.0) > 0:
            header += ' | متبقّي تحصيل: %.2f' % project.x_ai_outstanding_amount
        header += ')'
        extra_html = '<p style="margin:4px 0 0;color:#27AE60;">%s</p>' % escape(extra_line) if extra_line else ''
        return (
            '<div style="margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid #ddd;">'
            '<p style="margin:0 0 4px;font-weight:bold;color:#714B67;">📌 %s</p>'
            '<p style="margin:0 0 4px;">%s</p>'
            '<p style="margin:0;color:#A8432B;">عالق: %s</p>'
            '%s'
            '</div>'
            % (escape(header), escape(today_text[:600]), escape(alerts_text[:400]), extra_html)
        )

    # ------------------------------------------------------------------
    # تاسكات انخلصت "اليوم بالتحديد" (write_date اليوم + stage.fold/منجزة)
    # - مفيدة بالملخّص اليومي لإظهار الإنجاز الفعلي، مش بس المشاكل. بنميّز
    # التاسك يلي كان متأخر (deadline فات) قبل ما يخلص - هاي أخبار جيدة
    # لازم تُحسب لصالح الفريق، مش تضيع بين التنبيهات.
    # ------------------------------------------------------------------
    def _kh_ai_tasks_closed_today(self, project, today_str):
        return project.task_ids.filtered(
            lambda t: t.write_date and str(t.write_date)[:10] == today_str and self._kh_ai_is_task_done(t))

    # ------------------------------------------------------------------
    # التقرير الأسبوعي الشامل للمدير العام - مش تقرير مشروع لحاله، إنما
    # نظرة عامة على كل المشاريع سوا: حمل الفريق مجمّع (مين شغال عالشو بكل
    # المشاريع)، وفقرة سردية لكل مشروع (شو صار + شو عالق). بيوصله بطريقتين
    # (Inbox عبر message_notify + إيميل مباشر) عشان نضمن يشوفه أكيد، حسب
    # طلب صاحب العمل تحديداً - بيصير مرة وحدة أسبوعياً بعد ما كل المشاريع
    # تتحدّث (فريش، مش أرقام قديمة).
    # ------------------------------------------------------------------
    def _kh_ai_send_gm_weekly_digest(self, projects):
        gm = self._kh_ai_find_general_manager()
        if not gm or not gm.partner_id:
            _logger.warning('KH_AI_MANAGER: General Manager user not found by name - skipping weekly digest.')
            return
        if not projects:
            return

        today_str = str(fields.Date.context_today(self))
        overdue_projects = projects.filtered(lambda p: p.x_ai_overdue_tasks_count or p.x_ai_overdue_activities_count)
        collection_projects = projects.filtered(lambda p: (p.x_ai_outstanding_amount or 0.0) > 0)
        total_outstanding = sum(projects.mapped('x_ai_outstanding_amount'))

        # حمل الفريق مجمّع عبر كل المشاريع المستهدفة سوا (مش لكل مشروع لحاله)
        workload = defaultdict(lambda: [0, 0])
        for project in projects:
            open_tasks = project.task_ids.filtered(lambda t: not project._kh_ai_is_task_done(t))
            for t in open_tasks:
                is_overdue = bool(t.date_deadline and str(t.date_deadline) < today_str)
                names = t.user_ids.mapped('name') or ['⚠️ غير مسندة']
                for name in names:
                    workload[name][0] += 1
                    if is_overdue:
                        workload[name][1] += 1

        workload_rows = ''.join(
            '<tr><td>%s</td><td style="text-align:center;">%d</td>'
            '<td style="text-align:center;color:%s;">%d</td></tr>'
            % (escape(name), c[0], '#E74C3C' if c[1] else '#888', c[1])
            for name, c in sorted(workload.items(), key=lambda kv: -kv[1][0])
        ) or '<tr><td colspan="3" style="text-align:center;color:#999;">لا يوجد تاسكات مفتوحة حالياً.</td></tr>'

        # فقرة سردية حقيقية لكل مشروع (شو صار + شو عالق) - مش جدول أرقام بس.
        # نستخدم آخر ملخّص/تنبيهات محفوظة (فريش أصلاً، بتتحدّث كل ربع ساعة
        # طول الأسبوع) - بدون أي استدعاء Claude إضافي هون، القراءة بس.
        project_blocks = ''.join(self._kh_ai_render_digest_project_block(p) for p in projects)

        body_html = (
            '%s<div class="kh_ai_box" dir="rtl">'
            '<h3 style="color:#714B67;">🤖 التقرير الأسبوعي الشامل - كل المشاريع - %s</h3>'
            '<p>📊 %d مشروع نشط | ⚠️ %d فيهم متأخرات | 💰 %d محتاجين تحصيل (الإجمالي المتبقّي: %.2f)</p>'
            '<h4 style="color:#714B67;">👥 حمل الفريق (مجمّع على كل المشاريع)</h4>'
            '<table style="width:100%%;border-collapse:collapse;font-size:13px;">'
            '<thead><tr><th style="text-align:right;">الموظف</th><th>مفتوحة</th><th>متأخرة</th></tr></thead>'
            '<tbody>%s</tbody></table>'
            '<h4 style="color:#714B67;margin-top:14px;">📋 شو صار بكل مشروع هذا الأسبوع</h4>'
            '%s</div>'
            % (self._KH_AI_STYLE, today_str, len(projects), len(overdue_projects),
               len(collection_projects), total_outstanding, workload_rows, project_blocks)
        )
        subject = '🤖 التقرير الأسبوعي الشامل - مدير المشاريع الذكي (%s)' % today_str

        try:
            self.env['mail.thread'].message_notify(
                partner_ids=gm.partner_id.ids, subject=subject, body=Markup(body_html))
        except Exception:
            _logger.exception('KH_AI_MANAGER: message_notify to GM failed')

        try:
            self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': body_html,
                'recipient_ids': [(6, 0, gm.partner_id.ids)],
            }).send()
        except Exception:
            _logger.exception('KH_AI_MANAGER: sending GM weekly digest email failed')

    # ------------------------------------------------------------------
    # "في المشروع شي فعلي اليوم؟" - 3 حقائق ملموسة وقابلة للتحقق (مش
    # اعتماد على x_ai_last_review_date/بصمة التغيير الداخلية): (1) تاسك
    # موعده اليوم بالتحديد، (2) رسالة/تعليق على شاتر المشروع اليوم، (3)
    # طلب اعتماد (kh.approval.request) مرتبط بهذا المشروع تحرّك اليوم
    # (أُنشئ أو تغيّرت حالته). لو صفر من الثلاثة، ما في سبب حقيقي نظهر
    # المشروع بالملخّص اليومي.
    # ------------------------------------------------------------------
    def _kh_ai_has_activity_today(self, project, today):
        today_str = str(today)
        date_from_str = today_str + ' 00:00:00'

        if project.task_ids.filtered(lambda t: t.date_deadline and str(t.date_deadline)[:10] == today_str):
            return True

        if self._kh_ai_tasks_closed_today(project, today_str):
            return True

        if self.env['mail.message'].sudo().search_count([
            ('model', '=', 'project.project'),
            ('res_id', '=', project.id),
            ('date', '>=', date_from_str),
        ]):
            return True

        if self.env['kh.approval.request'].sudo().search_count([
            ('project_id', '=', project.id),
            ('write_date', '>=', date_from_str),
        ]):
            return True

        return False

    # ------------------------------------------------------------------
    # الملخّص اليومي للمدير العام - رسالة واحدة كل يوم، بس فيها تفاصيل
    # المشاريع يلي فيها فعلياً شي جديد اليوم (مراجعة حقيقية صارت اليوم -
    # مش متجاهلة بآلية "ما تغيّر شي") - الباقي (الهادئ) بسطر واحد مجمّع
    # بدل ما يتكرر لكل مشروع بلا فايدة. قراءة بس من حقول محفوظة، بدون أي
    # استدعاء Claude جديد - رخيصة تماماً.
    # ------------------------------------------------------------------
    def _kh_ai_send_gm_daily_digest(self, projects):
        gm = self._kh_ai_find_general_manager()
        if not gm or not gm.partner_id:
            _logger.warning('KH_AI_MANAGER: General Manager user not found by name - skipping daily digest.')
            return
        if not projects:
            return

        today = fields.Date.context_today(self)
        today_str = str(today)
        active_today = projects.filtered(lambda p: self._kh_ai_has_activity_today(p, today))
        quiet_count = len(projects) - len(active_today)
        alert_count = len(projects.filtered(lambda p: p.x_ai_overdue_tasks_count or p.x_ai_overdue_activities_count))

        def _closed_today_line(project):
            closed = self._kh_ai_tasks_closed_today(project, today_str)
            if not closed:
                return ''
            names = []
            for t in closed:
                was_overdue = t.date_deadline and str(t.date_deadline)[:10] < today_str
                names.append('%s%s' % (t.name, ' (كان متأخر)' if was_overdue else ''))
            return '✅ خلص اليوم: ' + '، '.join(names)

        project_blocks = ''.join(
            self._kh_ai_render_digest_project_block(p, extra_line=_closed_today_line(p)) for p in active_today)
        if not project_blocks:
            project_blocks = '<p>لا يوجد أي مشروع فيه تحديث فعلي اليوم.</p>'
        quiet_line = '<p>✅ %d مشروع هادئ اليوم بدون أي جديد.</p>' % quiet_count if quiet_count else ''

        subject = '🤖 ملخّص اليوم - مدير المشاريع الذكي (%s)' % today
        body_html = (
            '%s<div class="kh_ai_box" dir="rtl">'
            '<h3 style="color:#714B67;">🤖 ملخّص اليوم - كل المشاريع - %s</h3>'
            '<p>📊 من أصل %d مشروع: %d فيها تحديث فعلي اليوم | %d فيهم تنبيهات نشطة</p>'
            '%s%s</div>'
            % (self._KH_AI_STYLE, today, len(projects), len(active_today), alert_count,
               project_blocks, quiet_line)
        )

        try:
            self.env['mail.thread'].message_notify(
                partner_ids=gm.partner_id.ids, subject=subject, body=Markup(body_html))
        except Exception:
            _logger.exception('KH_AI_MANAGER: message_notify (daily) to GM failed')
        try:
            self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': body_html,
                'recipient_ids': [(6, 0, gm.partner_id.ids)],
            }).send()
        except Exception:
            _logger.exception('KH_AI_MANAGER: sending GM daily digest email failed')

    # ------------------------------------------------------------------
    # Cron يومي (مرة وحدة باليوم) - بس بيبني ويبعت الملخّص، بدون أي مراجعة
    # AI جديدة (هذا الجزء تكفّل فيه الـ Cron الساعي كل ربع ساعة أصلاً).
    # ------------------------------------------------------------------
    def _cron_daily_digest_batch(self):
        try:
            self._kh_ai_send_gm_daily_digest(self._kh_ai_target_projects())
            self.env.cr.commit()
        except Exception:
            self.env.cr.rollback()
            _logger.exception('KH_AI_MANAGER: GM daily digest failed')

    # ------------------------------------------------------------------
    # بناء نص الملخص (Digest) - بيانات فعلية جاهزة، بدون تخمين
    # ------------------------------------------------------------------
    def _kh_ai_build_digest(self, work_done, work_done_tasks, contract_value, invoiced_amount, collected_amount,
                             open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts,
                             messages, today_str, days_since_update=None, stale_tasks=None, accountant=None,
                             task_activity_text=''):
        lines = []
        lines.append('المشروع: %s' % self.name)
        lines.append('المرحلة الحالية: %s' % (self.stage_id.name if self.stage_id else '-'))
        lines.append('مدير المشروع: %s' % (self.user_id.name if self.user_id else '-'))
        lines.append('نسبة الإنجاز المسجّلة يدوياً بـ Odoo: %.1f%%' % work_done)
        lines.append('نسبة الإنجاز محسوبة فعلياً من التاسكات (منجز/الكل غير الملغى): %.1f%%' % work_done_tasks)
        if contract_value:
            lines.append('قيمة العقد: %.2f' % contract_value)
        else:
            lines.append('⚠️ حقيقة مهمة: قيمة العقد (Contract Value) غير معبّأة بسجل المشروع إطلاقاً.')
        lines.append('المفوتر فعلياً (فواتير Odoo حقيقية): %.2f | المحصّل فعلياً (مدفوع): %.2f'
                      % (invoiced_amount, collected_amount))
        lines.append('تاريخ اليوم: %s' % today_str)

        if days_since_update is None:
            lines.append('⚠️ حقيقة مهمة: لا يوجد ولا رسالة/تحديث واحد بسجل نشاط المشروع إطلاقاً.')
        elif days_since_update >= 7:
            lines.append('⚠️ حقيقة مهمة: آخر تحديث/رسالة بسجل النشاط كان قبل %d يوم (فجوة تحديث حقيقية).' % days_since_update)
        else:
            lines.append('آخر تحديث بسجل النشاط: قبل %d يوم.' % days_since_update)

        stale_tasks = stale_tasks or self.env['project.task']
        if stale_tasks:
            lines.append('⚠️ حقيقة مهمة: %d تاسك مفتوح ما تحرّك (بدون أي تعديل) منذ 14 يوم أو أكتر: %s'
                          % (len(stale_tasks), ', '.join(stale_tasks.mapped('name')[:10])))

        if accountant:
            lines.append('المحاسب المسؤول عن التحصيل: %s (user_id=%d) - لو في ملاحظة تحصيل، وجّهها له بالاسم.'
                          % (accountant.name, accountant.id))
        else:
            lines.append('تنويه: ما لقيت مستخدم اسمه "Karan" بالنظام حالياً.')

        lines.append('\n--- التاسكات المفتوحة (غير Approved/Done) - العدد: %d ---' % len(open_tasks))
        for t in open_tasks:
            deadline = str(t.date_deadline)[:10] if t.date_deadline else 'بدون موعد'
            try:
                state_label = dict(t._fields['state'].selection or []).get(t.state, t.state or '-')
            except Exception:
                state_label = t.state or '-'
            overdue_tag = ' [متأخرة]' if t in overdue_tasks else ''
            assignees = ', '.join(t.user_ids.mapped('name')) or 'غير مسندة'
            lines.append('  📌 %s | المكلّف: %s | الحالة: %s | الموعد: %s%s'
                          % (t.name, assignees, state_label, deadline, overdue_tag))

        lines.append('\n--- أكتفيتيز متأخرة على المشروع - العدد: %d ---' % len(overdue_proj_acts))
        for a in overdue_proj_acts:
            summ = a.summary or (a.activity_type_id.name if a.activity_type_id else 'بدون عنوان')
            lines.append('  🔔 %s (موعدها كان: %s)' % (summ, a.date_deadline))

        lines.append('\n--- أكتفيتيز متأخرة على التاسكات - العدد: %d ---' % len(overdue_task_acts))
        for a in overdue_task_acts:
            summ = a.summary or (a.activity_type_id.name if a.activity_type_id else 'بدون عنوان')
            task_name = a.res_id and self.env['project.task'].sudo().browse(a.res_id).name or '-'
            lines.append('  🔔 [%s] %s (موعدها كان: %s)' % (task_name, summ, a.date_deadline))

        lines.append('\n--- سجل نشاط المشروع (آخر %d يوم) ---' % DIGEST_DAYS)
        if not messages:
            lines.append('  لا يوجد رسائل مسجّلة.')
        for m in messages:
            body_txt = html2plaintext(m.body or '').strip()
            subj_txt = (m.subject or '').strip()
            content = body_txt or subj_txt
            if not content:
                continue
            author = m.author_id.name if m.author_id else '?'
            lines.append('  [%s] %s (%s): %s' % (str(m.date)[:16], author, m.message_type, content[:500]))

        if task_activity_text:
            lines.append('\n--- نشاط فعلي داخل التاسكات (ملاحظات + ساعات تايمشيت مسجّلة) ---')
            lines.append(task_activity_text)

        return '\n'.join(lines)

    _KH_AI_REVIEW_TOOL = {
        'name': 'provide_project_review',
        'description': (
            'إرجاع محتوى مراجعة المشروع بـ 4 أقسام - نص عادي بس بكل قيمة، بدون HTML. '
            'استدعِ هذه الأداة فقط لما تكون خلصت الاستكشاف وجاهز للنتيجة النهائية.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'general_status': {
                    'type': 'string',
                    'description': (
                        'جملة أو جملتين بس: الوضع العام للمشروع بشكل شامل (المرحلة، نسبة الإنجاز '
                        'التقريبية، الانطباع العام) - مش عن اليوم تحديداً، هذا سياق عام ثابت نسبياً.'
                    ),
                },
                'today_update': {
                    'type': 'string',
                    'description': (
                        '⚠️ هذا القسم لازم يكون فعلياً عن اليوم/آخر 24 ساعة بس - مش تكرار للوضع '
                        'العام. فقرة قصيرة (2-4 جمل): شو تحرّك بالمشروع تحديداً اليوم أو بآخر '
                        'تحديث فعلي (رسالة شاتر جديدة، تاسك تحرّك، نشاط استُلم) - استند فقط على '
                        'التواريخ الفعلية بالبيانات. لو مافي أي حركة اليوم تحديداً، قول هذا بوضوح '
                        'صراحةً (مثلاً: "لا يوجد أي تحديث اليوم - آخر حركة كانت قبل X أيام") بدل '
                        'ما تعيد وصف الوضع العام كأنه تحديث جديد.'
                    ),
                },
                'collection_note': {
                    'type': 'string',
                    'description': (
                        'فقرة (2-5 جمل) عن وضع التحصيل المالي: قارن الإنجاز (يدوي وحسب التاسكات) مع '
                        'التحصيل الفعلي، ووضّح أي فجوة. الأرقام المالية المرفقة بالبيانات (المفوتر/'
                        'المحصّل) مدقّقة مسبقاً بفحص مالي منفصل - اعتمد عليها كما هي، مش مطلوب منك '
                        'تتحقق منها بنفسك. لو في نقطة يلزم المحاسب يتابعها، وجّهها له بالاسم (موجود '
                        'بالمعرّفات أعلاه لو موجود بالنظام).'
                    ),
                },
                'alerts': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'type': {
                                'type': 'string',
                                'enum': ['missing_update', 'stale_task', 'overdue', 'unassigned', 'financial', 'other'],
                                'description': (
                                    'نوع التنبيه: missing_update (مافي تحديث بالسجل)، stale_task '
                                    '(تاسك ما تحرّك)، overdue (متأخر)، unassigned (بدون مسؤول)، '
                                    'financial (فجوة مالية)، other (أي ملاحظة ذكية تانية لاحظتها انت '
                                    'وما بتنطبق على الأنواع فوق - هذا القسم يلي بيخليك تفكّر مش بس تعدّ).'
                                ),
                            },
                            'message': {'type': 'string', 'description': 'نص التنبيه، جملة أو جملتين، واضح ومباشر.'},
                        },
                        'required': ['type', 'message'],
                    },
                    'description': (
                        'كل التنبيهات المهمة - لازم تشمل حقائق "مهمة" المذكورة بالبيانات (مافي تحديث/'
                        'تاسكات ما تحرّكت) إذا موجودة، بالإضافة لأي مشكلة حقيقية تانية تلاحظها انت '
                        '(نوع other) - فكّر متل مدير مشاريع حقيقي بيحاول يحل مشاكل الموقع، مش بس عداد. '
                        'لو ما في أي تنبيه فعلي، رجّع array فاضية [].'
                    ),
                },
                'next_steps': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'minItems': 2,
                    'description': (
                        '⚠️ إلزامي - ممنوع تكون array فاضية أبداً، حتى لو المشروع هادئ وما في أي '
                        'تنبيهات: 2 إلى 5 خطوات تالية ملموسة ومباشرة لمدير المشروع، كل واحدة جملة '
                        'واحدة واضحة. لو المشروع فعلاً ماشي تمام بدون مشاكل، اقترح خطوات متابعة '
                        'عادية بردو (مثلاً: تأكيد مع الفريق إنه الموعد الجاي واضح، تحديث العميل '
                        'بالتقدّم، مراجعة التاسكات المفتوحة القريبة من موعدها) - مش تسيبها فاضية. '
                        'لازم تكون array حقيقية (عنصر نص لكل خطوة)، مش نص واحد فيه أقواس/فواصل.'
                    ),
                },
            },
            'required': ['general_status', 'today_update', 'collection_note', 'alerts', 'next_steps'],
        },
    }

    def _kh_ai_build_seed_context(self):
        parts = []
        if self.partner_id:
            parts.append('العميل (partner_id): %s (id=%d)' % (self.partner_id.name, self.partner_id.id))
        analytic_field = self._kh_ai_analytic_account_field_name()
        analytic_account = self._kh_ai_read_studio_value(analytic_field) if analytic_field else False
        if analytic_account:
            parts.append('الحساب التحليلي (Analytic Account): %s (id=%d)' % (analytic_account.name, analytic_account.id))
        accountant = self._kh_ai_find_accountant_user()
        if accountant:
            parts.append('المحاسب المسؤول عن التحصيل (Karan): %s (user_id=%d)' % (accountant.name, accountant.id))
        parts.append('project_id = %d' % self.id)
        return '\n'.join(parts) if parts else 'لا يوجد معرّفات إضافية (عميل/حساب تحليلي) لهذا المشروع.'

    # ------------------------------------------------------------------
    # استدعاء Claude Agentic - نعطيه أداة بحث حرّة (search_odoo_records) على
    # النماذج المسموحة (project/task/CRM/purchase/account/approvals/partner)
    # بالإضافة لملخّص جاهز، وبيقرر هو لحاله شو يحتاج يفتش زيادة (متل CRM أو
    # أوامر شراء)، لحد ما يستدعي provide_project_review بالنتيجة النهائية.
    # يرجع (data_dict, error_html) - وحدة منهم دايماً None.
    # ------------------------------------------------------------------
    def _kh_ai_claude_review(self, digest_text):
        warn_box = '<div style="color:#856404;background:#fff3cd;padding:8px 12px;border-radius:6px;">%s</div>'

        if not HAS_ANTHROPIC:
            return None, warn_box % '⚠️ مكتبة anthropic غير مثبّتة.'

        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('mcp_server.anthropic_api_key')
        model = ICP.get_param('mcp_server.anthropic_model') or DEFAULT_MODEL
        if not api_key:
            return None, warn_box % '⚠️ مفتاح mcp_server.anthropic_api_key غير موجود في إعدادات Odoo.'

        prompt = (
            "أنت مساعد مدير مشاريع خبير بشركة هندسية وتجارية بالإمارات - بتفكّر متل مدير مشاريع حقيقي "
            "بيحاول يحل مشاكل الموقع، مش بس نظام بيعدّ أرقام.\n"
            "البيانات أدناه مستخرجة مباشرة من نظام Odoo (تاسكات، أكتفيتيز، فواتير حقيقية، سجل نشاط/شاتر المشروع) وهي دقيقة 100%%.\n"
            "ممنوع منعاً باتاً أن تخترع أو تغيّر أي رقم (عدد التاسكات، التواريخ، المبالغ المالية، النسب) - اعتمد عليها كما هي فقط.\n"
            "قارن ثلاث نسب مع بعضها: (1) نسبة الإنجاز المسجّلة يدوياً بـ Odoo، (2) نسبة الإنجاز المحسوبة فعلياً من "
            "التاسكات المنجزة، (3) نسبة التحصيل الفعلي (المحصّل/قيمة العقد). إذا في فرق واضح بين أي منهم - "
            "خصوصاً إذا نسبة التاسكات المنجزة أعلى بكثير من نسبة التحصيل، أو النسبة اليدوية بعيدة عن نسبة التاسكات - "
            "هاي فجوة مهمة لازم تنبّه عليها بوضوح بقسم collection_note.\n"
            "لو في مشروع بدون أي تحديث حديث بسجل النشاط، أو تاسكات مفتوحة ما تحرّكت من فترة طويلة - هاي "
            "حقائق جاهزة بالبيانات تحت، لازم تظهر بقسم alerts (type: missing_update / stale_task).\n\n"
            "مهم: قسم 'نشاط فعلي داخل التاسكات' تحت (لو موجود) هو ملاحظات/ساعات تايمشيت مسجّلة "
            "داخل تاسكات لحالها (مش على شاتر المشروع العام) - هذا غالباً أدق مصدر لـ 'شو صار اليوم' "
            "فعلياً، خصوصاً لو مافي شي جديد بسجل نشاط المشروع نفسه. اعتمد عليه بقسم today_update.\n\n"
            "بخصوص الفواتير: الرقم المرفق (المفوتر/المحصّل تحت) مُدقّق مسبقاً بفحص مالي منفصل عبر فواتير "
            "حقيقية - اعتمد عليه كما هو، مش مطلوب منك تتحقق منه بنفسك.\n\n"
            "معرّفات مفيدة للاستكشاف:\n%s\n\n"
            "عندك أداة search_odoo_records تقدر تستخدمها (أكتر من مرة إذا لزم) لتتحقق من معلومات إضافية "
            "مرتبطة بهذا المشروع - مثلاً: عروض/فرص CRM لهذا العميل، أوامر شراء (purchase.order) مرتبطة "
            "بالحساب التحليلي، أو طلبات اعتماد (kh.approval.request) معلّقة. استخدمها بحرية (لحد 3-4 "
            "استدعاءات) لو تحتاج سياق إضافي غير موجود بالبيانات تحت.\n\n"
            "البيانات:\n"
            "--------------------------------------------------\n"
            "%s\n"
            "--------------------------------------------------\n\n"
            "لما تخلص استكشاف، استدعِ أداة provide_project_review بمحتوى نصي عادي بس (بدون HTML) بـ 5 "
            "قيم: general_status (وضع عام مختصر)، today_update (تحديداً اليوم/آخر 24 ساعة - مختلف "
            "عن general_status، مش تكرار له)، ملاحظة التحصيل، التنبيهات، الخطوات التالية. تنبيه "
            "مهم: قسم next_steps ممنوع يكون فاضي أبداً، حتى لو المشروع هادئ بدون أي مشاكل - لازم "
            "يحتوي على الأقل خطوتين متابعة ملموسة (حتى لو كانت خطوات متابعة عادية زي تأكيد الموعد "
            "الجاي أو تحديث العميل)."
            % (self._kh_ai_build_seed_context(), digest_text)
        )

        tools = [self._KH_AI_SEARCH_TOOL, self._KH_AI_REVIEW_TOOL]
        messages = [{'role': 'user', 'content': prompt}]

        try:
            client = anthropic.Anthropic(api_key=api_key)
            for _ in range(MAX_AGENTIC_ITERATIONS):
                resp = client.messages.create(
                    model=model, max_tokens=2000, tools=tools, messages=messages)
                messages.append({'role': 'assistant', 'content': resp.content})

                tool_uses = [b for b in (resp.content or []) if getattr(b, 'type', '') == 'tool_use']
                if not tool_uses:
                    break

                review_call = next((b for b in tool_uses if b.name == 'provide_project_review'), None)
                if review_call:
                    return (review_call.input or {}), None

                tool_results = []
                for block in tool_uses:
                    if block.name == 'search_odoo_records':
                        result = self._kh_ai_execute_search_tool(block.input or {})
                    else:
                        result = {'error': 'أداة غير معروفة: %s' % block.name}
                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': block.id,
                        'content': json.dumps(result, default=str, ensure_ascii=False)[:8000],
                    })
                messages.append({'role': 'user', 'content': tool_results})

            raise ValueError('وصل الحد الأقصى لعدد التكرارات (%d) بدون نتيجة نهائية.' % MAX_AGENTIC_ITERATIONS)
        except Exception as e:
            _logger.exception('KH_AI_MANAGER: Claude call failed')
            return None, warn_box % ('⚠️ فشل استدعاء Claude: %s' % str(e)[:200])
