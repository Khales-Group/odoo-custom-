# -*- coding: utf-8 -*-
# ============================================================
#  مدير المشاريع الذكي (AI Project Manager)
#  زر على المشروع: يحسب التاسكات المفتوحة/المتأخرة والأكتفيتيز المتأخرة
#  بالكود (بدون تخمين)، وبعدين يبعت ملخّص لـ Claude API عشان يطلع
#  تقييم للحالة (مطابقة مع الـ chatter؟) واقتراحات للخطوات التالية.
# ============================================================
import json
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
    x_ai_open_tasks_count = fields.Integer(string="تاسكات مفتوحة (AI)", readonly=True, copy=False)
    x_ai_overdue_tasks_count = fields.Integer(string="تاسكات متأخرة (AI)", readonly=True, copy=False)
    x_ai_overdue_activities_count = fields.Integer(string="أكتفيتيز متأخرة (AI)", readonly=True, copy=False)
    x_ai_last_review_date = fields.Datetime(string="آخر مراجعة AI", readonly=True, copy=False)
    x_ai_status_summary = fields.Html(string="تقييم الحالة (AI)", readonly=True, copy=False, sanitize=False)
    x_ai_next_steps = fields.Html(string="الخطوات التالية المقترحة (AI)", readonly=True, copy=False, sanitize=False)

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
            work_done, contract_value, open_tasks, overdue_tasks,
            overdue_proj_acts, overdue_task_acts, messages, today_str)

        status_html, next_steps_html = self._kh_ai_claude_review(digest)

        self.x_ai_status_summary = status_html
        self.x_ai_next_steps = next_steps_html
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
    def _kh_ai_build_digest(self, work_done, contract_value, open_tasks, overdue_tasks,
                             overdue_proj_acts, overdue_task_acts, messages, today_str):
        lines = []
        lines.append('المشروع: %s' % self.name)
        lines.append('المرحلة الحالية: %s' % (self.stage_id.name if self.stage_id else '-'))
        lines.append('مدير المشروع: %s' % (self.user_id.name if self.user_id else '-'))
        lines.append('نسبة الإنجاز: %.1f%% | قيمة العقد: %.2f' % (work_done, contract_value))
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
            "البيانات أدناه مستخرجة مباشرة من نظام Odoo (تاسكات، أكتفيتيز، سجل نشاط/شاتر المشروع) وهي دقيقة 100%%.\n"
            "ممنوع منعاً باتاً أن تخترع أو تغيّر أي رقم (عدد التاسكات، التواريخ) - اعتمد عليها كما هي فقط.\n\n"
            "البيانات:\n"
            "--------------------------------------------------\n"
            "%s\n"
            "--------------------------------------------------\n\n"
            "أجب حصراً بصيغة JSON صحيحة (بدون أي نص قبلها أو بعدها) بالشكل التالي:\n"
            '{"status_summary": "<HTML بسيط: هل الحالة الفعلية (تاسكات/أكتفيتيز) متوافقة مع ما هو مذكور بسجل النشاط؟ '
            'في أي فجوات أو تناقضات؟ أي ملاحظة مالية إذا سجل النشاط ذكر تأخر بفواتير أو دفعات؟>", '
            '"next_steps": "<HTML بسيط (ul/li) لـ 3 إلى 5 خطوات تالية ملموسة ومباشرة لمدير المشروع، '
            'مبنية فقط على التاسكات/الأكتفيتيز المتأخرة والمفتوحة أعلاه>"}\n'
            "استخدم وسوم HTML بسيطة فقط (<p>, <strong>, <ul>, <li>) داخل قيم الـ JSON، بدون Markdown."
            % digest_text
        )

        try:
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                max_tokens=2000,
                messages=[{'role': 'user', 'content': prompt}],
            )
            text = ''.join(
                getattr(block, 'text', '') for block in (resp.content or []) if getattr(block, 'type', '') == 'text'
            ).strip()
            if text.startswith('```'):
                text = text.strip('`')
                if text.lower().startswith('json'):
                    text = text[4:]
            data = json.loads(text)
            status_html = data.get('status_summary') or ''
            next_steps_html = data.get('next_steps') or ''
            return status_html, next_steps_html
        except Exception as e:
            _logger.exception('KH_AI_MANAGER: Claude call failed')
            return warn_box % ('⚠️ فشل استدعاء Claude: %s' % str(e)[:200]), ''
