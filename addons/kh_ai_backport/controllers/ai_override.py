# -*- coding: utf-8 -*-
from odoo import http, models, fields, api, _
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
import base64
import logging
import json
import re
import io

_logger = logging.getLogger(__name__)

# محاولة استيراد المكتبات لضمان استقرار السيرفر
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

# --- [1] إصلاح الـ AssertionError (حل مشكلة الـ Registry) ---
class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'

    # إعادة تعريف الحقل مع خياراته ليتجاوز أودو مرحلة التحقق بنجاح
    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text')
    ], string='Source Type', required=True, default='file')

class AiAgent(models.Model):
    _inherit = 'ai.agent'

    def _execute_query(self, query, history=None, attachment_ids=None, **kwargs):
        """ اعتراض الاستعلام لضمان استجابة Gemini في الواجهة الأمامية """
        _logger.info("===== [PROD] GEMINI OVERRIDE TRIGGERED =====")
        if not HAS_GENAI:
            return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)
        
        # استدعاء الكنترولر الموحد للحصول على الرد
        res = request.env['ai.controller.override'].generate_response(prompt=query, attachment_ids=attachment_ids)
        return res.get('answer') or res.get('response') or "No response generated."

# --- [2] الكنترولر الاحترافي: دردشة طبيعية + معالج فواتير ذكي ---
class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== KH_AI: HYBRID CHAT & AUDITOR MODE =====')
        
        # تعريف رد افتراضي لمنع الردود الفارغة (The 5-byte fix)
        final_msg = "أهلاً بك، حصل خطأ في المعالجة. هل يمكنك المحاولة مرة أخرى؟"
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        try:
            # 1. تجميع البيانات والمرفقات
            mail_message_id = kwargs.get('mail_message_id')
            if mail_message_id:
                message = request.env['mail.message'].sudo().browse(int(mail_message_id))
                if message.exists():
                    prompt = html2plaintext(message.body) if message.body else ""
                    attachments = message.attachment_ids
            else:
                raw_prompt = kwargs.get('prompt') or kwargs.get('question') or kwargs.get('text') or ''
                prompt = html2plaintext(raw_prompt) if '<' in raw_prompt else raw_prompt
                att_ids = kwargs.get('attachments') or kwargs.get('attachment_ids') or []
                if att_ids:
                    attachments = request.env['ir.attachment'].sudo().browse([int(i) for i in att_ids if str(i).isdigit()])

            has_files = len(attachments) > 0

            # 2. تحديد البرومبت (محاسب دقيق للفواتير / زميل ودود للدردشة)
            if has_files:
                system_prompt = """You are a senior auditor for Khales Group. Analyze the document visually. 
                Identify if it's a Vendor Bill (in_invoice) or Customer Invoice (out_invoice).
                Return ONLY JSON: {"action": "create_move", "move_type": "in_invoice", "partner_name": "X", "lines": []}"""
            else:
                system_prompt = "You are a helpful AI assistant for Nezar at Khales Group. Chat naturally and friendly."

            # 3. الاتصال بـ Gemini API
            api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
            if not api_key: return {'answer': "API Key Missing", 'response': "API Key Missing"}

            client = genai.Client(api_key=api_key)
            contents = [f"{system_prompt}\n\nUser: {prompt}"]
            for att in attachments:
                file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if file_bytes: contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

            response = client.models.generate_content(model="gemini-2.5-flash", contents=contents)
            final_msg = getattr(response, "text", str(response)).strip()

            # 4. معالجة الـ JSON لإنشاء الفواتير
            if has_files and "{" in final_msg:
                try:
                    clean_json = re.sub(r'```json|```', '', final_msg).strip()
                    data = json.loads(clean_json)
                    if data.get('action') == 'create_move':
                        env = request.env
                        m_type = data.get('move_type', 'in_invoice')
                        partner = env['res.partner'].sudo().search([('name', '=ilike', data.get('partner_name'))], limit=1)
                        if not partner: partner = env['res.partner'].sudo().create({'name': data.get('partner_name')})
                        
                        acc_type = 'expense' if m_type == 'in_invoice' else 'income'
                        account = env['account.account'].sudo().search([('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)
                        
                        inv_lines = [(0, 0, {'name': l.get('desc'), 'quantity': float(l.get('qty', 1)), 'price_unit': float(l.get('price', 0)), 'account_id': account.id}) for l in data.get('lines', [])]
                        new_move = env['account.move'].sudo().create({'move_type': m_type, 'partner_id': partner.id, 'invoice_line_ids': inv_lines})

                        # إرسال تنبيه أخضر (Notification)
                        env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {
                            'title': 'AI Success', 'message': f'Created {m_type} for {partner.name}', 'type': 'success', 'sticky': True,
                        })

                        return {
                            'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': new_move.id,
                            'views': [[False, 'form']], 'target': 'current',
                            'answer': f"✅ تم إنشاء المستند بنجاح.", 'response': "جاري التحويل..."
                        }
                except: pass

            return {'answer': final_msg, 'response': final_msg, 'status': 'success'}

        except Exception as e:
            _logger.exception("AI Error")
            return {'answer': f"Error: {e}", 'response': f"System Error: {e}"}