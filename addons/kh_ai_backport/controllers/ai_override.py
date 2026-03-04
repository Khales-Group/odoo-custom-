# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
import base64
import io
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
        _logger.info('===== SMART AI ROUTER: FINAL STABLE VERSION =====')
        
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        # 1. جلب الرسالة والمرفقات
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

        # 2. شرطي المرور (Router)
        db_keywords = ['موظف', 'موظفين', 'مبيعات', 'عملاء', 'عميل', 'how many', 'sales', 'invoice count']
        needs_database = any(keyword in prompt_lower for keyword in db_keywords)

        if needs_database and not has_files:
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # 3. إعداد Gemini Vision
        system_prompt = """You are an ERP expert. Analyze the documents. 
        If creating an invoice: Extract Client Name and ALL Table Lines (Description, Qty, Price).
        Reply ONLY with JSON format:
        {"action": "create_invoice", "customer_name": "Name", "invoice_lines": [{"desc": "Item", "qty": 1, "price": 10}]}
        """
        
        gemini_contents = [f"{system_prompt}\n\nUser Question: {prompt}"]
        for att in attachments:
            try:
                file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if file_bytes:
                    gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))
            except Exception as e:
                _logger.error(f"File Error: {e}")

        if not HAS_GENAI: return {'response': "Missing GenAI Library"}
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=gemini_contents)
            result_text = getattr(response, "text", str(response)).strip()
            
            clean_json_str = re.sub(r'```json|```', '', result_text).strip()
            final_msg = result_text

            try:
                parsed_data = json.loads(clean_json_str)
                if parsed_data.get('action') == 'create_invoice':
                    env = request.env
                    partner = env['res.partner'].sudo().search([('name', '=ilike', parsed_data.get('customer_name'))], limit=1)
                    if not partner:
                        partner = env['res.partner'].sudo().create({'name': parsed_data.get('customer_name')})
                    
                    income_account = env['account.account'].sudo().search([('account_type', '=', 'income'), ('company_ids', 'in', env.company.id)], limit=1)
                    
                    invoice_lines = []
                    for line in parsed_data.get('invoice_lines', []):
                        invoice_lines.append((0, 0, {
                            'name': line.get('desc', 'AI Line Item'),
                            'quantity': float(line.get('qty', 1.0)),
                            'price_unit': float(line.get('price', 0.0)),
                            'account_id': income_account.id if income_account else False
                        }))

                    new_inv = env['account.move'].sudo().create({
                        'move_type': 'out_invoice',
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_lines
                    })

                    # --- بناء اللينك الصاروخي (رابط كامل) ---
                    base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
                    inv_url = f"{base_url}/web#id={new_inv.id}&model=account.move&view_type=form"
                    
                    final_msg = f"✅ **Invoice #{new_inv.id} Created!**\n\nI have extracted all items from the document for **{partner.name}**.\n\n[👉 CLICK HERE TO OPEN INVOICE]({inv_url})"

            except Exception: pass # كمل كرسالة نصية لو مو JSON

            # 4. الرد النهائي للشات (المسار الآمن والمستقر)
            channel_id = kwargs.get('channel_id')
            if channel_id:
                channel = request.env['discuss.channel'].sudo().browse(int(channel_id))
                if channel.exists():
                    html_body = final_msg.replace('\n', '<br>')
                    channel.message_post(body=html_body, author_id=request.env.ref('base.partner_root').id, message_type='comment')

            return {'answer': final_msg, 'response': final_msg, 'status': 'success'}

        except Exception as e:
            _logger.exception("AI Error")
            return {'response': f"Error: {e}"}