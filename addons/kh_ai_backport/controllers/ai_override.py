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
        _logger.info('===== KH_AI: FORCED AUTO-OPEN MODE =====')
        
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

        # 2. إعداد Gemini Vision لاستخراج البيانات
        system_prompt = """You are an ERP expert. Analyze the document.
        Return ONLY JSON: {"action": "create_invoice", "customer_name": "X", "invoice_lines": [{"desc": "Y", "qty": 1, "price": 10}]}"""
        
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
                if parsed_data.get('action') == 'create_invoice':
                    env = request.env
                    c_name = parsed_data.get('customer_name')
                    
                    partner = env['res.partner'].sudo().search([('name', '=ilike', c_name)], limit=1)
                    if not partner:
                        partner = env['res.partner'].sudo().create({'name': c_name})
                    
                    income_account = env['account.account'].sudo().search([
                        ('account_type', '=', 'income'), 
                        ('company_ids', 'in', env.company.id)
                    ], limit=1)
                    
                    lines = []
                    for l in parsed_data.get('invoice_lines', []):
                        lines.append((0, 0, {
                            'name': l.get('desc', 'AI Item'),
                            'quantity': float(l.get('qty', 1.0)),
                            'price_unit': float(l.get('price', 0.0)),
                            'account_id': income_account.id if income_account else False
                        }))

                    # إنشاء الفاتورة
                    new_inv = env['account.move'].sudo().create({
                        'move_type': 'out_invoice',
                        'partner_id': partner.id,
                        'invoice_line_ids': lines
                    })

                    # --- بناء الرابط الصافي والمباشر ---
                    base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
                    inv_url = f"{base_url.rstrip('/')}/web#id={new_inv.id}&model=account.move&view_type=form"
                    
                    # الرد النصي اللي رح يظهر في الشات ويحل مشكلة "No Response"
                    success_msg = f"✅ Success! Invoice #{new_inv.id} created for {partner.name}.\nLink: {inv_url}"

                    # 🚀 إرسال تنبيه "أودو" الرسمي (Sticky Notification) ليظهر فوق في الشاشة
                    # هذا سيجعل المستخدم يرى النجاح فوراً حتى لو الشات علق
                    request.env['bus.bus']._sendone(request.env.user.partner_id, 'simple_notification', {
                        'title': 'AI Invoice Created',
                        'message': f'Invoice for {partner.name} is ready.',
                        'type': 'success',
                        'sticky': True,
                    })

                    return {
                        'answer': success_msg,
                        'response': success_msg,
                        'status': 'success'
                    }

            except Exception as e:
                _logger.error(f"JSON Parsing Error: {e}")

            return {'answer': result_text, 'response': result_text, 'status': 'success'}

        except Exception as e:
            _logger.exception("AI Error")
            return {'response': f"Error: {e}"}