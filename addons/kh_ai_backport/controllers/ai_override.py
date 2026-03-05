# -*- coding: utf-8 -*-
from odoo import http, models, fields
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
import base64
import logging
import json
import re

_logger = logging.getLogger(__name__)

# --- [1] إصلاح مشكلة الـ Registry اللي واجهتك سابقاً ---
class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'
    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text')
    ], string='Source Type', required=True, default='file')

# --- [2] الكنترولر المعدل ليدعم الدردشة والتحليل ---
class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== KH_AI: CONVERSATIONAL AUDITOR MODE =====')
        
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        # جلب البيانات والمرفقات
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

        # 🧠 التعديل الجوهري: تبديل البرومبت بناءً على الحالة
        if has_files:
            system_prompt = """You are a senior auditor for Khales Group.
            Analyze the document visually. 
            - Identify if it's a Vendor Bill (Khales is receiving) or Customer Invoice (Khales is sending).
            - Extract Partner Name, TRN, VAT Amount, and all Line Items.
            - If it's an invoice request, you MUST return ONLY a JSON object.
            JSON Format: {"action": "create_move", "move_type": "in_invoice", "partner_name": "X", "trn": "123", "vat": 5.0, "lines": [{"desc": "A", "qty": 1, "price": 10}]}
            """
        else:
            # برومبت الدردشة الطبيعية
            system_prompt = "You are a helpful and witty AI collaborator for Nezar at Khales Group. Just chat naturally in the user's language. Don't mention JSON."

        try:
            from google import genai
            from google.genai import types
            api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
            client = genai.Client(api_key=api_key)
            
            gemini_contents = [f"{system_prompt}\n\nUser: {prompt}"]
            for att in attachments:
                file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if file_bytes:
                    gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

            response = client.models.generate_content(model="gemini-2.5-flash", contents=gemini_contents)
            result_text = getattr(response, "text", str(response)).strip()

            # ⚙️ محاولة معالجة الـ JSON فقط إذا كان هناك ملفات
            if has_files and "{" in result_text:
                try:
                    clean_json = re.sub(r'```json|```', '', result_text).strip()
                    data = json.loads(clean_json)
                    if data.get('action') == 'create_move':
                        # ... [نفس منطق إنشاء الفاتورة/البيل اللي كتبناه سابقاً] ...
                        env = request.env
                        move_type = data.get('move_type', 'in_invoice')
                        partner = env['res.partner'].sudo().search([('name', '=ilike', data.get('partner_name'))], limit=1)
                        if not partner:
                            partner = env['res.partner'].sudo().create({'name': data.get('partner_name'), 'vat': data.get('trn')})
                        
                        acc_type = 'expense' if move_type == 'in_invoice' else 'income'
                        account = env['account.account'].sudo().search([('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)
                        
                        inv_lines = []
                        for l in data.get('lines', []):
                            inv_lines.append((0, 0, {'name': l.get('desc'), 'quantity': float(l.get('qty', 1)), 'price_unit': float(l.get('price', 0)), 'account_id': account.id}))
                        
                        # إضافة سطر الضريبة إذا وجد
                        if data.get('vat', 0) > 0:
                            inv_lines.append((0, 0, {'name': 'VAT (AI Extracted)', 'quantity': 1, 'price_unit': float(data.get('vat')), 'account_id': account.id}))

                        new_move = env['account.move'].sudo().create({'move_type': move_type, 'partner_id': partner.id, 'invoice_line_ids': inv_lines})
                        
                        return {
                            'type': 'ir.actions.act_window',
                            'res_model': 'account.move',
                            'res_id': new_move.id,
                            'views': [[False, 'form']],
                            'target': 'current',
                            'answer': f"✅ تم إنشاء {move_type} لـ {partner.name} بنجاح!",
                            'response': "جاري فتح المستند..."
                        }
                except: pass

            # الرد العادي (مرحبا، كيفك، الخ)
            return {'answer': result_text, 'response': result_text, 'status': 'success'}

        except Exception as e:
            _logger.exception("AI Error")
            return {'response': f"Error: {e}"}