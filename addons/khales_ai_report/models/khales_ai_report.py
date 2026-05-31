# -*- coding: utf-8 -*-
# ============================================================
#  محتوى models/khales_ai_report.py  (نسخة app-aware)
#  لكل موظف: يجمع شغلو من حيث ما يشتغل فعلاً —
#   • مشاريع: تاسك ← تايمشيت/نوتات/أكتفيتيز
#   • قانوني (x_reports): قضية ← تحديثات/ملاحظات/أكتفيتيز
#  Gemini يحلّل المجال الموجود فقط (ما يتوقّع تايمشيت للمحامي)
#  يُستدعى من Server Action / Scheduled Action
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

    # ============================================================
    # نقاط الدخول
    #   env['khales.ai.report'].generate_for_user(2)
    #   env['khales.ai.report'].generate_all(30)
    # ============================================================
    def generate_for_user(self, user_id, days=30):
        user = self.env['res.users'].sudo().browse(user_id)
        if not user.exists():
            return False
        section, _ = self._build_user_section(user, days)
        wrapper = ('<div dir="rtl" style="font-family:sans-serif;padding:10px;">'
                   '<h2 style="color:#714B67;">📊 تقرير توثيق %s</h2>'
                   '<p style="color:#666;">آخر %d يوم</p>%s</div>'
                   % (user.name, days, section))
        return self._finalize('📊 تقرير توثيق %s - %s' % (user.name, datetime.date.today()), wrapper)

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
                   '<h2 style="color:#714B67;">📊 تقرير الموظفين الشهري</h2>'
                   '<p style="color:#666;">آخر %d يوم — %d موظف</p>%s</div>'
                   % (days, count, sections))
        return self._finalize('📊 تقرير الموظفين الشهري - %s (%d موظف)' % (datetime.date.today(), count), wrapper)

    # ============================================================
    # بناء قسم موظف واحد — app-aware
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

        # ========== مجال المشاريع (تاسك/تايمشيت) ==========
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

        done_count = 0
        projects_html = ''
        for pid in all_pids:
            pname = project_names.get(pid, 'مشروع')
            proj_tasks = tasks_by_project.get(pid, [])
            loose = project_loose.get(pid, 0.0)
            digest.append('مشروع: %s' % pname)

            loose_html = ''
            if loose > 0:
                loose_html = ('<div style="font-size:12px;color:#856404;background:#fff3cd;'
                    'padding:4px 8px;border-radius:4px;margin-bottom:8px;">⏱️ وقت عام بدون تاسك: <strong>%s</strong></div>'
                    % self._fmt(loose))
                digest.append('  وقت عام بدون تاسك: %.2f س' % loose)

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
                digest.append('  أكتفيتي على المشروع: %s (موعد %s)%s' % (summ, a.date_deadline or '-', ' [متأخرة]' if over else ''))
            if not pa_html:
                pa_html = '<li style="color:#bbb;">لا يوجد</li>'
            project_level_html = ('<div style="background:#eef2f7;border-radius:6px;padding:6px 10px;margin-bottom:8px;">'
                '<div style="font-size:12px;color:#2C3E50;font-weight:bold;">🔔 أكتفيتيز على المشروع نفسه:</div>'
                '<ul style="margin:3px 0;padding-right:18px;font-size:12px;">%s</ul></div>' % pa_html)

            tasks_html = ''
            for t in proj_tasks:
                stage = t.stage_id.name if t.stage_id else (t.state or '-')
                hrs = hours_by_task.get(t.id, 0.0)
                is_done = (t.state == '1_done') or (t.stage_id and 'done' in (t.stage_id.name or '').lower())
                if is_done:
                    done_count += 1
                att = env['ir.attachment'].sudo().search_count([
                    ('res_model', '=', 'project.task'), ('res_id', '=', t.id)])
                has_desc = bool((t.description or '').strip())
                evid = []
                if att:
                    evid.append('%d مرفق' % att)
                if has_desc:
                    evid.append('وصف')
                evid_s = ' + '.join(evid) if evid else '⚠️ لا دليل'
                if is_done and not evid:
                    flags.append('تاسك "%s" Done بدون دليل' % t.name[:35])
                if is_done and hrs == 0:
                    flags.append('تاسك "%s" Done بدون وقت' % t.name[:35])
                digest.append('  تاسك: %s | مرحلة: %s | ساعات: %.2f | دليل: %s' % (t.name, stage, hrs, evid_s))

                ts_html = ''
                for ln in lines_by_task.get(t.id, []):
                    dd = (ln.name or '').strip() or '⚠️ بدون وصف'
                    ts_html += '<tr><td style="%s">%s</td><td style="%s">%s</td><td style="%s">%s</td></tr>' % (
                        TC, ln.date, TD, dd, TC, self._fmt(ln.unit_amount or 0.0))
                    digest.append('      تايمشيت %s: %s (%.2fس)' % (ln.date, dd, ln.unit_amount or 0.0))
                if not ts_html:
                    ts_html = '<tr><td colspan="3" style="%s color:#999;">لا يوجد تايمشيت</td></tr>' % TC

                tnotes = env['mail.message'].sudo().search([
                    ('model', '=', 'project.task'), ('res_id', '=', t.id),
                    ('author_id', '=', partner_id), ('message_type', '=', 'comment')],
                    order='date desc', limit=8)
                notes_html = ''
                for m in tnotes:
                    txt = html2plaintext(m.body or '').strip()
                    if not txt:
                        continue
                    notes_html += '<li style="color:#444;">%s</li>' % self._clip(txt, 250)
                    digest.append('      نوت: %s' % self._clip(txt, 200))
                if not notes_html:
                    notes_html = '<li style="color:#bbb;">لا يوجد</li>'

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
                    digest.append('      أكتفيتي: %s (موعد %s)%s' % (summ, a.date_deadline or '-', ' [متأخرة]' if over else ''))
                if not acts_html:
                    acts_html = '<li style="color:#bbb;">لا يوجد</li>'

                tasks_html += ('<div style="border:1px solid #ddd;border-radius:6px;padding:10px;margin:8px 0;background:#fff;">'
                    '<div style="font-weight:bold;color:#2C3E50;font-size:14px;">📌 %s</div>'
                    '<div style="font-size:12px;color:#666;margin:4px 0 8px;">المرحلة: <strong>%s</strong> | '
                    'الموعد: %s | الوقت: <strong>%s</strong> | الدليل: <span style="%s">%s</span></div>'
                    '<div style="font-size:12px;color:#714B67;font-weight:bold;">⏱️ شو عمل (تايمشيت):</div>'
                    '<table style="width:100%%;border-collapse:collapse;font-size:12px;margin:3px 0;"><tbody>%s</tbody></table>'
                    '<div style="font-size:12px;color:#714B67;font-weight:bold;margin-top:6px;">📝 نوتات التاسك:</div>'
                    '<ul style="margin:3px 0;padding-right:18px;font-size:12px;">%s</ul>'
                    '<div style="font-size:12px;color:#714B67;font-weight:bold;margin-top:6px;">🔔 أكتفيتيز التاسك:</div>'
                    '<ul style="margin:3px 0;padding-right:18px;font-size:12px;">%s</ul></div>'
                    % (t.name, stage, t.date_deadline or '-', self._fmt(hrs),
                       FLAG if (is_done and not evid) else '', evid_s, ts_html, notes_html, acts_html))

            projects_html += ('<div style="border:2px solid #714B67;border-radius:8px;padding:12px;margin-bottom:14px;background:#faf8fb;">'
                '<h4 style="margin:0 0 8px;color:#714B67;">🗂️ المشروع: %s</h4>%s%s%s</div>'
                % (pname, project_level_html, loose_html, tasks_html))

        if no_project:
            np = ''
            for t in no_project:
                np += '<li>📌 %s — وقت: %s</li>' % (t.name, self._fmt(hours_by_task.get(t.id, 0.0)))
                digest.append('مهمة خاصة: %s' % t.name)
            projects_html += ('<div style="border:2px dashed #999;border-radius:8px;padding:12px;margin-bottom:14px;">'
                '<h4 style="margin:0 0 8px;color:#666;">🗂️ مهام خاصة (بدون مشروع)</h4>'
                '<ul style="padding-right:18px;font-size:13px;">%s</ul></div>' % np)

        # ========== مجال القانون (x_reports) ==========
        legal_html, legal_count = '', 0
        try:
            cases = env['x_reports'].sudo().search(
                ['|', ('x_studio_user_id', '=', uid), ('create_uid', '=', uid)],
                order='write_date desc', limit=50)
            legal_count = len(cases)
            if cases:
                digest.append('--- قضايا/عقود قانونية (%d) ---' % legal_count)
                cases_html = ''
                for c in cases:
                    try:
                        cname  = c.x_name or '-'
                        stage  = c.x_studio_stage_id.name if c.x_studio_stage_id else '-'
                        ctype  = getattr(c, 'x_studio_type', None) or '-'
                        cval   = getattr(c, 'x_studio_value', None) or getattr(c, 'x_studio_contract_value', None) or '-'
                        cdate  = getattr(c, 'x_studio_date', None) or '-'
                        cend   = getattr(c, 'x_studio_end_date', None) or '-'
                        resp   = c.x_studio_user_id.name if c.x_studio_user_id else 'غير محدد'

                        digest.append('\n=== قضية/عقد: %s ===' % cname)
                        digest.append('النوع: %s | المرحلة: %s | القيمة: %s | تاريخ البداية: %s | تاريخ الانتهاء: %s | المسؤول: %s'
                                      % (ctype, stage, cval, cdate, cend, resp))

                        # --- النوتز/التفاصيل ---
                        notes_raw = html2plaintext(getattr(c, 'x_studio_notes', '') or '').strip()
                        notes_display = self._clip(notes_raw, 800)
                        notes_block = ''
                        if notes_display:
                            notes_block = ('<div style="font-size:12px;color:#444;margin:6px 0;background:#fafafa;'
                                           'border-right:3px solid #b8860b;padding:6px 10px;border-radius:4px;">'
                                           '<strong>📝 تفاصيل/ملاحظات:</strong><br>'
                                           + notes_display.replace('\n', '<br>') + '</div>')
                            digest.append('   📝 تفاصيل القضية:\n%s' % notes_raw)

                        # --- الشاتر مصنّف ---
                        cmsgs = env['mail.message'].sudo().search([
                            ('model', '=', 'x_reports'), ('res_id', '=', c.id),
                            ('message_type', 'in', ['comment', 'email', 'notification'])],
                            order='date desc', limit=30)
                        chat_html = ''
                        digest.append('   📋 سجل النشاط والتواصل:')
                        for m in cmsgs:
                            try:
                                body_txt = html2plaintext(m.body or '').strip()
                                subj_txt = (m.subject or '').strip()
                                # getattr آمن لـ mail_activity_type_id
                                act_type_rec = getattr(m, 'mail_activity_type_id', False)
                                act_type_name = act_type_rec.name if act_type_rec else None

                                if act_type_name:
                                    feedback = body_txt or subj_txt or '(أُنجز بدون ملاحظات إضافية)'
                                    label = '✅ أنجز نشاط [%s]' % act_type_name
                                    content = feedback
                                    item_style = 'background:#d4edda;color:#155724;border-right:3px solid #28a745;'
                                elif m.message_type == 'email':
                                    subject_part = ('الموضوع: %s | ' % subj_txt) if subj_txt else ''
                                    label = '📧 بريد إلكتروني'
                                    content = subject_part + (body_txt or subj_txt or '(بدون محتوى)')
                                    item_style = 'background:#cce5ff;color:#004085;border-right:3px solid #004085;'
                                elif m.message_type == 'notification':
                                    label = '🔄 تغيير في النظام'
                                    content = body_txt or subj_txt or ''
                                    item_style = 'background:#fff3cd;color:#856404;border-right:3px solid #ffc107;'
                                else:
                                    label = '💬 ملاحظة/تعليق'
                                    content = body_txt or subj_txt or ''
                                    item_style = 'background:#f8f9fa;color:#333;border-right:3px solid #6c757d;'

                                if not content:
                                    continue

                                display = self._clip(content, 400)
                                msg_date = str(m.date)[:16]
                                chat_html += ('<li style="margin:5px 0;padding:6px 10px;%s border-radius:4px;list-style:none;">'
                                              '<strong>%s</strong> <span style="color:#999;font-size:10px;">(%s)</span><br>'
                                              '<span style="font-size:12px;line-height:1.5;">%s</span></li>'
                                              % (item_style, label, msg_date, display.replace('\n', '<br>')))
                                digest.append('      [%s] (%s):\n         %s' % (label, msg_date, self._clip(content, 500)))
                            except Exception:
                                _logger.exception('KH_REPORT: error processing message id=%s', m.id)
                                continue

                        if not chat_html:
                            chat_html = '<li style="color:#bbb;list-style:none;">لا يوجد تحديثات بالشاتر</li>'

                        # --- الأنشطة المنجزة (Done) ---
                        try:
                            cacts_done = env['mail.activity'].sudo().with_context(active_test=False).search([
                                ('res_model', '=', 'x_reports'), ('res_id', '=', c.id),
                                ('user_id', '=', uid), ('active', '=', False)])
                        except Exception:
                            cacts_done = []
                        done_html = ''
                        if cacts_done:
                            digest.append('   ✅ أنشطة أنجزها الموظف:')
                        for a in cacts_done:
                            try:
                                atype    = a.activity_type_id.name if a.activity_type_id else 'نشاط'
                                summ     = a.summary or '(بدون عنوان محدد)'
                                deadline = str(a.date_deadline) if a.date_deadline else '-'
                                done_html += ('<li style="margin:4px 0;padding:6px 10px;background:#d4edda;'
                                              'border-right:3px solid #28a745;border-radius:4px;list-style:none;">'
                                              '<strong>✅ منجز — [%s]:</strong> %s '
                                              '<span style="color:#999;font-size:10px;">(كان موعدها: %s)</span></li>'
                                              % (atype, summ, deadline))
                                digest.append('      ✅ أنجز [%s]: "%s" — كانت مجدولة بتاريخ %s' % (atype, summ, deadline))
                            except Exception:
                                continue

                        # --- الأنشطة المفتوحة ---
                        cacts = env['mail.activity'].sudo().search([
                            ('res_model', '=', 'x_reports'), ('res_id', '=', c.id), ('user_id', '=', uid)])
                        open_html = ''
                        if cacts:
                            digest.append('   🔔 أنشطة مجدولة قادمة:')
                        for a in cacts:
                            try:
                                atype    = a.activity_type_id.name if a.activity_type_id else 'نشاط'
                                summ     = a.summary or '(بدون عنوان)'
                                deadline = str(a.date_deadline) if a.date_deadline else '-'
                                over     = bool(a.date_deadline and str(a.date_deadline) < today_str)
                                if over:
                                    flags.append('خطوة متأخّرة على قضية "%s": %s' % (cname[:25], summ[:30]))
                                    open_html += ('<li style="margin:4px 0;padding:6px 10px;background:#fdecea;'
                                                  'border-right:3px solid #E74C3C;border-radius:4px;list-style:none;">'
                                                  '<strong>🚩 متأخّرة — [%s]:</strong> %s '
                                                  '<span style="color:#922;font-size:10px;">(كان الموعد: %s)</span></li>'
                                                  % (atype, summ, deadline))
                                    digest.append('      🚩 [%s]: "%s" — موعدها كان %s [متأخرة!]' % (atype, summ, deadline))
                                else:
                                    open_html += ('<li style="margin:4px 0;padding:6px 10px;background:#e8f5e9;'
                                                  'border-right:3px solid #27AE60;border-radius:4px;list-style:none;">'
                                                  '<strong>🔔 قادمة — [%s]:</strong> %s '
                                                  '<span style="color:#999;font-size:10px;">(الموعد: %s)</span></li>'
                                                  % (atype, summ, deadline))
                                    digest.append('      🔔 [%s]: "%s" — الموعد %s' % (atype, summ, deadline))
                            except Exception:
                                continue

                        act_section = ''
                        if done_html or open_html:
                            act_section = ('<div style="font-size:12px;color:#714B67;font-weight:bold;margin-top:10px;">📋 الأنشطة:</div>'
                                           '<ul style="margin:4px 0;padding:0;">%s%s</ul>'
                                           % (done_html, open_html))

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

                    except Exception:
                        _logger.exception('KH_REPORT: error processing case id=%s name=%s', c.id, getattr(c, 'x_name', '?'))
                        digest.append('   [خطأ في معالجة هذه القضية — تحقق من اللوغ]')
                        continue

                legal_html = ('<div style="border:2px solid #b8860b;border-radius:8px;padding:12px;margin-bottom:14px;background:#fffbea;">'
                    '<h4 style="margin:0 0 8px;color:#b8860b;">⚖️ القضايا/العقود (تطبيق Law) — %d</h4>%s</div>'
                    % (legal_count, cases_html))
        except Exception:
            _logger.exception('KH_REPORT: legal section failed for user %s', uid)

        # ========== هل في داتا؟ ==========
        has_data = bool(all_tasks or legal_count or total_hours > 0)

        # ========== الإشارات ==========
        flags = list(dict.fromkeys(flags))
        if flags:
            fl = ''.join('<li>%s</li>' % x for x in flags)
            flags_box = ('<div style="background:#fdecea;border:1px solid #E74C3C;border-radius:6px;padding:8px 12px;margin:8px 0;">'
                '<strong style="color:#E74C3C;">🚩 إشارات تلقائية:</strong>'
                '<ul style="margin:4px 0 0;padding-right:18px;color:#922;">%s</ul></div>' % fl)
        else:
            flags_box = '<div style="background:#d4edda;border-radius:6px;padding:8px 12px;margin:8px 0;color:#155724;">✅ ما في إشارات مقلقة.</div>'

        # ========== المؤشرات (حسب مجال شغلو) ==========
        kpis_parts = []
        if total_hours > 0 or all_tasks:
            kpis_parts.append('ساعات: %s' % self._fmt(total_hours))
            kpis_parts.append('تاسكات: %d (Done %d)' % (len(all_tasks), done_count))
        if legal_count:
            kpis_parts.append('قضايا/عقود: %d' % legal_count)
        kpis = ' | '.join(kpis_parts) if kpis_parts else 'لا يوجد نشاط مسجّل'

        # نحدّد مجال شغل الموظف عشان الـ AI يتأقلم
        domains = []
        if all_tasks or total_hours > 0:
            domains.append('مشاريع (تاسكات وتايمشيت)')
        if legal_count:
            domains.append('قضايا قانونية (تطبيق Law)')
        domain_label = ' و '.join(domains) if domains else 'غير محدّد'

        digest_text = '\n'.join(digest) if digest else 'لا يوجد نشاط.'
        ai_html = self._ai_analysis(user.name, days, kpis, domain_label, digest_text, flags)

        section = ('<div style="border-bottom:3px solid #714B67;margin-bottom:20px;padding-bottom:10px;">'
            '<h3 style="color:#714B67;">👤 %s</h3>'
            '<p style="color:#666;font-size:13px;">🧭 مجال الشغل: <strong>%s</strong> | %s</p>'
            '%s%s%s%s</div>'
            % (user.name, domain_label, kpis, ai_html, flags_box, projects_html, legal_html))
        return section, has_data

    # ============================================================
    # تحليل Gemini — app-aware
    # ============================================================
    def _ai_analysis(self, name, days, kpis, domain_label, digest_text, flags):
        box = '<div style="background:#f4ecf7;border:1px solid #714B67;border-radius:8px;padding:12px 16px;margin-bottom:12px;">'
        ttl = '<div style="font-weight:bold;color:#714B67;margin-bottom:6px;">🤖 تحليل الأداء (AI)</div>'

        if not HAS_GENAI:
            return box + ttl + '<div style="color:#856404;">⚠️ مكتبة google-genai غير مثبّتة.</div></div>'
        ICP = self.env['ir.config_parameter'].sudo()
        key = ICP.get_param('gemini.api.key')
        model = ICP.get_param('gemini.model') or 'gemini-2.5-flash'
        if not key:
            return box + ttl + '<div style="color:#856404;">⚠️ مفتاح gemini.api.key غير موجود.</div></div>'

        prompt = (
            "أنت محلل أداء موظفين في شركة هندسية وقانونية بالإمارات. "
            "هاد توثيق شغل الموظف '%s' خلال آخر %d يوم مسحوب من نظام Odoo.\n"
            "مجال شغل هذا الموظف: %s.\n"
            "قواعد التحليل:\n"
            "- حلّل فقط المجال الموجود في البيانات.\n"
            "- البيانات تشمل: تفاصيل كل قضية/عقد، سجل النشاط والتواصل المصنّف (✅ أنشطة منجزة، 📧 بريد، 💬 ملاحظات، 🔄 تغييرات)، "
            "والأنشطة المنجزة والمجدولة.\n"
            "- ✅ في السجل = نشاط أنجزه الموظف فعلاً (مثل: إرسال إيميل، حضور جلسة، تحضير وثيقة).\n"
            "- اذكر كل نشاط منجز بالاسم والتفاصيل — لا تجمّع ولا تختصر.\n\n"
            "مؤشرات: %s\n"
            "إشارات تلقائية: %s\n\n"
            "البيانات التفصيلية:\n%s\n\n"
            "اكتب تحليلاً تفصيلياً بالعربي بصيغة HTML بسيطة فقط (<p> <strong> <ul><li>):\n"
            "1. <strong>ملخّص الشغل لكل قضية/عقد على حدة:</strong> اذكر اسم القضية ثم شو اشتغل عليها تحديداً.\n"
            "2. <strong>الأنشطة المنجزة بالتفصيل:</strong> لكل نشاط منجز (✅): اذكر نوعه، موضوعه، وما تم إنجازه فعلاً بناءً على محتوى الشاتر والنوتز.\n"
            "3. <strong>الوضع الحالي والخطوات الجاية:</strong> وين واصل كل قضية وشو المطلوب بعدين.\n"
            "4. <strong>جودة التوثيق:</strong> قوية/متوسطة/ضعيفة مع السبب الواضح بناءً على البيانات الموجودة.\n"
            "5. <strong>نقاط للمدير:</strong> 3-5 نقاط عملية بناءً على ما شفته في البيانات.\n"
            "اعتمد فقط على البيانات الموجودة، لا تخترع أرقاماً أو وقائع، ولا تقول 'لا يوجد بيانات' إذا كانت البيانات موجودة أمامك."
            % (name, days, domain_label, kpis, ', '.join(flags) if flags else 'لا يوجد', digest_text)
        )
        try:
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(temperature=0.3))
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
                text = '<p style="color:#999;">ما رجع تحليل من الـ AI.</p>'
        except Exception as e:
            _logger.exception('KH_REPORT: Gemini failed')
            return box + ttl + '<div style="color:#922;">⚠️ فشل التحليل: %s</div></div>' % str(e)[:200]
        return box + ttl + '<div style="font-size:13px;line-height:1.7;color:#333;">%s</div></div>' % text

    # ============================================================
    # إنشاء To-Do بالتقرير
    # ============================================================
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