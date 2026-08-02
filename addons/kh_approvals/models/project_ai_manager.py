# -*- coding: utf-8 -*-
# ============================================================
#  مدير المشاريع الذكي (AI Project Manager)
#  زر على المشروع: يحسب التاسكات المفتوحة/المتأخرة والأكتفيتيز المتأخرة
#  بالكود (بدون تخمين)، وبعدين يبعت ملخّص لـ Claude API عشان يطلع
#  تقييم للحالة (مطابقة مع الـ chatter؟) واقتراحات للخطوات التالية.
# ============================================================
import logging

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

    x_ai_work_done = fields.Float(string="نسبة الإنجاز (AI)", readonly=True, copy=False)
    x_ai_contract_value = fields.Float(string="قيمة العقد (AI)", readonly=True, copy=False)
    x_ai_invoiced_amount = fields.Float(string="المفوتر (AI)", readonly=True, copy=False)
    x_ai_collected_amount = fields.Float(string="المحصّل فعلياً (AI)", readonly=True, copy=False)
    x_ai_open_tasks_count = fields.Integer(string="تاسكات مفتوحة (AI)", readonly=True, copy=False)
    x_ai_overdue_tasks_count = fields.Integer(string="تاسكات متأخرة (AI)", readonly=True, copy=False)
    x_ai_overdue_activities_count = fields.Integer(string="أكتفيتيز متأخرة (AI)", readonly=True, copy=False)
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

    # ------------------------------------------------------------------
    # التحصيل المالي الفعلي - من فواتير Odoo الحقيقية المرتبطة بالمشروع عبر
    # الحساب التحليلي (Analytic Account)، مش رقم يدوي. نكتشف اسم حقل الحساب
    # التحليلي ديناميكياً (تغيّر بين إصدارات Odoo: account_id/analytic_account_id)
    # بدل ما نثبّت اسم معيّن، وأي فشل بيرجع صفر بهدوء بدل ما يكسر المراجعة.
    # ------------------------------------------------------------------
    def _kh_ai_find_analytic_account(self):
        for fname, f in self._fields.items():
            if f.type == 'many2one' and getattr(f, 'comodel_name', None) == 'account.analytic.account':
                try:
                    val = self[fname]
                except Exception:
                    continue
                if val:
                    return val
        return False

    def _kh_ai_compute_financials(self):
        try:
            analytic_account = self._kh_ai_find_analytic_account()
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
    # الميثود الرئيسية - تُستدعى من زر "🤖 مراجعة AI" على فورم المشروع
    # ------------------------------------------------------------------
    def action_run_ai_review(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        today_str = str(today)
        date_from = fields.Datetime.to_string(
            fields.Datetime.subtract(fields.Datetime.now(), days=DIGEST_DAYS)
        )

        # ---- Work Done % وContract Value (حقول Studio، اسمها التقني مُكتشف وقت التشغيل) ----
        work_done_field = self._kh_ai_find_studio_field(
            ['work done', 'إنجاز', 'انجاز', 'progress'], ['float', 'integer', 'monetary'])
        contract_value_field = self._kh_ai_find_studio_field(
            ['contract value', 'قيمة العقد'], ['float', 'integer', 'monetary'])
        work_done = self._kh_ai_read_studio_value(work_done_field) or 0.0
        contract_value = self._kh_ai_read_studio_value(contract_value_field) or 0.0
        self.x_ai_work_done = work_done
        self.x_ai_contract_value = contract_value

        # ---- التحصيل المالي الفعلي (من فواتير Odoo الحقيقية عبر Analytic Account) ----
        invoiced_amount, collected_amount = self._kh_ai_compute_financials()
        self.x_ai_invoiced_amount = invoiced_amount
        self.x_ai_collected_amount = collected_amount

        # ---- التاسكات ----
        Task = self.env['project.task'].sudo()
        all_tasks = Task.search([('project_id', '=', self.id)])
        open_tasks = all_tasks.filtered(lambda t: (t.x_custom_state or '') not in DONE_STATES)
        overdue_tasks = open_tasks.filtered(
            lambda t: t.date_deadline and str(t.date_deadline) < today_str)

        # ---- الأكتفيتيز المتأخرة (على المشروع نفسه وعلى تاسكاته) ----
        Activity = self.env['mail.activity'].sudo()
        proj_activities = Activity.search([('res_model', '=', 'project.project'), ('res_id', '=', self.id)])
        task_activities = Activity.search([('res_model', '=', 'project.task'), ('res_id', 'in', all_tasks.ids)]) \
            if all_tasks else Activity.browse()
        overdue_proj_acts = proj_activities.filtered(lambda a: a.date_deadline and str(a.date_deadline) < today_str)
        overdue_task_acts = task_activities.filtered(lambda a: a.date_deadline and str(a.date_deadline) < today_str)

        self.x_ai_open_tasks_count = len(open_tasks)
        self.x_ai_overdue_tasks_count = len(overdue_tasks)
        self.x_ai_overdue_activities_count = len(overdue_proj_acts) + len(overdue_task_acts)

        # ---- الشاتر (chatter) تبع المشروع خلال آخر DIGEST_DAYS يوم ----
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'project.project'),
            ('res_id', '=', self.id),
            ('date', '>=', date_from),
            ('message_type', 'in', ['comment', 'email', 'notification']),
        ], order='date desc', limit=40)

        digest = self._kh_ai_build_digest(
            work_done, contract_value, invoiced_amount, collected_amount, open_tasks, overdue_tasks,
            overdue_proj_acts, overdue_task_acts, messages, today_str)

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
    def _kh_ai_build_digest(self, work_done, contract_value, invoiced_amount, collected_amount,
                             open_tasks, overdue_tasks, overdue_proj_acts, overdue_task_acts,
                             messages, today_str):
        lines = []
        lines.append('المشروع: %s' % self.name)
        lines.append('المرحلة الحالية: %s' % (self.stage_id.name if self.stage_id else '-'))
        lines.append('مدير المشروع: %s' % (self.user_id.name if self.user_id else '-'))
        lines.append('نسبة الإنجاز: %.1f%% | قيمة العقد: %.2f' % (work_done, contract_value))
        lines.append('المفوتر فعلياً (فواتير Odoo حقيقية): %.2f | المحصّل فعلياً (مدفوع): %.2f'
                      % (invoiced_amount, collected_amount))
        lines.append('تاريخ اليوم: %s' % today_str)

        lines.append('\n--- التاسكات المفتوحة (غير Approved/Done) - العدد: %d ---' % len(open_tasks))
        for t in open_tasks:
            deadline = str(t.date_deadline)[:10] if t.date_deadline else 'بدون موعد'
            state_label = dict(t._fields['x_custom_state'].selection or []).get(t.x_custom_state, t.x_custom_state or '-')
            overdue_tag = ' [متأخرة]' if t in overdue_tasks else ''
            lines.append('  📌 %s | الحالة: %s | الموعد: %s%s' % (t.name, state_label, deadline, overdue_tag))

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
            "ممنوع منعاً باتاً أن تخترع أو تغيّر أي رقم (عدد التاسكات، التواريخ، المبالغ المالية) - اعتمد عليها كما هي فقط.\n"
            "قارن نسبة المحصّل فعلياً (المدفوع) لقيمة العقد مع نسبة الإنجاز - إذا التحصيل أقل بشكل واضح من نسبة الإنجاز، "
            "هاي فجوة مالية مهمة لازم تنبّه عليها بوضوح بتقييم الحالة.\n\n"
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
                            'وبند مالي واضح: قارن نسبة التحصيل الفعلي (المدفوع/قيمة العقد) مع نسبة '
                            'الإنجاز - نبّه إذا كان التحصيل متأخر بشكل ملحوظ عن الإنجاز.'
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
