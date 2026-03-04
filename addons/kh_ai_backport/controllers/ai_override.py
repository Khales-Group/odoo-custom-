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
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== SMART AI ROUTER: PHASE 2 (AUTONOMOUS DOCS) =====')
        
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

        prompt_lower = prompt.lower()
        has_files = len(attachments) > 0

        db_keywords = ['موظف', 'موظفين', 'مبيعات', 'عملاء', 'عميل', 'how many', 'sales']
        needs_database = any(keyword in prompt_lower for keyword in db_keywords)

        if needs_database and not has_files:
            return super(AIControllerOverride, self).generate_response(**kwargs)

        extracted_text = ""
        for att in attachments:
            try:
                if 'pdf' in (att.mimetype or ''):
                    file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                    extracted_text += "".join([page.extract_text() or '' for page in reader.pages])
                elif att.index_content:
                    extracted_text += att.index_content
            except Exception as e:
                _logger.warning(f"File extraction error: {e}")

        system_prompt = """You are an advanced ERP AI Assistant. 
        Read the provided file text. 
        IF the user asks to create an invoice, bill, or receipt based on this file:
        You MUST extract the 'Client/Customer Name' and the 'Total Amount'.
        Then, you MUST reply ONLY with a valid JSON format like this exactly (no markdown, no extra text):
        {"action": "create_invoice", "customer_name": "Extracted Name", "amount": 1234.50}
        
        IF the user asks a general question (not creating an invoice), just answer normally in text.
        """
        
        final_prompt = f"{system_prompt}\n\n--- FILE CONTEXT ---\n{extracted_text}\n-------------------\n\nUser Question: {prompt}" if extracted_text else f"User Question: {prompt}"

        if not HAS_GENAI: return {'response': "Gemini SDK missing."}
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=final_prompt)
            result_text = getattr(response, "text", str(response)).strip()
            
            clean_json_str = re.sub(r'```json|```', '', result_text).strip()
            
            try:
                parsed_data = json.loads(clean_json_str)
                
                if parsed_data.get('action') == 'create_invoice':
                    c_name = parsed_data.get('customer_name')
                    inv_amount = float(parsed_data.get('amount', 0.0))
                    
                    env = request.env
                    partner = env['res.partner'].sudo().search([('name', '=ilike', c_name)], limit=1)
                    if not partner:
                        partner = env['res.partner'].sudo().create({'name': c_name})
                        
                    # ==========================================
                    # 🛠️ التعديل هنا: استخدام company_ids بدل company_id
                    # ==========================================
                    income_account = env['account.account'].sudo().search([
                        ('account_type', '=', 'income'), 
                        ('company_ids', 'in', env.company.id)
                    ], limit=1)
                    
                    invoice_vals = {
                        'move_type': 'out_invoice',
                        'partner_id': partner.id,
                        'invoice_line_ids': [(0, 0, {
                            'name': 'Invoice automatically extracted from PDF via AI',
                            'quantity': 1.0,
                            'price_unit': inv_amount,
                            'account_id': income_account.id if income_account else False
                        })]
                    }
                    new_inv = env['account.move'].sudo().create(invoice_vals)
                    inv_url = f"/web#id={new_inv.id}&model=account.move&view_type=form"
                    
                    final_chat_message = f"✅ **Success!** I read the document, extracted the data, and automatically created the invoice for **{partner.name}** with amount **{inv_amount}**.\n\n[👉 CLICK HERE TO OPEN THE INVOICE]({inv_url})"
                
                else:
                    final_chat_message = result_text
                    
            except json.JSONDecodeError:
                final_chat_message = result_text

            channel_id = kwargs.get('channel_id')
            if channel_id:
                channel = request.env['discuss.channel'].sudo().browse(int(channel_id))
                if channel.exists():
                    html_body = final_chat_message.replace('\n', '<br>')
                    bot_id = request.env.ref('base.partner_root').id
                    channel.message_post(body=html_body, author_id=bot_id, message_type='comment', subtype_xmlid='mail.mt_comment')
                    
            return {'answer': final_chat_message, 'response': final_chat_message, 'status': 'success'}
            
        except Exception as e:
            _logger.exception("AI Bridge Error: %s", e)
            return {'response': f"System Error: {e}"}