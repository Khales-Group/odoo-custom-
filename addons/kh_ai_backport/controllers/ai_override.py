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
        _logger.info('===== KH_AI: WEBSOCKET & PROMPT MASTER MODE =====')
        
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

        has_files = len(attachments) > 0

        # ==========================================
        # 🛑 1. أسئلة الداتابيز (بدون مرفقات)
        # ==========================================
        if not has_files:
            try:
                return super(AIControllerOverride, self).generate_response(**kwargs)
            except Exception as e:
                _logger.error(f"Native Odoo AI Failed: {e}")
                return {} 

        # ==========================================
        # 🚀 2. معالجة الملفات (فواتير + شرح أكواد)
        # ==========================================
        system_prompt = """You are 'Khales AI', a witty and helpful ERP assistant.
        Analyze the user's message and attached documents.
        
        ALWAYS return a valid JSON object with EXACTLY this structure:
        {
          "intent": "create_invoice" or "chat",
          "message": "Write a friendly reply here in the user's language. If it's an invoice, say you are creating it. If it's a question, answer it clearly.",
          "invoice_data": {
            "move_type": "in_invoice" or "out_invoice",
            "partner_name": "Name",
            "trn": "TRN",
            "vat_amount": 0.0,
            "lines": [{"desc": "Item", "qty": 1, "price": 10}]
          }
        }
        
        RULES:
        - If the document is an invoice/bill, set intent to 'create_invoice' and fill 'invoice_data'.
        - If it's code, an email, or a general question, set intent to 'chat'.
        - The 'message' key is MANDATORY. Never leave it empty!"""
        
        gemini_contents = [f"{system_prompt}\n\nUser Message: {prompt}"]
        for att in attachments:
            file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
            if file_bytes:
                gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

        if not HAS_GENAI: return {}
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=gemini_contents)
            result_text = getattr(response, "text", str(response)).strip()
            clean_json_str = re.sub(r'```json|```', '', result_text).strip()
            
            try:
                data = json.loads(clean_json_str)
                intent = data.get('intent', 'chat')
                
                # 💬 سحبنا الرسالة اللي كتبها الذكاء الاصطناعي (وغيرنا الجملة الاحتياطية عشان ما تعصب 😂)
                chat_msg = data.get('message', 'تم استلام الملف وجاري معالجته بنجاح.')

                # 🚀 نشر الرسالة بقاعدة البيانات لتظهر الفقاعة فوراً
                if mail_message_id:
                    msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                    if msg_record.model == 'discuss.channel':
                        channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                        ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                        author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                        channel.message_post(body=chat_msg, author_id=author_id, message_type='comment')

                # === مسار الفواتير ===
                if intent == 'create_invoice' and data.get('invoice_data'):
                    inv_data = data['invoice_data']
                    move_type = inv_data.get('move_type', 'in_invoice')
                    env = request.env
                    
                    p_name = inv_data.get('partner_name') or 'Unknown Partner'
                    partner = env['res.partner'].sudo().search([('name', '=ilike', p_name)], limit=1)
                    if not partner: partner = env['res.partner'].sudo().create({'name': p_name, 'vat': inv_data.get('trn')})
                    
                    acc_type = 'expense' if move_type == 'in_invoice' else 'income'
                    account = env['account.account'].sudo().search([('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)

                    invoice_lines = []
                    for l in inv_data.get('lines', []):
                        invoice_lines.append((0, 0, {'name': l.get('desc', 'Item'), 'quantity': float(l.get('qty', 1.0)), 'price_unit': float(l.get('price', 0.0)), 'account_id': account.id if account else False}))
                    if inv_data.get('vat_amount', 0) > 0:
                        invoice_lines.append((0, 0, {'name': 'VAT', 'quantity': 1.0, 'price_unit': float(inv_data.get('vat_amount')), 'account_id': account.id if account else False}))

                    new_move = env['account.move'].sudo().create({'move_type': move_type, 'partner_id': partner.id, 'invoice_line_ids': invoice_lines, 'ref': f"AI-REF-{inv_data.get('trn', '')}"})

                    env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {'title': 'Success', 'message': f'Created {move_type}', 'type': 'success', 'sticky': True})

                    return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': new_move.id, 'views': [[False, 'form']], 'target': 'current'}

                return {} 

            except json.JSONDecodeError:
                # 🛡️ إذا فشل الجيسون، نطبع الرد كنص عادي عشان الشات ما يضل فاضي
                if mail_message_id:
                    msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                    if msg_record.model == 'discuss.channel':
                        channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                        ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                        author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                        channel.message_post(body=result_text, author_id=author_id, message_type='comment')
                return {}

        except Exception as e:
            _logger.exception("AI Error")
            return {}