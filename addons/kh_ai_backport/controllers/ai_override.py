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

# --- [1] إصلاح مشكلة الـ Registry لضمان استقرار السيستم ---
class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'
    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text')
    ], string='Source Type', required=True, default='file')

class AiAgent(models.Model):
    _inherit = 'ai.agent'

    def _execute_query(self, query, history=None, attachment_ids=None, **kwargs):
        _logger.info("===== [PROD] GEMINI OVERRIDE TRIGGERED =====")
        # توجيه الاستعلام للكنترولر الموحد لضمان رد Gemini
        res = request.env['ai.controller.override'].generate_response(prompt=query, attachment_ids=attachment_ids)
        return res.get('answer') or res.get('response') or "No response from AI."

# --- [2] الكنترولر الاحترافي (دردشة + فواتير) ---
class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== KH_AI: ADVANCED HYBRID MODE (CHAT + AUDITOR) =====')
        
        # 🛡️ تعريف رد افتراضي لمنع الردود الفارغة (The 5-byte Fix)
        final_msg = "أهلاً بك، حصل خطأ بسيط في المعالجة. هل يمكنك تكرار السؤال؟"
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        try:
            # 1. جلب البيانات والمرفقات
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

            # 2. تجهيز Gemini بناءً على الحالة (دردشة أو فاتورة)
            if has_files:
                system_prompt = """You are a senior auditor for Khales Group. Analyze the document visually. 
                Identify if it's a Vendor Bill (Khales is receiver) or Customer Invoice (Khales is sender).
                Return ONLY JSON: {"action": "create_move", "move_type": "in_invoice", "partner_name": "X", "lines": []}"""
            else:
                system_prompt = "You are a helpful AI assistant for Khales Group. Answer naturally in the user's language."

            # 3. الاتصال بـ Gemini API
            from google import genai
            from google.genai import types
            api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
            
            if not api_key:
                final_msg = "Error: Gemini API Key is missing in System Parameters."
            else:
                client = genai.Client(api_key=api_key)
                contents = [f"{system_prompt}\n\nUser: {prompt}"]
                
                for att in attachments:
                    file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                    if file_bytes:
                        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

                response = client.models.generate_content(model="gemini-2.5-flash", contents=contents)
                final_msg = getattr(response, "text", str(response)).strip()

                # 4. منطق إنشاء الفواتير (فقط إذا وجد ملف ورد جيسون)
                if has_files and "{" in final_msg:
                    try:
                        clean_json = re.sub(r'```json|```', '', final_msg).strip()
                        data = json.loads(clean_json)
                        if data.get('action') == 'create_move':
                            env = request.env
                            m_type = data.get('move_type', 'in_invoice')
                            partner = env['res.partner'].sudo().search([('name', '=ilike', data.get('partner_name'))], limit=1)
                            if not partner:
                                partner = env['res.partner'].sudo().create({'name': data.get('partner_name')})
                            
                            acc_type = 'expense' if m_type == 'in_invoice' else 'income'
                            account = env['account.account'].sudo().search([('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)
                            
                            inv_lines = []
                            for l in data.get('lines', []):
                                inv_lines.append((0, 0, {'name': l.get('desc'), 'quantity': float(l.get('qty', 1)), 'price_unit': float(l.get('price', 0)), 'account_id': account.id}))
                            
                            new_move = env['account.move'].sudo().create({'move_type': m_type, 'partner_id': partner.id, 'invoice_line_ids': inv_lines})

                            # إرسال تنبيه رسمي (Sticky Notification)
                            env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {
                                'title': 'AI Success', 'message': f'Created {m_type} for {partner.name}', 'type': 'success', 'sticky': True,
                            })

                            return {
                                'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': new_move.id,
                                'views': [[False, 'form']], 'target': 'current',
                                'answer': f"✅ Created {m_type} for {partner.name}.", 'response': "Opening document..."
                            }
                    except: pass

        except Exception as e:
            _logger.exception("AI CRITICAL ERROR")
            final_msg = f"System Error: {str(e)}"

        # ✅ الرد النهائي المضمون الذي يمنع الـ 5-byte error
        return {
            'answer': final_msg,
            'response': final_msg,
            'status': 'success'
        }