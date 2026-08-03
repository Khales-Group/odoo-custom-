# -*- coding: utf-8 -*-
# ============================================================
#  مدير المشاريع الذكي (AI Project Manager)
#  الأرقام والقوائم (تاسكات مفتوحة/متأخرة، أكتفيتيز متأخرة، إسناد المهام،
#  التحصيل المالي) محسوبة تلقائياً بالكود وتظهر فوراً بدون أي زر - مافي
#  شي منها يحتاج استدعاء AI. زر "🤖 تشغيل مراجعة AI" الوحيد المطلوب هو
#  فقط للجزء المكلف: تحليل Claude النصي (تقييم الحالة + الخطوات التالية).
# ============================================================
import logging
from collections import defaultdict

from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools import html2plaintext

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

    # ---- الوحيدة يلي بتحتاج زر (استدعاء Claude فعلي) ----
    x_ai_last_review_date = fields.Datetime(string="آخر مراجعة AI", readonly=True, copy=False)
    x_ai_status_summary = fields.Html(string="تقييم الحالة (AI)", readonly=True, copy=False, sanitize=False)
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
    # هل التاسك منجزة؟ - نفس منطق khales_ai_report.py المُثبت شغله فعلياً:
    # الحقل الحقيقي المستخدم بالنظام هو state (المدمج بـ Odoo)، وx_custom_state
    # هو حقل كاستوم إضافي ثبت إنه فاضي لمعظم التاسكات (مش هو يلي فيه البيانات
    # الحقيقية) - نتحقق منه بس كـ fallback ثانوي. وبالإضافة اسم الـ stage
    # كإشارة ثالثة، تماماً متل khales_ai_report.py.
    # ------------------------------------------------------------------
    @staticmethod
    def _kh_ai_is_task_done(task):
        task_state = task.state or task.x_custom_state or ''
        if task_state in DONE_STATES:
            return True
        if task.stage_id and 'done' in (task.stage_id.name or '').lower():
            return True
        return False

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
        if not analytic_field:
            notes.append('⚠️ project.project ما فيه حقل حساب تحليلي (Analytic Account) - ما بقدر أحسب الفواتير.')
        note = ' '.join(notes)

        for project in self:
            project.x_ai_work_done = project._kh_ai_read_studio_value(work_done_field) or 0.0
            project.x_ai_contract_value = project._kh_ai_read_studio_value(contract_value_field) or 0.0
            invoiced, collected = project._kh_ai_compute_financials(analytic_field)
            project.x_ai_invoiced_amount = invoiced
            project.x_ai_collected_amount = collected
            project_note = note
            if analytic_field and not project._kh_ai_read_studio_value(analytic_field):
                extra = '⚠️ هذا المشروع تحديداً غير مرتبط بحساب تحليلي - ما رح تظهر فواتيره.'
                project_note = (project_note + ' ' + extra).strip()
            project.x_ai_financial_data_note = project_note or False

    def _kh_ai_compute_financials(self, analytic_field=None):
        try:
            if analytic_field is None:
                analytic_field = self._kh_ai_analytic_account_field_name()
            analytic_account = self._kh_ai_read_studio_value(analytic_field) if analytic_field else False
            if not analytic_account:
                return 0.0, 0.0
            AML = self.env['account.move.line'].sudo()
            lines = AML.search([
                ('analytic_distribution', 'in', [analytic_account.id]),
                ('parent_state', '=', 'posted'),
                ('move_id.move_type', 'in', ['out_invoice', 'out_refund']),
            ])
            moves = lines.mapped('move_id')
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
    # الميثود الوحيدة يلي بتستدعي Claude - تُستدعى فقط من زر "🤖 مراجعة AI"
    # (الأرقام والقوائم فوق محسوبة أصلاً تلقائياً وما بتحتاج هالزر)
    # ------------------------------------------------------------------
    def action_run_ai_review(self):
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

        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'project.project'),
            ('res_id', '=', self.id),
            ('date', '>=', date_from),
            ('message_type', 'in', ['comment', 'email', 'notification']),
        ], order='date desc', limit=40)

        digest = self._kh_ai_build_digest(
            self.x_ai_work_done, self.x_ai_work_done_tasks, self.x_ai_contract_value,
            self.x_ai_invoiced_amount, self.x_ai_collected_amount,
            open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts, messages, today_str)

        status_html, next_steps_html = self._kh_ai_claude_review(digest)

        preview = html2plaintext(next_steps_html or '').strip().replace('\n', ' ')
        self.x_ai_status_summary = status_html
        self.x_ai_next_steps = next_steps_html
        self.x_ai_next_steps_preview = (preview[:140] + '…') if len(preview) > 140 else preview
        self.x_ai_last_review_date = fields.Datetime.now()

        report_html = (
            '<div style="border:2px solid #714B67;border-radius:8px;padding:12px;margin-bottom:10px;">'
            '<h4 style="margin:0 0 8px;color:#714B67;">🤖 مراجعة مدير المشاريع الذكي - %s</h4>'
            '<p style="color:#666;font-size:12px;">تاسكات مفتوحة: %d | متأخرة: %d | أكتفيتيز متأخرة: %d</p>'
            '%s%s</div>'
            % (today_str, len(open_tasks), len(overdue_tasks),
               len(overdue_proj_acts) + len(overdue_task_acts), status_html, next_steps_html)
        )
        self.message_post(body=Markup(report_html), message_type='comment', subtype_xmlid='mail.mt_comment')
        return True

    # ------------------------------------------------------------------
    # بناء نص الملخص (Digest) - بيانات فعلية جاهزة، بدون تخمين
    # ------------------------------------------------------------------
    def _kh_ai_build_digest(self, work_done, work_done_tasks, contract_value, invoiced_amount, collected_amount,
                             open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts,
                             messages, today_str):
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

    # ------------------------------------------------------------------
    # استدعاء Claude - يرجع (status_summary_html, next_steps_html)
    # ------------------------------------------------------------------
    def _kh_ai_claude_review(self, digest_text):
        warn_box = '<div style="color:#856404;background:#fff3cd;padding:8px 12px;border-radius:6px;">%s</div>'

        if not HAS_ANTHROPIC:
            return warn_box % '⚠️ مكتبة anthropic غير مثبّتة.', ''

        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('mcp_server.anthropic_api_key')
        model = ICP.get_param('mcp_server.anthropic_model') or DEFAULT_MODEL
        if not api_key:
            return warn_box % '⚠️ مفتاح mcp_server.anthropic_api_key غير موجود في إعدادات Odoo.', ''

        prompt = (
            "أنت مساعد مدير مشاريع خبير بشركة هندسية وتجارية بالإمارات.\n"
            "البيانات أدناه مستخرجة مباشرة من نظام Odoo (تاسكات، أكتفيتيز، فواتير حقيقية، سجل نشاط/شاتر المشروع) وهي دقيقة 100%%.\n"
            "ممنوع منعاً باتاً أن تخترع أو تغيّر أي رقم (عدد التاسكات، التواريخ، المبالغ المالية، النسب) - اعتمد عليها كما هي فقط.\n"
            "قارن ثلاث نسب مع بعضها: (1) نسبة الإنجاز المسجّلة يدوياً بـ Odoo، (2) نسبة الإنجاز المحسوبة فعلياً من "
            "التاسكات المنجزة، (3) نسبة التحصيل الفعلي (المحصّل/قيمة العقد). إذا في فرق واضح بين أي منهم - "
            "خصوصاً إذا نسبة التاسكات المنجزة أعلى بكثير من نسبة التحصيل، أو النسبة اليدوية بعيدة عن نسبة التاسكات - "
            "هاي فجوة مهمة (بيانات غير محدّثة أو تحصيل متأخر) لازم تنبّه عليها بوضوح بتقييم الحالة.\n\n"
            "البيانات:\n"
            "--------------------------------------------------\n"
            "%s\n"
            "--------------------------------------------------\n\n"
            "استدعِ أداة provide_project_review بتقييم الحالة والخطوات التالية بناءً على البيانات أعلاه فقط."
            % digest_text
        )

        # نستخدم Tool Use ونجبر Claude على استدعاء أداة بمخرجات مبنية (JSON مضمون
        # الصحة من الـ SDK نفسه) بدل الاعتماد على تحليل نص حر - تفادياً لأخطاء
        # JSON parsing لما يحتوي النص على أقواس/اقتباسات داخل الـ HTML.
        review_tool = {
            'name': 'provide_project_review',
            'description': 'إرجاع تقييم حالة المشروع والخطوات التالية المقترحة.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'status_summary': {
                        'type': 'string',
                        'description': (
                            'HTML بسيط (وسوم <p>/<strong>/<ul>/<li> فقط): هل الحالة الفعلية '
                            '(تاسكات/أكتفيتيز) متوافقة مع سجل النشاط؟ أي فجوات أو تناقضات؟ '
                            'وبند مقارنة واضح بين النسب الثلاث (الإنجاز اليدوي، الإنجاز حسب التاسكات، '
                            'التحصيل الفعلي) - نبّه إذا في فجوة ملحوظة بينهم.'
                        ),
                    },
                    'next_steps': {
                        'type': 'string',
                        'description': (
                            'HTML بسيط (ul/li فقط) لـ 3 إلى 5 خطوات تالية ملموسة ومباشرة '
                            'لمدير المشروع، مبنية فقط على التاسكات/الأكتفيتيز المتأخرة والمفتوحة أعلاه.'
                        ),
                    },
                },
                'required': ['status_summary', 'next_steps'],
            },
        }

        try:
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                max_tokens=2000,
                tools=[review_tool],
                tool_choice={'type': 'tool', 'name': 'provide_project_review'},
                messages=[{'role': 'user', 'content': prompt}],
            )
            tool_block = next(
                (b for b in (resp.content or []) if getattr(b, 'type', '') == 'tool_use'), None)
            if not tool_block:
                raise ValueError('لم يرجع Claude أي نتيجة منظّمة (tool_use).')
            data = tool_block.input or {}
            status_html = data.get('status_summary') or ''
            next_steps_html = data.get('next_steps') or ''
            return status_html, next_steps_html
        except Exception as e:
            _logger.exception('KH_AI_MANAGER: Claude call failed')
            return warn_box % ('⚠️ فشل استدعاء Claude: %s' % str(e)[:200]), ''
