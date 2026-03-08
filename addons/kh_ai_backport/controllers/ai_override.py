# -*- coding: utf-8 -*-
from odoo import models, fields, http, api
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

class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'
    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text')
    ], string='Source Type', required=True, default='file')

class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== KH_AI: STRICT INTENT ROUTING MODE =====')
        
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()
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

        # 🚀 البرومبت العسكري: يجبر الـ AI على تحديد النية أولاً
        system_prompt = """You are 'Khales AI', an expert ERP assistant.
        Determine the user's INTENT based on their message and attachments:
        1. 'create_invoice': User explicitly wants to create a bill/invoice, or uploaded a clear invoice document.
        2. 'chat': User is greeting, asking a question, or uploaded non-invoice files (like code, HTML, general images).

        You MUST ALWAYS reply in THIS EXACT JSON FORMAT ONLY:
        {
          "intent": "create_invoice" or "chat",
          "message": "Your conversational reply (e.g., Hello! / Here is the code explanation... / I am extracting the invoice now.)",
          "invoice_data": {
            "move_type": "in_invoice" or "out_invoice",
            "partner_name": "Name",
            "trn": "TRN",
            "vat_amount": 0.0,
            "lines": [{"desc": "Item", "qty": 1, "price": 10}]
          }
        }"""
        
        gemini_contents = [f"{system_prompt}\n\nUser Question: {prompt}"]
        for att in attachments:
            file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
            if file_bytes:
                gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

        if not HAS_GENAI: return {'answer': "Error: SDK Missing", 'response': "Error: SDK Missing"}
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=gemini_contents)
            result_text = getattr(response, "text", str(response)).strip()
            
            # تنظيف الـ JSON
            clean_json_str = re.sub(r'```json|```', '', result_text).strip()
            
            try:
                data = json.loads(clean_json_str)
                intent = data.get('intent', 'chat')
                chat_msg = data.get('message', 'تم معالجة الطلب.')

                # ⚙️ تنفيذ الفاتورة فقط إذا كانت النية واضحة ومؤكدة
                if intent == 'create_invoice' and data.get('invoice_data'):
                    inv_data = data['invoice_data']
                    move_type = inv_data.get('move_type')
                    
                    if move_type in ['in_invoice', 'out_invoice']:
                        env = request.env
                        p_name = inv_data.get('partner_name') or 'Unknown Partner'
                        partner = env['res.partner'].sudo().search([('name', '=ilike', p_name)], limit=1)
                        if not partner:
                            partner = env['res.partner'].sudo().create({'name': p_name, 'vat': inv_data.get('trn')})
                        
                        acc_type = 'expense' if move_type == 'in_invoice' else 'income'
                        account = env['account.account'].sudo().search([('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)

                        invoice_lines = []
                        for l in inv_data.get('lines', []):
                            invoice_lines.append((0, 0, {'name': l.get('desc', 'Item'), 'quantity': float(l.get('qty', 1.0)), 'price_unit': float(l.get('price', 0.0)), 'account_id': account.id if account else False}))
                        
                        if inv_data.get('vat_amount', 0) > 0:
                            invoice_lines.append((0, 0, {'name': 'VAT (Extracted)', 'quantity': 1.0, 'price_unit': float(inv_data.get('vat_amount')), 'account_id': account.id if account else False}))

                        new_move = env['account.move'].sudo().create({
                            'move_type': move_type,
                            'partner_id': partner.id,
                            'invoice_line_ids': invoice_lines,
                            'ref': f"AI-REF-{inv_data.get('trn', '')}"
                        })

                        friendly_name = "Vendor Bill" if move_type == 'in_invoice' else "Customer Invoice"
                        env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {
                            'title': 'Invoice Processed', 'message': f'Success! Created {friendly_name} for {partner.name}', 'type': 'success', 'sticky': True,
                        })

                        return {
                            'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': new_move.id,
                            'views': [[False, 'form']], 'target': 'current',
                            'answer': f"✅ {chat_msg}", 'response': f"✅ {chat_msg}"
                        }
                
                # 💬 إذا كانت النية مجرد دردشة (كود، سؤال عام، ترحيب)
                return {'answer': chat_msg, 'response': chat_msg}

            except json.JSONDecodeError:
                # 🛡️ شبكة أمان: إذا الـ AI عاند وما رجع JSON، بنعتبره دردشة عادية
                return {'answer': result_text, 'response': result_text}

        except Exception as e:
            _logger.exception("AI Error")
            return {'answer': f"System Error: {e}", 'response': f"System Error: {e}"}