# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
import base64
import logging
import json
import re

_logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== KH_AI: DUAL MODE (INVOICES & BILLS) =====')
        
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        # 1. جلب بيانات الرسالة والمرفقات
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

        prompt_lower = prompt.lower()
        has_files = len(attachments) > 0

        # شرطي المرور للطلبات الداخلية
        if any(k in prompt_lower for k in ['موظف', 'مبيعات', 'how many']) and not has_files:
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # 2. إعداد Gemini Vision للتمييز بين الفاتورة والـ Bill
        system_prompt = """You are an expert ERP accountant. Analyze the document visually.
        1. Determine if it is a 'Customer Invoice' (we are selling) or a 'Vendor Bill' (we are buying/paying).
        2. Extract the Name (Client for Invoices, Vendor for Bills).
        3. Extract ALL line items (Description, Quantity, Unit Price).
        
        Reply ONLY with JSON:
        {
          "type": "out_invoice" OR "in_invoice",
          "name": "Full Name",
          "lines": [{"desc": "Item", "qty": 1, "price": 10}]
        }"""
        
        gemini_contents = [f"{system_prompt}\n\nUser Question: {prompt}"]
        for att in attachments:
            file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
            if file_bytes:
                gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

        if not HAS_GENAI: return {'response': "Error: Gemini SDK Missing"}
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=gemini_contents)
            result_text = getattr(response, "text", str(response)).strip()
            clean_json_str = re.sub(r'```json|```', '', result_text).strip()

            try:
                parsed_data = json.loads(clean_json_str)
                move_type = parsed_data.get('type') # 'out_invoice' or 'in_invoice'
                
                if move_type in ['out_invoice', 'in_invoice']:
                    env = request.env
                    # إنشاء/جلب الطرف الآخر (عميل أو مورد)
                    partner = env['res.partner'].sudo().search([('name', '=ilike', parsed_data.get('name'))], limit=1)
                    if not partner:
                        partner = env['res.partner'].sudo().create({'name': parsed_data.get('name')})
                    
                    # اختيار نوع الحساب بناءً على نوع الحركة
                    acc_type = 'income' if move_type == 'out_invoice' else 'expense'
                    account = env['account.account'].sudo().search([
                        ('account_type', '=', acc_type), 
                        ('company_ids', 'in', env.company.id)
                    ], limit=1)
                    
                    # بناء الأسطر
                    invoice_lines = []
                    for l in parsed_data.get('lines', []):
                        invoice_lines.append((0, 0, {
                            'name': l.get('desc', 'AI Extracted Line'),
                            'quantity': float(l.get('qty', 1.0)),
                            'price_unit': float(l.get('price', 0.0)),
                            'account_id': account.id if account else False
                        }))

                    # إنشاء السجل (Invoice or Bill)
                    new_move = env['account.move'].sudo().create({
                        'move_type': move_type,
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_lines
                    })

                    # إشعار النجاح وفتح الصفحة
                    return {
                        'type': 'ir.actions.act_window',
                        'res_model': 'account.move',
                        'res_id': new_move.id,
                        'views': [[False, 'form']],
                        'target': 'current',
                        'answer': f"Success! Created a {move_type.replace('_', ' ')} for {partner.name}.",
                        'response': "Opening the document now...",
                        'status': 'success'
                    }

            except Exception: pass

            return {'answer': result_text, 'response': result_text, 'status': 'success'}

        except Exception as e:
            _logger.exception("AI Error")
            return {'response': f"Error: {str(e)}"}