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
        _logger.info('===== SMART AI ROUTER: PHASE 2 (MULTI-LINE VISION) =====')
        
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

        # شرطي المرور: توجيه لأودو إذا كان استعلام قاعدة بيانات داخلي
        db_keywords = ['موظف', 'موظفين', 'مبيعات', 'عملاء', 'عميل', 'فواتير', 'how many', 'sales']
        needs_database = any(keyword in prompt_lower for keyword in db_keywords)

        if needs_database and not has_files:
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # 2. بناء الأوامر لـ Gemini Vision لاستخراج الأسطر بالتفصيل
        system_prompt = """You are an expert ERP accountant.
        Analyze the attached documents visually.
        If the user wants to create an invoice, extract:
        1. The exact Client/Customer Name.
        2. EVERY line item found in the table (Description, Quantity, Unit Price).
        
        You MUST reply ONLY with a JSON object (no markdown, no extra text):
        {
          "action": "create_invoice",
          "customer_name": "Full Name",
          "invoice_lines": [
            {"desc": "Item 1 Description", "qty": 1.0, "price": 100.0},
            {"desc": "Item 2 Description", "qty": 2.0, "price": 50.0}
          ]
        }
        
        If it's just a general question, reply with normal text.
        """
        
        gemini_contents = [f"{system_prompt}\n\nUser Question: {prompt}"]

        # إضافة الملفات الخام (PDF/Images) للرؤية البصرية
        for att in attachments:
            try:
                file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if file_bytes:
                    gemini_contents.append(
                        types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf')
                    )
            except Exception as e:
                _logger.warning(f"Attachment processing failed: {e}")

        if not HAS_GENAI: return {'response': "Gemini SDK missing."}
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=gemini_contents)
            result_text = getattr(response, "text", str(response)).strip()
            
            # 3. معالجة النتائج وزراعتها في أودو
            clean_json_str = re.sub(r'```json|```', '', result_text).strip()
            
            try:
                parsed_data = json.loads(clean_json_str)
                if parsed_data.get('action') == 'create_invoice':
                    c_name = parsed_data.get('customer_name')
                    lines = parsed_data.get('invoice_lines', [])
                    
                    env = request.env
                    partner = env['res.partner'].sudo().search([('name', '=ilike', c_name)], limit=1)
                    if not partner:
                        partner = env['res.partner'].sudo().create({'name': c_name})
                    
                    # البحث عن حساب الإيرادات المناسب للشركة
                    income_account = env['account.account'].sudo().search([
                        ('account_type', '=', 'income'), 
                        ('company_ids', 'in', env.company.id)
                    ], limit=1)

                    # بناء قائمة أسطر الفاتورة بالتفصيل
                    invoice_line_ids = []
                    for line in lines:
                        invoice_line_ids.append((0, 0, {
                            'name': line.get('desc', 'Service'),
                            'quantity': float(line.get('qty', 1.0)),
                            'price_unit': float(line.get('price', 0.0)),
                            'account_id': income_account.id if income_account else False
                        }))

                    # إنشاء الفاتورة النهائية
                    new_inv = env['account.move'].sudo().create({
                        'move_type': 'out_invoice',
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_line_ids
                    })
                    
                    inv_url = f"/web#id={new_inv.id}&model=account.move&view_type=form"
                    final_msg = f"✅ **Success!** I read the document and extracted {len(lines)} line items for **{partner.name}**.\n\n[👉 CLICK HERE TO OPEN THE INVOICE]({inv_url})"
                else:
                    final_msg = result_text
                    
            except (json.JSONDecodeError, ValueError):
                final_msg = result_text

            # 4. نشر النتيجة في قناة المحادثة
            channel_id = kwargs.get('channel_id')
            if channel_id:
                channel = request.env['discuss.channel'].sudo().browse(int(channel_id))
                if channel.exists():
                    html_body = final_msg.replace('\n', '<br>')
                    channel.message_post(body=html_body, author_id=request.env.ref('base.partner_root').id, message_type='comment')
                    
            return {'answer': final_msg, 'response': final_msg, 'status': 'success'}
            
        except Exception as e:
            _logger.exception("AI Bridge Critical Error: %s", e)
            return {'response': f"System Error: {e}"}