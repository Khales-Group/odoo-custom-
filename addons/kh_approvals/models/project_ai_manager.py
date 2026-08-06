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
from collections import defaultdict

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.tools import html2plaintext
from odoo.tools.safe_eval import safe_eval

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
MAX_AGENTIC_ITERATIONS = 6

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

    # ---- محسوبة تلقائياً، تظهر فوراً بدون أي زر ----
    x_ai_work_done = fields.Float(string="نسبة الإنجاز حسب Odoo (AI)", compute='_compute_ai_financials')
    x_ai_contract_value = fields.Float(string="قيمة العقد (AI)", compute='_compute_ai_financials')
    x_ai_invoiced_amount = fields.Float(string="المفوتر (AI)", compute='_compute_ai_financials')
    x_ai_collected_amount = fields.Float(string="المحصّل فعلياً (AI)", compute='_compute_ai_financials')
    x_ai_financial_data_note = fields.Char(
        string="ملاحظة بيانات مالية", compute='_compute_ai_financials')

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
    x_ai_today_summary = fields.Html(string="ملخّص اليوم (AI)", readonly=True, copy=False, sanitize=False)
    x_ai_collection_note = fields.Html(string="التحصيل مع المحاسب (AI)", readonly=True, copy=False, sanitize=False)
    x_ai_alerts = fields.Html(string="التنبيهات (AI)", readonly=True, copy=False, sanitize=False)
    x_ai_next_steps = fields.Html(string="الخطوات التالية المقترحة (AI)", readonly=True, copy=False, sanitize=False)
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
            invoiced, collected = project._kh_ai_compute_financials(analytic_field)
            project.x_ai_invoiced_amount = invoiced
            project.x_ai_collected_amount = collected
            project_note = note
            if not project.partner_id and not (analytic_field and project._kh_ai_read_studio_value(analytic_field)):
                extra = '⚠️ هذا المشروع بدون عميل (partner_id) وبدون حساب تحليلي - ما بقدر ألقى فواتيره.'
                project_note = (project_note + ' ' + extra).strip()
            project.x_ai_financial_data_note = project_note or False

    def _kh_ai_compute_financials(self, analytic_field=None):
        # المصدر الأساسي: فواتير العميل (partner_id) تبع المشروع مباشرة - هذا
        # فعلياً كيف الفواتير مربوطة بالمشروع بهذا النظام (تأكدنا منه فعلياً:
        # مافي Analytic Account مستخدم على الفواتير، بس فلترة الفواتير بالعميل
        # هي يلي تطلع النتيجة الصحيحة). الحساب التحليلي (لو موجود) بيتفحص
        # كمان كـ مصدر إضافي، بدون تكرار (نفس الفاتورة ما تُحسب مرتين).
        try:
            Move = self.env['account.move'].sudo()
            moves = Move.browse()

            if self.partner_id:
                moves |= Move.search([
                    ('partner_id', 'child_of', self.partner_id.id),
                    ('state', '=', 'posted'),
                    ('move_type', 'in', ['out_invoice', 'out_refund']),
                ])

            if analytic_field is None:
                analytic_field = self._kh_ai_analytic_account_field_name()
            analytic_account = self._kh_ai_read_studio_value(analytic_field) if analytic_field else False
            if analytic_account:
                AML = self.env['account.move.line'].sudo()
                lines = AML.search([
                    ('analytic_distribution', 'in', [analytic_account.id]),
                    ('parent_state', '=', 'posted'),
                    ('move_id.move_type', 'in', ['out_invoice', 'out_refund']),
                ])
                moves |= lines.mapped('move_id')

            invoiced = sum(m.amount_total_signed for m in moves)
            collected = sum(m.amount_total_signed - m.amount_residual_signed for m in moves)
            return invoiced, collected
        except Exception:
            _logger.exception('KH_AI_MANAGER: financial computation failed')
            return 0.0, 0.0

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
            return '<p style="color:#999;">لا يوجد تاسكات مفتوحة.</p>'

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
            '<table style="width:100%%;border-collapse:collapse;font-size:13px;">'
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
        '.kh_ai_box{line-height:1.8;font-size:14px;}'
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

    def _kh_ai_render_simple_html(self, text):
        text = (text or '').strip()
        if not text:
            return ''
        return '<div class="kh_ai_box">%s<p>%s</p></div>' % (self._KH_AI_STYLE, escape(text))

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
            return '<div class="kh_ai_box">%s<p style="color:#27AE60;">✅ لا يوجد تنبيهات حالياً.</p></div>' % self._KH_AI_STYLE
        return '<div class="kh_ai_box">%s%s</div>' % (self._KH_AI_STYLE, ''.join(rows))

    def _kh_ai_render_next_steps_html(self, data):
        steps = [s for s in self._kh_ai_as_list(data.get('next_steps')) if s and str(s).strip()]
        if not steps:
            return ''
        return (
            '<div class="kh_ai_box">%s<ol>%s</ol></div>'
            % (self._KH_AI_STYLE, ''.join('<li>%s</li>' % escape(s) for s in steps))
        )

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
    def action_run_ai_review(self, post_report=False):
        self.ensure_one()
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

        digest = self._kh_ai_build_digest(
            self.x_ai_work_done, self.x_ai_work_done_tasks, self.x_ai_contract_value,
            self.x_ai_invoiced_amount, self.x_ai_collected_amount,
            open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts, messages, today_str,
            days_since_update, stale_tasks, accountant)

        data, error_html = self._kh_ai_claude_review(digest)
        if error_html:
            today_html, collection_html, alerts_html, next_steps_html = error_html, '', '', ''
            data = {}
        else:
            data = data or {}
            today_html = self._kh_ai_render_simple_html(data.get('today_summary'))
            collection_html = self._kh_ai_render_simple_html(data.get('collection_note'))
            alerts_html = self._kh_ai_render_alerts_html(data)
            next_steps_html = self._kh_ai_render_next_steps_html(data)

        preview = ' | '.join(str(s) for s in self._kh_ai_as_list(data.get('next_steps')))
        self.x_ai_today_summary = today_html
        self.x_ai_collection_note = collection_html
        self.x_ai_alerts = alerts_html
        self.x_ai_next_steps = next_steps_html
        self.x_ai_next_steps_preview = (preview[:140] + '…') if len(preview) > 140 else preview
        self.x_ai_last_review_date = fields.Datetime.now()

        if self.user_id and self.user_id.partner_id:
            self.message_subscribe(partner_ids=self.user_id.partner_id.ids)

        if post_report:
            report_html = (
                '<div style="border:2px solid #714B67;border-radius:8px;padding:12px;margin-bottom:10px;">'
                '<h4 style="margin:0 0 8px;color:#714B67;">🤖 التقرير الأسبوعي - مدير المشاريع الذكي - %s</h4>'
                '<p style="color:#666;font-size:12px;">تاسكات مفتوحة: %d | متأخرة: %d | أكتفيتيز متأخرة: %d</p>'
                '<h5 style="color:#714B67;margin:10px 0 4px;">📋 ملخّص</h5>%s'
                '<h5 style="color:#714B67;margin:10px 0 4px;">💰 التحصيل</h5>%s'
                '<h5 style="color:#714B67;margin:10px 0 4px;">⚠️ التنبيهات</h5>%s'
                '<h5 style="color:#714B67;margin:10px 0 4px;">➡️ الخطوات التالية</h5>%s</div>'
                % (today_str, len(open_tasks), len(overdue_tasks),
                   len(overdue_proj_acts) + len(overdue_task_acts),
                   today_html, collection_html, alerts_html, next_steps_html)
            )
            self.message_post(body=Markup(report_html), message_type='comment', subtype_xmlid='mail.mt_comment')

        self._kh_ai_notify_pm_if_needed(open_tasks)
        return True

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

    def _kh_ai_target_projects(self):
        return self.search([
            ('active', '=', True),
            ('stage_id.name', 'in', ['Under Processing', 'Sign & Design']),
        ])

    # ------------------------------------------------------------------
    # التشغيل التلقائي كل ساعة (ir.cron) - تحديث صامت لكل المشاريع النشطة
    # (بدون نشر بالشاتر، بس تحديث الحقول + تنبيه المدير لو في مشكلة حقيقية).
    # فشل مشروع واحد ما بوقف الباقي.
    # ------------------------------------------------------------------
    def _cron_run_ai_review_batch(self):
        for project in self._kh_ai_target_projects():
            try:
                project.action_run_ai_review(post_report=False)
            except Exception:
                _logger.exception('KH_AI_MANAGER: hourly review failed for project %s (%s)',
                                   project.id, project.name)

    # ------------------------------------------------------------------
    # التقرير الأسبوعي (ir.cron أسبوعي) - نفس التحديث، بس بينشر بالشاتر
    # (المكان الوحيد يلي بيتكرر فيه النشر - تفادياً لـ Spam من التشغيل الساعي).
    # ------------------------------------------------------------------
    def _cron_weekly_report_batch(self):
        for project in self._kh_ai_target_projects():
            try:
                project.action_run_ai_review(post_report=True)
            except Exception:
                _logger.exception('KH_AI_MANAGER: weekly report failed for project %s (%s)',
                                   project.id, project.name)

    # ------------------------------------------------------------------
    # بناء نص الملخص (Digest) - بيانات فعلية جاهزة، بدون تخمين
    # ------------------------------------------------------------------
    def _kh_ai_build_digest(self, work_done, work_done_tasks, contract_value, invoiced_amount, collected_amount,
                             open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts,
                             messages, today_str, days_since_update=None, stale_tasks=None, accountant=None):
        lines = []
        lines.append('المشروع: %s' % self.name)
        lines.append('المرحلة الحالية: %s' % (self.stage_id.name if self.stage_id else '-'))
        lines.append('مدير المشروع: %s' % (self.user_id.name if self.user_id else '-'))
        lines.append('نسبة الإنجاز المسجّلة يدوياً بـ Odoo: %.1f%%' % work_done)
        lines.append('نسبة الإنجاز محسوبة فعلياً من التاسكات (منجز/الكل غير الملغى): %.1f%%' % work_done_tasks)
        lines.append('قيمة العقد: %.2f' % contract_value)
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
                'today_summary': {
                    'type': 'string',
                    'description': (
                        'فقرة قصيرة (2-4 جمل): شو صار بالمشروع اليوم/آخر تحديث فعلي - بناءً على سجل '
                        'النشاط الأحدث والتاسكات المتحرّكة. إذا مافي شي جديد اليوم، قول هذا بوضوح.'
                    ),
                },
                'collection_note': {
                    'type': 'string',
                    'description': (
                        'فقرة (2-4 جمل) عن وضع التحصيل المالي: قارن الإنجاز (يدوي وحسب التاسكات) مع '
                        'التحصيل الفعلي، ووضّح أي فجوة. لو في نقطة يلزم المحاسب يتابعها، وجّهها له '
                        'بالاسم (موجود بالمعرّفات أعلاه لو موجود بالنظام).'
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
                    'description': (
                        '3 إلى 5 خطوات تالية ملموسة ومباشرة لمدير المشروع، كل واحدة جملة واحدة واضحة. '
                        'لازم تكون array حقيقية (عنصر نص لكل خطوة)، مش نص واحد فيه أقواس/فواصل.'
                    ),
                },
            },
            'required': ['today_summary', 'collection_note', 'alerts', 'next_steps'],
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
            "معرّفات مفيدة للاستكشاف:\n%s\n\n"
            "عندك أداة search_odoo_records تقدر تستخدمها (أكتر من مرة إذا لزم) لتتحقق من معلومات إضافية "
            "مرتبطة بهذا المشروع - مثلاً: عروض/فرص CRM لهذا العميل، أوامر شراء (purchase.order) مرتبطة "
            "بالحساب التحليلي، طلبات اعتماد (kh.approval.request) معلّقة، أو تفاصيل فواتير إضافية. "
            "استخدمها فقط لو فعلاً بتضيف معلومة مفيدة، وما تلزّق أكتر من 3-4 استدعاءات.\n\n"
            "البيانات:\n"
            "--------------------------------------------------\n"
            "%s\n"
            "--------------------------------------------------\n\n"
            "لما تخلص استكشاف، استدعِ أداة provide_project_review بمحتوى نصي عادي بس (بدون HTML) بـ 4 "
            "أقسام: ملخّص اليوم، ملاحظة التحصيل، التنبيهات، الخطوات التالية."
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
