# -*- coding: utf-8 -*-
# ============================================================
#  محتوى models/khales_ai_report.py  (نسخة مخصصة للمشاريع والنوتات)
#  لكل موظف: يجمع شغلو من حيث ما يشتغل فعلاً —
#   • مشاريع: تاسك ← تايمشيت/نوتات/أكتفيتيز ومعرفتها بالتفصيل
#   • قانوني (x_reports): قضية ← تحديثات/ملاحظات/أكتفيتيز
#  Gemini يحلّل المجال الموجود فقط بناءً على النوتات والتايمشيت
# ============================================================
import logging
import datetime

from markupsafe import Markup

from odoo import models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False
    _logger.warning("KH_REPORT: google-genai not installed.")

FLAG = 'color:#E74C3C;font-weight:bold;'


class KhalesAiReport(models.AbstractModel):
    _name = 'khales.ai.report'
    _description = 'Khales Monthly Employee Documentation Report (AI)'

    @staticmethod
    def _fmt(h):
        h = h or 0.0
        hh = int(h)
        mm = int(round((h - hh) * 60))
        return '%d:%02d' % (hh, mm)

    @staticmethod
    def _clip(txt, n):
        txt = (txt or '').strip()
        return (txt[:n] + '…') if len(txt) > n else txt

    def generate_for_user(self, user_id, days=30):
        user = self.env['res.users'].sudo().browse(user_id)
        if not user.exists():
            return False
        section, _ = self._build_user_section(user, days)
        wrapper = ('<div dir="rtl" style="font-family:sans-serif;padding:10px;">'
                   '<h2 style="color:#714B67;">📊 تقرير مهام الموظف: %s</h2>'
                   '<p style="color:#666;">آخر %d يوم</p>%s</div>'
                   % (user.name, days, section))
        return self._finalize('📊 تقرير مهام %s - %s' % (user.name, datetime.date.today()), wrapper)

    def generate_all(self, days=30):
        ICP = self.env['ir.config_parameter'].sudo()
        exclude = (ICP.get_param('khales.report.exclude') or '').lower()
        exclude_names = [x.strip() for x in exclude.split(',') if x.strip()]
        users = self.env['res.users'].sudo().search([('share', '=', False), ('active', '=', True)])
        sections, count = '', 0
        for user in users:
            low = (user.name or '').lower()
            if any(x in low for x in exclude_names):
                continue
            sec, has_data = self._build_user_section(user, days)
            if has_data:
                sections += sec
                count += 1
        if not sections:
            sections = '<p style="color:#999;">لا يوجد نشاط مسجّل لأي موظف.</p>'
        wrapper = ('<div dir="rtl" style="font-family:sans-serif;padding:10px;">'
                   '<h2 style="color:#714B67;">📊 تقرير الموظفين الشهري الموثق</h2>'
                   '<p style="color:#666;">آخر %d يوم — %d موظف</p>%s</div>'
                   % (days, count, sections))
        return self._finalize('📊 تقرير الموظفين الشهري - %s (%d موظف)' % (datetime.date.today(), count), wrapper)

    # ============================================================
    # بناء قسم موظف واحد — جلب المشاريع والنوتات بالتفصيل
    # ============================================================
    def _build_user_section(self, user, days):
        env = self.env
        uid = user.id
        partner_id = user.partner_id.id
        date_to = datetime.date.today()
        date_from = date_to - datetime.timedelta(days=days)
        date_from_str = date_from.strftime('%Y-%m-%d')
        today_str = date_to.strftime('%Y-%m-%d')
        TC = 'padding:6px;border:1px solid #e3e3e3;text-align:center;'
        TD = 'padding:6px;border:1px solid #e3e3e3;text-align:right;'

        flags, digest = [], []

        # ========== مجال المشاريع (تاسك/تايمشيت/نوتات) ==========
        ts_lines = env['account.analytic.line'].sudo().search([
            ('user_id', '=', uid), ('project_id', '!=', False), ('date', '>=', date_from)],
            order='date desc')
        lines_by_task, hours_by_task = {}, {}
        project_names, project_loose = {}, {}
        total_hours, ts_no_desc = 0.0, 0
        for ln in ts_lines:
            pid = ln.project_id.id
            project_names[pid] = ln.project_id.name
            h = ln.unit_amount or 0.0
            total_hours += h
            d = (ln.name or '').strip()
            if not d or d == '/':
                ts_no_desc += 1
            if ln.task_id:
                lines_by_task.setdefault(ln.task_id.id, []).append(ln)
                hours_by_task[ln.task_id.id] = hours_by_task.get(ln.task_id.id, 0.0) + h
            else:
                project_loose[pid] = project_loose.get(pid, 0.0) + h
        if ts_no_desc:
            flags.append('%d سطر تايمشيت بدون وصف' % ts_no_desc)

        user_tasks = env['project.task'].sudo().search([
            ('user_ids', 'in', [uid]), ('write_date', '>=', date_from_str)])
        task_ids = set(user_tasks.ids) | set(lines_by_task.keys())
        all_tasks = env['project.task'].sudo().browse(list(task_ids)).exists()
        tasks_by_project, no_project = {}, []
        for t in all_tasks:
            if t.project_id:
                project_names[t.project_id.id] = t.project_id.name
                tasks_by_project.setdefault(t.project_id.id, []).append(t)
            else:
                no_project.append(t)

        all_pids = sorted(tasks_by_project.keys(), key=lambda p: project_names.get(p, ''))
        for p in project_loose:
            if p not in all_pids:
                all_pids.append(p)

        # مشاريع الموظف هو مديرها (Project Manager = user_id)
        managed_projects = env['project.project'].sudo().search([
            ('user_id', '=', uid),
            ('active', '=', True),
        ])
        for p in managed_projects:
            if p.id not in all_pids:
                project_names[p.id] = p.name
                all_pids.append(p.id)

        # مشاريع كتب فيها الموظف نوتز مباشرة على المشروع هالشهر
        proj_with_notes = env['mail.message'].sudo().search([
            ('model', '=', 'project.project'),
            ('author_id', '=', partner_id),
            ('date', '>=', date_from_str),
            ('message_type', 'in', ['comment', 'email', 'notification']),
        ]).mapped('res_id')
        for p in proj_with_notes:
            if p not in all_pids:
                proj_rec = env['project.project'].sudo().browse(p)
                if proj_rec.exists():
                    project_names[p] = proj_rec.name
                    all_pids.append(p)

        # حقول HTML/text للمشروع — مرة واحدة قبل الحلقة (نفس نهج x_reports)
        proj_html_fields = env['ir.model.fields'].sudo().search_read(
            [('model', '=', 'project.project'),
             ('ttype', 'in', ['html', 'text']),
             ('name', 'like', 'x_studio_')],
            ['name', 'field_description', 'ttype']
        )

        done_count = 0
        projects_html = ''

        if all_pids:
            digest.append('--- مجال المشاريع والمهام الحالية ---')

        for pid in all_pids:
            proj_rec = env['project.project'].sudo().browse(pid)
            pname = (proj_rec.name if proj_rec.exists() else None) or project_names.get(pid, 'مشروع غير محدد')
            proj_tasks = tasks_by_project.get(pid, [])
            loose = project_loose.get(pid, 0.0)

            digest.append('\n=== مشروع: %s ===' % pname)

            # معلومات المشروع الأساسية
            if proj_rec.exists():
                proj_stage   = proj_rec.stage_id.name if proj_rec.stage_id else '-'
                proj_manager = proj_rec.user_id.name if proj_rec.user_id else '-'
                proj_start   = str(proj_rec.date_start) if proj_rec.date_start else '-'
                proj_end     = str(proj_rec.date) if proj_rec.date else '-'
                digest.append('  المرحلة: %s | المدير: %s | البداية: %s | الانتهاء: %s'
                               % (proj_stage, proj_manager, proj_start, proj_end))

                # ---- حقول المشروع (HTML/text) — نفس نهج x_reports ----
                proj_field_texts = []
                for finfo in proj_html_fields:
                    try:
                        val = proj_rec[finfo['name']]
                        if val:
                            txt = html2plaintext(str(val)).strip() if finfo['ttype'] == 'html' else str(val).strip()
                            if txt and len(txt) > 15:
                                proj_field_texts.append('%s:\n%s' % (finfo['field_description'], txt))
                    except Exception:
                        continue
                if proj_field_texts:
                    combined = '\n---\n'.join(proj_field_texts)
                    digest.append('   📋 حقول وتفاصيل المشروع:\n%s' % combined)

            loose_html = ''
            if loose > 0:
                loose_html = ('<div style="font-size:12px;color:#856404;background:#fff3cd;'
                    'padding:4px 8px;border-radius:4px;margin-bottom:8px;">⏱️ وقت عام بدون تاسك: <strong>%s</strong></div>'
                    % self._fmt(loose))
                digest.append('  [وقت عام غير مربوط بتاسك]: %.2f ساعة' % loose)

            # ---- شاتر المشروع (كل الرسائل — نفس نهج x_reports بلا فلتر author) ----
            proj_msgs = env['mail.message'].sudo().search([
                ('model', '=', 'project.project'),
                ('res_id', '=', pid),
                ('date', '>=', date_from_str),
                ('message_type', 'in', ['comment', 'email', 'notification']),
            ], order='date desc', limit=30)

            proj_chat_html = ''
            digest.append('   📋 سجل نشاط المشروع:')
            for m in proj_msgs:
                try:
                    body_txt = html2plaintext(m.body or '').strip()
                    subj_txt = (m.subject or '').strip()
                    author   = m.author_id.name if m.author_id else '?'
                    act_type_name = None
                    try:
                        if m.mail_activity_type_id:
                            act_type_name = m.mail_activity_type_id.name
                    except Exception:
                        pass

                    if act_type_name:
                        content = body_txt or subj_txt or '(تم الإنجاز)'
                        label = '✅ أنجز نشاط'
                        item_style = 'background:#d4edda;color:#155724;border-right:3px solid #28a745;'
                    elif m.message_type == 'email':
                        content = ('الموضوع: %s' % subj_txt + (' | ' + body_txt if body_txt else '')) if subj_txt else (body_txt or '-')
                        label = '📧 بريد إلكتروني'
                        item_style = 'background:#cce5ff;color:#004085;border-right:3px solid #004085;'
                    elif m.message_type == 'notification':
                        content = body_txt or subj_txt or ''
                        label = '🔄 تغيير/تحديث'
                        item_style = 'background:#fff3cd;color:#856404;border-right:3px solid #ffc107;'
                    else:
                        content = body_txt or subj_txt or ''
                        label = '💬 ملاحظة'
                        item_style = 'background:#f8f9fa;color:#333;border-right:3px solid #6c757d;'

                    if not content:
                        continue
                    msg_date = str(m.date)[:16]
                    proj_chat_html += ('<li style="margin:5px 0;padding:6px 10px;%sborder-radius:4px;list-style:none;">'
                                       '<strong>%s</strong> — <span style="color:#555;font-size:11px;">%s</span> '
                                       '<span style="font-size:10px;color:#999;">(%s)</span><br>'
                                       '<span style="font-size:12px;line-height:1.5;">%s</span></li>'
                                       % (item_style, label, author, msg_date,
                                          self._clip(content, 400).replace('\n', '<br>')))
                    digest.append('      [%s] %s (%s): %s' % (label, author, msg_date, self._clip(content, 400)))
                except Exception:
                    continue
            if not proj_chat_html:
                proj_chat_html = '<li style="color:#aaa;list-style:none;padding:6px;">لا يوجد رسائل في الشاتر</li>'

            # ---- أكتفيتيز مفتوحة على المشروع ----
            pacts = env['mail.activity'].sudo().search([
                ('res_model', '=', 'project.project'), ('res_id', '=', pid), ('user_id', '=', uid)])
            pa_html = ''
            for a in pacts:
                over = bool(a.date_deadline and str(a.date_deadline) < today_str)
                clr = FLAG if over else 'color:#27AE60;'
                tag = 'متأخّرة' if over else 'بوقتها'
                if over:
                    flags.append('أكتفيتي متأخّرة على المشروع "%s"' % pname[:30])
                summ = a.summary or (a.activity_type_id.name if a.activity_type_id else 'بدون عنوان')
                pa_html += '<li><span style="%s">[%s]</span> %s (%s)</li>' % (clr, tag, summ, a.date_deadline or '-')
                digest.append('  🔔 أكتفيتي مجدولة: %s (موعد %s)%s' % (summ, a.date_deadline or '-', ' [متأخرة!]' if over else ''))

            project_level_html = (
                '<div style="border:1px solid #b0c4de;border-radius:6px;padding:8px 10px;margin-bottom:8px;background:#f8faff;">'
                '<div style="font-size:12px;color:#2C3E50;font-weight:bold;margin-bottom:4px;">🗒️ سجل نشاط المشروع:</div>'
                '<ul style="margin:3px 0;padding:0;font-size:12px;">%s</ul>'
                '%s'
                '</div>'
                % (proj_chat_html, ('<div style="margin-top:6px;"><strong>🔔 أنشطة مجدولة:</strong><ul style="margin:2px 0;padding-right:18px;font-size:12px;">%s</ul></div>' % pa_html) if pa_html else '')
            )

            NO_TASKS_MSG = (
                '<div style="background:#fdecea;border:1px solid #E74C3C;border-radius:8px;'
                'padding:12px 16px;margin:8px 0;font-size:13px;line-height:1.8;color:#333;">'
                '<strong style="color:#E74C3C;font-size:14px;">🚨 بناءً على الفحص التدقيقي لسجلات نظام Odoo، '
                'تم رصد 3 ثغرات رئيسية تمنع القياس اللوجستي والفني الدقيق للأداء:</strong><br><br>'
                '🚨 <strong>غياب المخطط الزمني (No Timeline):</strong> انعدام تام لأي خطة زمنية أو مخطط يربط '
                'الزيارات بجدول التنفيذ الكلي، مما يجعل التقييم منفصلاً عن مواعيد التسليم النهائية للمشاريع.<br><br>'
                '🚨 <strong>غياب التاسكات التفصيلية المسندة (No Assigned Tasks):</strong> جميع البنود المسجلة '
                'هي مهام تلقائية يولّدها النظام دورياً. يفتقر الحساب تماماً لمهام فنية يدوية محددة '
                '(مثل: استلام حديد التسليح، تدقيق أعمال البلاستر، فحص العزل... إلخ).<br><br>'
                '🚨 <strong>ضبابية نسب الإنجاز العامة:</strong> نظراً لغياب مدخلات البيانات الفنية من الموظف '
                'والمقاولين، فإن نسب الإنجاز العامة تعتمد بالكامل على الاستنتاج التقديري من واقع الملاحظات المقتضبة.'
                '</div>'
            )
            tasks_html = ''
            if not proj_tasks:
                tasks_html = NO_TASKS_MSG
                digest.append('  ⚠️ لا يوجد تاسكات مسندة — غياب المخطط الزمني والمهام التفصيلية وضبابية نسب الإنجاز.')
            for t in proj_tasks:
                stage = t.stage_id.name if t.stage_id else (t.state or '-')
                hrs = hours_by_task.get(t.id, 0.0)
                is_done = (t.state == '1_done') or (t.stage_id and 'done' in (t.stage_id.name or '').lower())
                if is_done:
                    done_count += 1

                # المكلّفون بالتاسك
                assignees = ', '.join(t.user_ids.mapped('name')) if t.user_ids else '⚠️ غير محدد'

                # التواريخ المخططة
                date_start = str(t.planned_date_begin)[:10] if t.planned_date_begin else (
                             str(t.planned_date_start)[:10] if t.planned_date_start else '-')
                date_end   = str(t.date_deadline)[:10] if t.date_deadline else (
                             str(t.date_end)[:10] if t.date_end else '-')

                if is_done and hrs == 0:
                    flags.append('تاسك "%s" Done بدون تسجيل ساعات' % t.name[:35])
                if date_end == '-':
                    flags.append('تاسك "%s" بدون تاريخ انتهاء (Deadline)' % t.name[:35])

                digest.append('  📌 تاسك: %s | المشروع: %s | المرحلة: %s | المكلّفون: %s | يبدأ: %s | ينتهي (Deadline): %s | ساعات: %.2f'
                               % (t.name, pname, stage, assignees, date_start, date_end, hrs))

                ts_html = ''
                for ln in lines_by_task.get(t.id, []):
                    dd = (ln.name or '').strip() or '⚠️ بدون وصف'
                    ts_html += '<tr><td style="%s">%s</td><td style="%s">%s</td><td style="%s">%s</td></tr>' % (
                        TC, ln.date, TD, dd, TC, self._fmt(ln.unit_amount or 0.0))
                    digest.append('      ⏱️ تايمشيت %s: %s (%.2fس)' % (ln.date, dd, ln.unit_amount or 0.0))
                if not ts_html:
                    ts_html = '<tr><td colspan="3" style="%s color:#999;">لا يوجد تايمشيت</td></tr>' % TC

                # نوتات الموظف على التاسك
                tnotes = env['mail.message'].sudo().search([
                    ('model', '=', 'project.task'), ('res_id', '=', t.id),
                    ('author_id', '=', partner_id), ('message_type', '=', 'comment')],
                    order='date desc', limit=15)
                notes_html = ''
                for m in tnotes:
                    txt = html2plaintext(m.body or '').strip()
                    if not txt:
                        continue
                    notes_html += ('<li style="color:#444;">%s '
                                   '<span style="font-size:10px;color:#999;">(%s)</span></li>'
                                   % (self._clip(txt, 300), str(m.date)[:16]))
                    digest.append('      📝 نوت كتبها الموظف (%s): %s' % (str(m.date)[:16], txt))
                if not notes_html:
                    notes_html = '<li style="color:#bbb;">لا يوجد نوتات مسجلة من الموظف</li>'

                tacts = env['mail.activity'].sudo().search([
                    ('res_model', '=', 'project.task'), ('res_id', '=', t.id), ('user_id', '=', uid)])
                acts_html = ''
                for a in tacts:
                    over = bool(a.date_deadline and str(a.date_deadline) < today_str)
                    clr = FLAG if over else 'color:#27AE60;'
                    tag = 'متأخّرة' if over else 'بوقتها'
                    if over:
                        flags.append('أكتفيتي متأخّرة على تاسك "%s"' % t.name[:30])
                    summ = a.summary or (a.activity_type_id.name if a.activity_type_id else 'بدون عنوان')
                    acts_html += '<li><span style="%s">[%s]</span> %s (%s)</li>' % (clr, tag, summ, a.date_deadline or '-')
                    digest.append('      🔔 أكتفيتي: %s (موعد %s)%s' % (summ, a.date_deadline or '-', ' [متأخرة]' if over else ''))
                if not acts_html:
                    acts_html = '<li style="color:#bbb;">لا يوجد</li>'

                tasks_html += (
                    '<div style="border:1px solid #ddd;border-radius:6px;padding:10px;margin:8px 0;background:#fff;">'
                    '<div style="font-weight:bold;color:#2C3E50;font-size:14px;">📌 %s</div>'
                    '<div style="font-size:12px;color:#555;margin:4px 0 2px;">'
                    '👤 المكلّفون: <strong>%s</strong></div>'
                    '<div style="font-size:12px;color:#666;margin:2px 0 8px;">'
                    '📅 يبدأ: <strong>%s</strong> | 🏁 ينتهي (Deadline): <strong style="color:#E74C3C;">%s</strong> | '
                    'المرحلة: <strong>%s</strong> | الوقت: <strong>%s</strong></div>'
                    '<div style="font-size:12px;color:#714B67;font-weight:bold;">⏱️ سجل العمل (تايمشيت):</div>'
                    '<table style="width:100%%;border-collapse:collapse;font-size:12px;margin:3px 0;"><tbody>%s</tbody></table>'
                    '<div style="font-size:12px;color:#714B67;font-weight:bold;margin-top:6px;">📝 نوتات الموظف:</div>'
                    '<ul style="margin:3px 0;padding-right:18px;font-size:12px;">%s</ul>'
                    '<div style="font-size:12px;color:#714B67;font-weight:bold;margin-top:6px;">🔔 الأنشطة:</div>'
                    '<ul style="margin:3px 0;padding-right:18px;font-size:12px;">%s</ul></div>'
                    % (t.name, assignees, date_start, date_end, stage, self._fmt(hrs),
                       ts_html, notes_html, acts_html))

            projects_html += ('<div style="border:2px solid #714B67;border-radius:8px;padding:12px;margin-bottom:14px;background:#faf8fb;">'
                '<h4 style="margin:0 0 8px;color:#714B67;">🗂️ المشروع: %s</h4>%s%s%s</div>'
                % (pname, project_level_html, loose_html, tasks_html))

        if no_project:
            np = ''
            for t in no_project:
                np += '<li>📌 %s — وقت: %s</li>' % (t.name, self._fmt(hours_by_task.get(t.id, 0.0)))
                digest.append('⚠️ مهمة عامة خارج المشاريع: %s' % t.name)
            projects_html += ('<div style="border:2px dashed #999;border-radius:8px;padding:12px;margin-bottom:14px;">'
                '<h4 style="margin:0 0 8px;color:#666;">🗂️ مهام خاصة (بدون مشروع)</h4>'
                '<ul style="padding-right:18px;font-size:13px;">%s</ul></div>' % np)

        # ========== مجال القانون (x_reports) — يبقى كما هو لمن يعمل به ==========
        legal_html, legal_count = '', 0
        try:
            active_case_ids = set(env['mail.message'].sudo().search([
                ('model', '=', 'x_reports'),
                ('date', '>=', date_from_str),
                ('author_id', '=', partner_id),
            ]).mapped('res_id'))
            domain = ['|', ('x_studio_user_id', '=', uid), ('create_uid', '=', uid)]
            if active_case_ids:
                domain = ['&', '|', ('id', 'in', list(active_case_ids)), ('create_date', '>=', date_from_str)] + domain
            else:
                domain = ['&', ('create_date', '>=', date_from_str)] + domain
            cases = env['x_reports'].sudo().search(domain, order='write_date desc', limit=50)
            legal_count = len(cases)
            if cases:
                digest.append('\n--- قضايا/عقود قانونية (%d) ---' % legal_count)
                cases_html = ''
                html_field_names = env['ir.model.fields'].sudo().search_read(
                    [('model', '=', 'x_reports'), ('ttype', '=', 'html')], ['name']
                )
                html_field_names = [f['name'] for f in html_field_names]

                for c in cases:
                    try:
                        def _val(field):
                            try:
                                v = c[field]
                                if hasattr(v, 'name'): return v.name or ''
                                if hasattr(v, 'display_name'): return v.display_name or ''
                                return str(v) if v not in (False, None, 0, 0.0) else ''
                            except Exception: return ''

                        cname = _val('x_name') or 'بدون عنوان'
                        stage = _val('x_studio_stage_id')
                        ctype = _val('x_studio_type')
                        cval  = _val('x_studio_value') or _val('x_studio_contract_value') or '-'
                        cdate = _val('x_studio_date')
                        cend  = _val('x_studio_date_stop') or '-'
                        resp  = _val('x_studio_user_id') or 'غير محدد'

                        digest.append('=== قضية/عقد: %s ===' % cname)
                        digest.append('  النوع: %s | المرحلة: %s | تاريخ: %s | تاريخ الانتهاء: %s | المسؤول: %s' % (ctype or '-', stage or '-', cdate or '-', cend, resp))

                        all_text_parts = []
                        for fname in html_field_names:
                            try:
                                raw_val = c[fname]
                                if raw_val:
                                    txt = html2plaintext(str(raw_val)).strip()
                                    if txt and len(txt) > 15: all_text_parts.append(txt)
                            except Exception: continue
                        notes_raw = '\n---\n'.join(all_text_parts).strip()
                        notes_display = self._clip(notes_raw, 1200)
                        notes_block = ''
                        if notes_display:
                            notes_block = ('<div style="font-size:12px;color:#444;margin:6px 0;background:#fafafa;'
                                           'border-right:3px solid #b8860b;padding:6px 10px;border-radius:4px;">'
                                           '<strong>📝 تفاصيل/ملاحظات:</strong><br>'
                                           + notes_display.replace('\n', '<br>') + '</div>')
                            digest.append('   📝 تفاصيل القضية الأصلية:\n%s' % notes_raw)

                        all_msgs = env['mail.message'].sudo().search([
                            ('model', '=', 'x_reports'), ('res_id', '=', c.id),
                            ('message_type', 'in', ['comment', 'email', 'notification']),
                        ], order='date desc', limit=30)

                        chat_html = ''
                        for m in all_msgs:
                            try:
                                body_txt = html2plaintext(m.body or '').strip()
                                subj_txt = (m.subject or '').strip()
                                act_type_name = None
                                try:
                                    if m.mail_activity_type_id: act_type_name = m.mail_activity_type_id.name
                                except Exception: pass

                                if act_type_name:
                                    content = body_txt or subj_txt or '(تم الإنجاز)'
                                    label = '✅ أنجز نشاط'
                                    item_style = 'background:#d4edda;color:#155724;border-right:3px solid #28a745;'
                                elif m.message_type == 'email':
                                    content = ('الموضوع: %s' % subj_txt + (' | ' + body_txt if body_txt else '')) if subj_txt else (body_txt or '-')
                                    label = '📧 بريد إلكتروني'
                                    item_style = 'background:#cce5ff;color:#004085;border-right:3px solid #004085;'
                                elif m.message_type == 'notification':
                                    content = body_txt or subj_txt or ''
                                    label = '🔄 تغيير/تحديث'
                                    item_style = 'background:#fff3cd;color:#856404;border-right:3px solid #ffc107;'
                                else:
                                    content = body_txt or subj_txt or ''
                                    label = '💬 ملاحظة'
                                    item_style = 'background:#f8f9fa;color:#333;border-right:3px solid #6c757d;'

                                if not content: continue
                                msg_date = str(m.date)[:16]
                                chat_html += ('<li style="margin:5px 0;padding:6px 10px;%sborder-radius:4px;list-style:none;">'
                                              '<strong>%s</strong> <span style="font-size:10px;color:#999;">(%s)</span><br>'
                                              '<span style="font-size:12px;line-height:1.5;">%s</span></li>'
                                              % (item_style, label, msg_date, self._clip(content, 400).replace('\n', '<br>')))
                                digest.append('      [%s] (%s): %s' % (label, msg_date, self._clip(content, 300)))
                            except Exception: continue

                        if not chat_html:
                            chat_html = '<li style="color:#aaa;list-style:none;padding:6px;">لا يوجد رسائل في الشاتر</li>'

                        open_acts = c.activity_ids.sudo().filtered(lambda a: a.user_id.id == uid)
                        act_html = ''
                        for a in open_acts:
                            try:
                                summ  = a.summary or a.note and html2plaintext(a.note).strip()[:80] or '(بدون عنوان)'
                                ddl   = str(a.date_deadline) if a.date_deadline else '-'
                                over  = bool(a.date_deadline and str(a.date_deadline) < today_str)
                                if over:
                                    flags.append('خطوة متأخّرة على قضية "%s": %s' % (cname[:25], summ[:30]))
                                    act_html += ('<li style="margin:4px 0;padding:6px 10px;background:#fdecea;'
                                                 'border-right:3px solid #E74C3C;border-radius:4px;list-style:none;">'
                                                 '<strong>🚩 متأخّرة:</strong> %s <span style="font-size:10px;color:#922;">(موعدها: %s)</span></li>' % (summ, ddl))
                                else:
                                    act_html += ('<li style="margin:4px 0;padding:6px 10px;background:#e8f5e9;'
                                                 'border-right:3px solid #27AE60;border-radius:4px;list-style:none;">'
                                                 '<strong>🔔 قادمة:</strong> %s <span style="font-size:10px;color:#555;">(موعدها: %s)</span></li>' % (summ, ddl))
                            except Exception: continue

                        act_section = ''
                        if act_html:
                            act_section = ('<div style="font-size:12px;color:#714B67;font-weight:bold;margin-top:10px;">📋 أنشطة مجدولة:</div>'
                                           '<ul style="margin:4px 0;padding:0;">%s</ul>' % act_html)

                        cases_html += (
                            '<div style="border:1px solid #e3c97a;border-radius:8px;padding:12px;margin:10px 0;background:#fffdf5;">'
                            '<div style="font-weight:bold;color:#8a6d1a;font-size:15px;border-bottom:1px solid #f0d080;'
                            'padding-bottom:6px;margin-bottom:8px;">⚖️ %s</div>'
                            '<div style="font-size:12px;color:#666;margin-bottom:8px;">'
                            '📌 النوع: <strong>%s</strong> | المرحلة: <strong>%s</strong> | '
                            'القيمة: <strong>%s</strong> | التاريخ: <strong>%s</strong></div>'
                            '%s'
                            '<div style="font-size:12px;color:#714B67;font-weight:bold;margin-top:10px;">🗒️ سجل النشاط والتواصل:</div>'
                            '<ul style="margin:4px 0;padding:0;">%s</ul>'
                            '%s</div>'
                            % (cname, ctype, stage, cval, cdate, notes_block, chat_html, act_section))
                    except Exception: continue

                legal_html = ('<div style="border:2px solid #b8860b;border-radius:8px;padding:12px;margin-bottom:14px;background:#fffbea;">'
                    '<h4 style="margin:0 0 8px;color:#b8860b;">⚖️ القضايا/العقود (تطبيق Law) — %d</h4>%s</div>'
                    % (legal_count, cases_html))
        except Exception:
            _logger.exception('KH_REPORT: legal section failed')

        # ========== معالجة النتيجة النهائية ==========
        has_data = bool(all_tasks or legal_count or total_hours > 0)
        flags = list(dict.fromkeys(flags))
        if flags:
            fl = ''.join('<li>%s</li>' % x for x in flags)
            flags_box = ('<div style="background:#fdecea;border:1px solid #E74C3C;border-radius:6px;padding:8px 12px;margin:8px 0;">'
                '<strong style="color:#E74C3C;">🚩 إشارات تلقائية للمدير:</strong>'
                '<ul style="margin:4px 0 0;padding-right:18px;color:#922;">%s</ul></div>' % fl)
        else:
            flags_box = '<div style="background:#d4edda;border-radius:6px;padding:8px 12px;margin:8px 0;color:#155724;">✅ جودة التوثيق جيدة ولا توجد إشارات مقلقة.</div>'

        kpis_parts = []
        if total_hours > 0 or all_tasks:
            kpis_parts.append('ساعات مسجلة: %s' % self._fmt(total_hours))
            kpis_parts.append('تاسكات نشطة: %d (مكتمل %d)' % (len(all_tasks), done_count))
        if legal_count:
            kpis_parts.append('ملفات قانونية: %d' % legal_count)
        kpis = ' | '.join(kpis_parts) if kpis_parts else 'لا يوجد نشاط رقمي'

        domains = []
        if all_tasks or total_hours > 0: domains.append('إدارة الهندسة والمشاريع')
        if legal_count: domains.append('الاستشارات والشؤون القانونية')
        domain_label = ' و '.join(domains) if domains else 'غير محدّد'

        digest_text = '\n'.join(digest) if digest else 'لا يوجد نشاط تفصيلي.'
        
        # استدعاء تحليل الذكاء الاصطناعي مع البيانات المحسّنة والنوتات
        ai_html = self._ai_analysis(user.name, days, kpis, domain_label, digest_text, flags)

        section = ('<div style="border-bottom:3px solid #714B67;margin-bottom:20px;padding-bottom:10px;">'
            '<h3 style="color:#714B67;">👤 الموظف: %s</h3>'
            '<p style="color:#666;font-size:13px;">🧭 طبيعة العمل: <strong>%s</strong> | %s</p>'
            '%s%s%s%s</div>'
            % (user.name, domain_label, kpis, ai_html, flags_box, projects_html, legal_html))
        return section, has_data

    # ============================================================
    # تحليل Gemini المعزز لقراءة النوتات ومعرفة تفاصيل كل مشروع
    # ============================================================
    def _ai_analysis(self, name, days, kpis, domain_label, digest_text, flags):
        box = '<div style="background:#f4ecf7;border:1px solid #714B67;border-radius:8px;padding:12px 16px;margin-bottom:12px;">'
        ttl = '<div style="font-weight:bold;color:#714B67;margin-bottom:6px;">🤖 تقرير الأداء الذكي المعتمد على التوثيق (AI)</div>'

        if not HAS_GENAI:
            return box + ttl + '<div style="color:#856404;">⚠️ مكتبة google-genai غير مثبّتة.</div></div>'
        ICP = self.env['ir.config_parameter'].sudo()
        key = ICP.get_param('gemini.api.key')
        model = ICP.get_param('gemini.model') or 'gemini-2.5-flash'
        if not key:
            return box + ttl + '<div style="color:#856404;">⚠️ مفتاح gemini.api.key غير موجود في سيستم Odoo.</div></div>'

        # الـ Prompt الجديد يركز على قراءة نوتات الموظف ومعرفة تفاصيل الشغل لكل مشروع
        prompt = (
            "أنت محلل أداء تنفيذي خبير في شركة هندسية وتجارية بالإمارات.\n"
            "مهمتك الأساسية هي قراءة سجل نشاط الموظف '%s' خلال آخر %d يوم المستخرج من Odoo وتوليد تقرير إداري دقيق.\n\n"
            "المطلوب منك التركيز بشكل كامل على نوتات الموظف (📝 نوت كتبها الموظف) والتايمشيت (⏱️ تايمشيت) المربوطة بكل مشروع وتاسك لمعرفة وتلخيص ما فعله بالتفصيل.\n\n"
            "طبيعة عمل الموظف الحالية: %s.\n"
            "ملخص المؤشرات الرقمية: %s.\n"
            "ملاحظات النظام التلقائية: %s.\n\n"
            "البيانات التفصيلية الخام المسحوبة من السيستم لقراءتها وتحليلها:\n"
            "--------------------------------------------------\n"
            "%s\n"
            "--------------------------------------------------\n\n"
            "قم بصياغة التقرير الإداري باللغة العربية بأسلوب احترافي جداً، واستخدم وسوم HTML بسيطة فقط للتنسيق (<p>, <strong>, <ul>, <li>, <h4>) بناءً على الهيكلية التالية:\n\n"
            "<h4>1. تفصيل العمل والإنجازات حسب المشاريع:</h4>\n"
            "قم بالمرور على كل مشروع موجود في البيانات بشكل مستقل، واذكر اسم المشروع، والتاسكات التابعة له، واشرح 'بالتفصيل وبناءً على النوتات المكتوبة من الموظف والتايمشيت' شو سوى الموظف في هذا المشروع بالضبط وما هي طبيعة الأعمال التي أنجزها. لا تدمج المشاريع.\n\n"
            "<h4>2. تحليل نوتات الموظف وجودة التحديث:</h4>\n"
            "حلل جودة النوتات والتعليقات التي يتركها الموظف على السيستم (هل هي واضحة وتفصيلية وتشرح سير العمل بشكل كافٍ للمدير، أم أنها مقتضبة؟) وقيم مستوى توثيقه لشغله (قوي / متوسط / ضعيف).\n\n"
            "<h4>3. الخطوات القادمة والأعمال المعلقة:</h4>\n"
            "بناءً على الأنشطة المجدولة أو طبيعة المشاريع المفتوحة، ما هي الخطوات القادمة المطلوبة من هذا الموظف في الأيام القادمة؟\n\n"
            "<h4>4. توصيات ونقاط عملية للمدير:</h4>\n"
            "اكتب من 3 إلى 5 نقاط أو توصيات ملموسة ومباشرة لمدير الشركة لتحسين إنتاجية هذا الموظف أو لمتابعة نقاط حرجة في مشاريع معينة بناءً على البيانات أعلاه.\n\n"
            "ملاحظة هامة وقاعدة ذهبية: اعتمد فقط وفقط على البيانات والنوتات المرفقة أمامك في النص. إذا كانت النوتات غنية، لخص تفاصيلها بذكاء دون إهمال لأسماء المشاريع والتفاصيل الفنية."
            % (name, days, domain_label, kpis, ', '.join(flags) if flags else 'لا يوجد', digest_text)
        )
        try:
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2)) # تقليل الـ temperature لزيادة دقة الالتزام بالبيانات ومنع التخيل
            text = (getattr(resp, 'text', '') or '').strip()
            if not text:
                for cand in (getattr(resp, 'candidates', None) or []):
                    content = getattr(cand, 'content', None)
                    parts = (getattr(content, 'parts', None) or []) if content else []
                    chunks = [getattr(p, 'text', '') for p in parts if getattr(p, 'text', '')]
                    if chunks:
                        text = '\n'.join(chunks).strip()
                        break
            if not text:
                text = '<p style="color:#999;">فشل النظام في استرجاع التحليل من الـ AI.</p>'
        except Exception as e:
            _logger.exception('KH_REPORT: Gemini connection failed')
            return box + ttl + '<div style="color:#922;">⚠️ فشل التحليل التلقائي: %s</div></div>' % str(e)[:200]
        return box + ttl + '<div style="font-size:13px;line-height:1.7;color:#333;">%s</div></div>' % text

    def _finalize(self, title, html):
        ICP = self.env['ir.config_parameter'].sudo()
        manager_uid = int(ICP.get_param('khales.report.manager_uid') or self.env.user.id)
        body = Markup(html)
        todo = self.env['project.task'].sudo().create({
            'name': title,
            'user_ids': [(6, 0, [manager_uid])],
            'project_id': False,
            'state': '01_in_progress',
            'description': body,
        })
        todo.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_comment')
        return todo.id