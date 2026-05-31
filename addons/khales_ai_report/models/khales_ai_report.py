# -*- coding: utf-8 -*-
import json
import re
import datetime
import logging

import requests

from odoo import models, api

_logger = logging.getLogger(__name__)

TZ_OFFSET_HOURS = 4
FLAG = 'color:#E74C3C;font-weight:bold;'


class KhalesAiReport(models.AbstractModel):
    _name = 'khales.ai.report'
    _description = 'Khales AI Employee Documentation Report'

    # ---------- أدوات مساعدة ----------
    @staticmethod
    def _fmt_hours(h):
        h = h or 0.0
        hh = int(h)
        mm = int(round((h - hh) * 60))
        return '%d:%02d' % (hh, mm)

    @staticmethod
    def _strip_html(body):
        if not body:
            return ''
        txt = re.sub(r'<[^>]+>', ' ', body)
        txt = txt.replace('&nbsp;', ' ').replace('&amp;', '&')
        return ' '.join(txt.split()).strip()

    # ============================================================
    # نقطة الدخول: env['khales.ai.report'].generate_for_user(2)
    # ============================================================
    def generate_for_user(self, user_id, days=30):
        user = self.env['res.users'].browse(user_id)
        if not user.exists():
            return False

        now_local = datetime.datetime.now() + datetime.timedelta(hours=TZ_OFFSET_HOURS)
        date_to = now_local.date()
        date_from = date_to - datetime.timedelta(days=days)
        date_limit = (datetime.datetime.combine(date_from, datetime.time.min)
                      - datetime.timedelta(hours=TZ_OFFSET_HOURS))
        date_limit_str = date_limit.strftime('%Y-%m-%d %H:%M:%S')
        today_str = date_to.strftime('%Y-%m-%d')
        partner_id = user.partner_id.id

        flags = []

        # ---------- 1) التايمشيت ----------
        ts_lines = self.env['account.analytic.line'].search([
            ('user_id', '=', user_id),
            ('project_id', '!=', False),
            ('date', '>=', date_from),
        ], order='date desc')

        lines_by_task, hours_by_task = {}, {}
        project_names, project_loose = {}, {}
        total_hours, ts_no_desc = 0.0, 0
        for ln in ts_lines:
            pid = ln.project_id.id
            project_names[pid] = ln.project_id.name
            h = ln.unit_amount or 0.0
            total_hours += h
            desc = (ln.name or '').strip()
            if not desc or desc == '/':
                ts_no_desc += 1
            if ln.task_id:
                lines_by_task.setdefault(ln.task_id.id, []).append(ln)
                hours_by_task[ln.task_id.id] = hours_by_task.get(ln.task_id.id, 0.0) + h
            else:
                project_loose[pid] = project_loose.get(pid, 0.0) + h
        if ts_no_desc:
            flags.append('في %d سطر تايمشيت بدون وصف.' % ts_no_desc)

        # ---------- 2) التاسكات مجمّعة بالمشاريع ----------
        user_tasks = self.env['project.task'].search([
            ('user_ids', 'in', [user_id]),
            ('write_date', '>=', date_limit_str),
        ])
        task_ids = set(user_tasks.ids) | set(lines_by_task.keys())
        all_tasks = self.env['project.task'].browse(list(task_ids)).exists()

        tasks_by_project, no_project_tasks = {}, []
        for t in all_tasks:
            if t.project_id:
                project_names[t.project_id.id] = t.project_id.name
                tasks_by_project.setdefault(t.project_id.id, []).append(t)
            else:
                no_project_tasks.append(t)

        # ---------- 3) بناء بنية بيانات موحّدة (للـ HTML وللـ AI) ----------
        projects = []
        all_pids = sorted(tasks_by_project.keys(), key=lambda p: project_names.get(p, ''))
        for p in project_loose:
            if p not in all_pids:
                all_pids.append(p)

        for pid in all_pids:
            pdata = {'name': project_names.get(pid, 'مشروع'),
                     'loose': project_loose.get(pid, 0.0), 'tasks': []}
            for t in tasks_by_project.get(pid, []):
                stage = t.stage_id.name if t.stage_id else (t.state or '-')
                hrs = hours_by_task.get(t.id, 0.0)
                att = self.env['ir.attachment'].search_count([
                    ('res_model', '=', 'project.task'), ('res_id', '=', t.id)])
                has_desc = bool((t.description or '').strip())
                evidence = []
                if att:
                    evidence.append('%d مرفق' % att)
                if has_desc:
                    evidence.append('وصف')
                is_done = (t.state == '1_done') or (t.stage_id and 'done' in (t.stage_id.name or '').lower())
                if is_done and not evidence:
                    flags.append('التاسك "%s" Done بدون دليل.' % t.name[:35])
                if is_done and hrs == 0:
                    flags.append('التاسك "%s" Done بدون وقت مسجّل.' % t.name[:35])

                ts = [(str(ln.date), (ln.name or '').strip() or '⚠️ بدون وصف', ln.unit_amount or 0.0)
                      for ln in lines_by_task.get(t.id, [])]

                msgs = self.env['mail.message'].search([
                    ('model', '=', 'project.task'), ('res_id', '=', t.id),
                    ('author_id', '=', partner_id), ('message_type', '=', 'comment'),
                ], order='date desc', limit=10)
                notes = []
                for m in msgs:
                    txt = self._strip_html(m.body)
                    if txt:
                        notes.append((str(m.date), txt[:250]))

                acts_rs = self.env['mail.activity'].search([
                    ('res_model', '=', 'project.task'), ('res_id', '=', t.id),
                    ('user_id', '=', user_id)])
                acts = []
                for a in acts_rs:
                    over = bool(a.date_deadline and str(a.date_deadline) < today_str)
                    if over:
                        flags.append('أكتفيتي متأخّرة على "%s".' % t.name[:30])
                    summ = a.summary or (a.activity_type_id.name if a.activity_type_id else 'بدون عنوان')
                    acts.append(('متأخّرة' if over else 'بوقتها', summ, str(a.date_deadline or '-')))

                pdata['tasks'].append({
                    'name': t.name, 'stage': stage, 'deadline': str(t.date_deadline or '-'),
                    'hours': hrs, 'evidence': ' + '.join(evidence) if evidence else '⚠️ لا دليل',
                    'done': is_done, 'timesheets': ts, 'notes': notes, 'activities': acts,
                })
            if pdata['tasks'] or pdata['loose'] > 0:
                projects.append(pdata)

        # ---------- 4) استدعاء الـ AI ----------
        ai_html = self._call_ai(user.name, total_hours, projects, flags)

        # ---------- 5) بناء HTML ----------
        report_body = self._render_html(user, date_from, date_to, total_hours,
                                        projects, no_project_tasks, hours_by_task,
                                        flags, ai_html)

        # تحويل لـ Markup عبر حقل Html
        self.env.user.partner_id.write({'comment': report_body})
        html_body = self.env.user.partner_id.comment
        self.env.user.partner_id.write({'comment': False})

        todo = self.env['project.task'].create({
            'name': '🤖 توثيق %s (AI) - %s' % (user.name, date_to),
            'user_ids': [(6, 0, [self.env.user.id])],
            'project_id': False,
            'state': '01_in_progress',
            'description': html_body,
        })
        todo.message_post(body=html_body, message_type='comment',
                          subtype_xmlid='mail.mt_comment')
        return todo.id

    # ============================================================
    # استدعاء Claude
    # ============================================================
    def _call_ai(self, name, total_hours, projects, flags):
        ICP = self.env['ir.config_parameter'].sudo()
        key = ICP.get_param('anthropic.api_key')
        model = ICP.get_param('anthropic.model') or 'claude-sonnet-4-6'

        if not key:
            return ('<div style="background:#fff3cd;padding:10px;border-radius:6px;color:#856404;">'
                    '⚠️ ما في مفتاح Anthropic. حطّه بـ Settings ← Technical ← System Parameters '
                    'باسم <code>anthropic.api_key</code>.</div>')

        # تجهيز نص البيانات للـ AI
        lines = ['الموظف: %s' % name, 'إجمالي الساعات: %s' % self._fmt_hours(total_hours)]
        for p in projects:
            lines.append('\nمشروع: %s (وقت عام بدون تاسك: %s)' % (p['name'], self._fmt_hours(p['loose'])))
            for t in p['tasks']:
                lines.append('  تاسك: %s | مرحلة: %s | ساعات: %s | دليل: %s'
                             % (t['name'], t['stage'], self._fmt_hours(t['hours']), t['evidence']))
                for d, desc, h in t['timesheets']:
                    lines.append('    - تايمشيت %s: %s (%sس)' % (d, desc, round(h, 2)))
                for d, txt in t['notes']:
                    lines.append('    - نوت: %s' % txt)
                for tag, summ, dl in t['activities']:
                    lines.append('    - أكتفيتي [%s]: %s (موعد %s)' % (tag, summ, dl))
        data_text = '\n'.join(lines)

        prompt = (
            'أنت محلل أداء. إلك بيانات فترة من شغل موظف على نظام Odoo '
            '(تاسكات، ساعات تايمشيت مع وصفها، نوتات، أكتفيتيز). '
            'مهمتك تعطي المدير قراءة ذكية، مش مجرد أرقام.\n\n'
            'البيانات:\n%s\n\n'
            'رجّعلي بالعربي وبصيغة HTML بسيطة (استخدم <p> و <strong> و <ul><li> فقط، '
            'بدون <html> أو <body>):\n'
            '1. <strong>ملخّص الشغل:</strong> 2-3 جمل عن شو اشتغل عليه فعلياً.\n'
            '2. <strong>جودة التوثيق:</strong> قيّمها (قوية/متوسطة/ضعيفة) مع سبب مختصر '
            '(تايمشيت بدون أوصاف، تاسكات Done بدون دليل، نوتات فاضية... إلخ).\n'
            '3. <strong>نقاط للمدير:</strong> 2-4 أسئلة أو ملاحظات يلزم ينتبهلها.\n'
            'كن صريح ومباشر، ولا تخترع معلومات مش موجودة بالبيانات.'
        ) % data_text

        try:
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                },
                data=json.dumps({
                    'model': model,
                    'max_tokens': 1500,
                    'messages': [{'role': 'user', 'content': prompt}],
                }),
                timeout=60,
            )
            jr = resp.json()
            if resp.status_code != 200:
                raise Exception(jr.get('error', {}).get('message', str(jr))[:300])
            ai_text = ''.join([b.get('text', '') for b in jr.get('content', [])
                               if b.get('type') == 'text']).strip()
            if not ai_text:
                ai_text = 'ما رجع تحليل من الـ AI.'
        except Exception as e:
            _logger.exception('Anthropic call failed')
            return ('<div style="background:#fdecea;padding:10px;border-radius:6px;color:#922;">'
                    '⚠️ فشل استدعاء الـ AI: %s</div>' % str(e)[:200])

        return ('<div style="background:#f4ecf7;border:1px solid #714B67;border-radius:8px;'
                'padding:12px 16px;margin-bottom:14px;">'
                '<div style="font-weight:bold;color:#714B67;margin-bottom:6px;">🤖 تحليل الـ AI</div>'
                '<div style="font-size:13px;color:#333;line-height:1.6;">%s</div></div>' % ai_text)

    # ============================================================
    # بناء الـ HTML الهرمي
    # ============================================================
    def _render_html(self, user, date_from, date_to, total_hours,
                     projects, no_project_tasks, hours_by_task, flags, ai_html):
        TC = 'padding:6px;border:1px solid #e3e3e3;text-align:center;'
        TD = 'padding:6px;border:1px solid #e3e3e3;text-align:right;'

        projects_html = ''
        for p in projects:
            loose_html = ''
            if p['loose'] > 0:
                loose_html = ('<div style="font-size:12px;color:#856404;background:#fff3cd;'
                              'padding:4px 8px;border-radius:4px;margin-bottom:8px;">'
                              '⏱️ وقت عام بدون تاسك: <strong>%s</strong></div>' % self._fmt_hours(p['loose']))
            tasks_html = ''
            for t in p['tasks']:
                ev_style = FLAG if (t['done'] and 'لا دليل' in t['evidence']) else ''
                ts_html = ''
                for d, desc, h in t['timesheets']:
                    ts_html += ('<tr><td style="%s width:90px;">%s</td>'
                                '<td style="%s">%s</td>'
                                '<td style="%s width:60px;">%s</td></tr>'
                                % (TC, d, TD, desc, TC, self._fmt_hours(h)))
                if not ts_html:
                    ts_html = '<tr><td colspan="3" style="%s color:#999;">لا يوجد تايمشيت</td></tr>' % TC

                notes_html = ''.join(['<li style="margin:2px 0;color:#444;">'
                                      '<span style="color:#999;font-size:10px;">%s</span> — %s</li>'
                                      % (d, txt) for d, txt in t['notes']])
                if not notes_html:
                    notes_html = '<li style="color:#bbb;">لا يوجد نوتات</li>'

                acts_html = ''
                for tag, summ, dl in t['activities']:
                    clr = FLAG if tag == 'متأخّرة' else 'color:#27AE60;'
                    acts_html += ('<li style="margin:2px 0;"><span style="%s">[%s]</span> %s '
                                  '<span style="color:#999;font-size:10px;">(%s)</span></li>'
                                  % (clr, tag, summ, dl))
                if not acts_html:
                    acts_html = '<li style="color:#bbb;">لا يوجد أكتفيتيز</li>'

                tasks_html += (
                    '<div style="border:1px solid #ddd;border-radius:6px;padding:10px;margin:8px 0;background:#fff;">'
                    '<div style="font-weight:bold;color:#2C3E50;font-size:14px;">📌 %s</div>'
                    '<div style="font-size:12px;color:#666;margin:4px 0 8px;">'
                    'المرحلة: <strong>%s</strong> | الموعد: %s | الوقت: <strong>%s</strong> | '
                    'الدليل: <span style="%s">%s</span></div>'
                    '<div style="font-size:12px;color:#714B67;font-weight:bold;">⏱️ التايمشيت:</div>'
                    '<table style="width:100%%;border-collapse:collapse;font-size:12px;margin:3px 0;">'
                    '<tbody>%s</tbody></table>'
                    '<div style="font-size:12px;color:#714B67;font-weight:bold;margin-top:6px;">📝 النوتات:</div>'
                    '<ul style="margin:3px 0;padding-right:18px;font-size:12px;">%s</ul>'
                    '<div style="font-size:12px;color:#714B67;font-weight:bold;margin-top:6px;">🔔 الأكتفيتيز:</div>'
                    '<ul style="margin:3px 0;padding-right:18px;font-size:12px;">%s</ul>'
                    '</div>'
                    % (t['name'], t['stage'], t['deadline'], self._fmt_hours(t['hours']),
                       ev_style, t['evidence'], ts_html, notes_html, acts_html))

            projects_html += (
                '<div style="border:2px solid #714B67;border-radius:8px;padding:12px;'
                'margin-bottom:16px;background:#faf8fb;">'
                '<h4 style="margin:0 0 8px;color:#714B67;">🗂️ المشروع: %s</h4>%s%s</div>'
                % (p['name'], loose_html, tasks_html))

        if no_project_tasks:
            np = ''.join(['<li style="margin:3px 0;">📌 %s — وقت: %s</li>'
                          % (t.name, self._fmt_hours(hours_by_task.get(t.id, 0.0)))
                          for t in no_project_tasks])
            projects_html += ('<div style="border:2px dashed #999;border-radius:8px;padding:12px;'
                              'margin-bottom:16px;"><h4 style="margin:0 0 8px;color:#666;">'
                              '🗂️ مهام خاصة (بدون مشروع)</h4>'
                              '<ul style="margin:0;padding-right:18px;font-size:13px;">%s</ul></div>' % np)

        if flags:
            fl = ''.join(['<li style="margin:3px 0;">%s</li>' % x for x in flags])
            flags_box = ('<div style="background:#fdecea;border:1px solid #E74C3C;border-radius:6px;'
                         'padding:10px 14px;margin:12px 0;"><strong style="color:#E74C3C;">'
                         '🚩 إشارات تلقائية:</strong><ul style="margin:6px 0 0;padding-right:20px;'
                         'color:#922;">%s</ul></div>' % fl)
        else:
            flags_box = ('<div style="background:#d4edda;border-radius:6px;padding:10px 14px;'
                         'margin:12px 0;color:#155724;">✅ ما في إشارات مقلقة.</div>')

        return (
            '<div dir="rtl" style="font-family:sans-serif;padding:10px;">'
            '<h3 style="color:#714B67;border-bottom:2px solid #714B67;padding-bottom:6px;">'
            '🤖 توثيق %s (تحليل AI)</h3>'
            '<p style="color:#666;">الفترة: %s ← %s | إجمالي الساعات: <strong>%s</strong></p>'
            '%s%s%s</div>'
            % (user.name, date_from, date_to, self._fmt_hours(total_hours),
               ai_html, flags_box, projects_html))
