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
        _logger.info('===== KH_AI: ADVANCED BILL/INVOICE ROUTER =====')
        
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        # 1. جلب البيانات (نفس منطقك السابق)
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

        # 2. برومبت ذكي جداً للتمييز (Bill vs Invoice)
        system_prompt = """You are an accountant for 'Khales Group'.
        Analyze the document carefully:
        - IF the document is FROM another company TO 'Khales' or 'Al Masar': It's a Vendor Bill (type: 'in_invoice').
        - IF the document is FROM 'Khales' TO a client: It's a Customer Invoice (type: 'out_invoice').
        - Extract the partner name (The other company).
        - Extract all items (Desc, Qty, Price).
        
        Return ONLY JSON: 
        {"type": "in_invoice" or "out_invoice", "partner_name": "Name", "lines": [{"desc": "X", "qty": 1, "price": 10}]}"""
        
        gemini_contents = [f"{system_prompt}\n\nUser Question: {prompt}"]
        for att in attachments:
            file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
            if file_bytes:
                gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

        if not HAS_GENAI: return {'response': "Missing SDK"}
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=gemini_contents)
            result_text = getattr(response, "text", str(response)).strip()
            clean_json_str = re.sub(r'```json|```', '', result_text).strip()

            try:
                parsed_data = json.loads(clean_json_str)
                move_type = parsed_data.get('type')
                
                if move_type in ['out_invoice', 'in_invoice']:
                    env = request.env
                    p_name = parsed_data.get('partner_name')
                    
                    partner = env['res.partner'].sudo().search([('name', '=ilike', p_name)], limit=1)
                    if not partner:
                        partner = env['res.partner'].sudo().create({'name': p_name})
                    
                    # اختيار الحساب الصحيح: 'income' للفاتورة و 'expense' للبيل
                    acc_type = 'income' if move_type == 'out_invoice' else 'expense'
                    account = env['account.account'].sudo().search([
                        ('account_type', '=', acc_type), 
                        ('company_ids', 'in', env.company.id)
                    ], limit=1)
                    
                    invoice_lines = []
                    for l in parsed_data.get('lines', []):
                        invoice_lines.append((0, 0, {
                            'name': l.get('desc', 'AI Line Item'),
                            'quantity': float(l.get('qty', 1.0)),
                            'price_unit': float(l.get('price', 0.0)),
                            'account_id': account.id if account else False
                        }))

                    new_move = env['account.move'].sudo().create({
                        'move_type': move_type,
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_lines
                    })

                    # بناء اللينك الصافي كاحتياط
                    base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
                    inv_url = f"{base_url.rstrip('/')}/web#id={new_move.id}&model=account.move&view_type=form"

                    # 🚀 إرسال التنبيه الرسمي (Bus Notification)
                    env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {
                        'title': 'AI Success',
                        'message': f'Created {move_type.replace("_", " ")} for {partner.name}',
                        'type': 'success',
                        'sticky': True,
                    })

                    # إرجاع الأكشن لفتح الفاتورة
                    return {
                        'type': 'ir.actions.act_window',
                        'res_model': 'account.move',
                        'res_id': new_move.id,
                        'views': [[False, 'form']],
                        'target': 'current',
                        'answer': f"✅ Created {move_type.replace('_', ' ')} #{new_move.id}.\nLink: {inv_url}",
                        'response': f"Opening {move_type.replace('_', ' ')}...",
                    }

            except Exception: pass

            return {'answer': result_text, 'response': result_text}

        except Exception as e:
            _logger.exception("AI Error")
            return {'response': f"Error: {e}"}