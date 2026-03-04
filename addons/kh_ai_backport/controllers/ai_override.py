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

# الحفاظ على التحقق من المكتبات لضمان عدم توقف السيرفر
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    _logger.warning("Google GenAI library not found")
    HAS_GENAI = False

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    _logger.warning("PyPDF2 library not found")
    HAS_PDF = False

class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== SMART AI ROUTER: FULL AUTO-OPEN & MULTI-LINE =====')
        
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        # 1. جلب الرسالة والمرفقات بدقة (نفس منطق كودك الأصلي)
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

        # 2. شرطي المرور الذكي (Router)
        db_keywords = ['موظف', 'موظفين', 'مبيعات', 'عملاء', 'عميل', 'فواتير', 'how many', 'sales']
        needs_database = any(keyword in prompt_lower for keyword in db_keywords)

        if needs_database and not has_files:
            _logger.info("🚦 ROUTER: Internal Odoo Query")
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # 3. إعداد محرك الرؤية (Gemini Vision)
        system_prompt = """You are an expert ERP accountant for Khales Group.
        Analyze the document visually. If the user wants to create an invoice:
        1. Extract the Customer Name.
        2. Extract ALL line items (Description, Quantity, Unit Price).
        Reply ONLY with this JSON:
        {"action": "create_invoice", "customer_name": "Name", "invoice_lines": [{"desc": "Item", "qty": 1, "price": 10}]}
        """
        
        gemini_contents = [f"{system_prompt}\n\nUser Question: {prompt}"]
        
        for att in attachments:
            try:
                file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if file_bytes:
                    gemini_contents.append(
                        types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf')
                    )
            except Exception as e:
                _logger.error(f"Attachment Error: {e}")

        if not HAS_GENAI:
            return {'response': "Gemini SDK is not installed on this server."}

        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            return {'response': "Gemini API Key is missing in System Parameters."}

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=gemini_contents)
            result_text = getattr(response, "text", str(response)).strip()
            
            # تنظيف الـ JSON
            clean_json_str = re.sub(r'```json|```', '', result_text).strip()
            
            try:
                parsed_data = json.loads(clean_json_str)
                if parsed_data.get('action') == 'create_invoice':
                    _logger.info("🛠️ Executing Autonomous Invoice Creation")
                    
                    env = request.env
                    c_name = parsed_data.get('customer_name')
                    
                    # البحث عن العميل أو إنشاؤه
                    partner = env['res.partner'].sudo().search([('name', '=ilike', c_name)], limit=1)
                    if not partner:
                        partner = env['res.partner'].sudo().create({'name': c_name})
                    
                    # تحديد حساب الإيرادات (متوافق مع Odoo 19)
                    income_account = env['account.account'].sudo().search([
                        ('account_type', '=', 'income'), 
                        ('company_ids', 'in', env.company.id)
                    ], limit=1)

                    # بناء الأسطر المتعددة
                    invoice_line_ids = []
                    for line in parsed_data.get('invoice_lines', []):
                        invoice_line_ids.append((0, 0, {
                            'name': line.get('desc', 'AI Extracted Line'),
                            'quantity': float(line.get('qty', 1.0)),
                            'price_unit': float(line.get('price', 0.0)),
                            'account_id': income_account.id if income_account else False
                        }))

                    # الإنشاء النهائي
                    new_inv = env['account.move'].sudo().create({
                        'move_type': 'out_invoice',
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_line_ids
                    })

                    _logger.info(f"✅ Invoice Created: {new_inv.id}")

                    # الرد الذي يفتح النافذة تلقائياً
                    return {
                        'type': 'ir.actions.act_window',
                        'res_model': 'account.move',
                        'res_id': new_inv.id,
                        'views': [[False, 'form']],
                        'target': 'current',
                    }

            except (json.JSONDecodeError, ValueError):
                pass # ليس طلباً لإنشاء فاتورة، أكمل كرسالة نصية

            # 4. الرد النصي العام (في حال لم يكن هناك إنشاء فاتورة)
            channel_id = kwargs.get('channel_id')
            if channel_id:
                channel = request.env['discuss.channel'].sudo().browse(int(channel_id))
                if channel.exists():
                    html_body = result_text.replace('\n', '<br>')
                    channel.message_post(
                        body=html_body, 
                        author_id=request.env.ref('base.partner_root').id,
                        message_type='comment'
                    )
            
            return {'answer': result_text, 'response': result_text, 'status': 'success'}

        except Exception as e:
            _logger.exception("Final Logic Error: %s", e)
            return {'response': f"AI Processing Error: {str(e)}"}