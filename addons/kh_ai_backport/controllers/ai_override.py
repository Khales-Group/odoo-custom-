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
        _logger.info('===== KH_AI: CONTEXT MEMORY & CRM MODE =====')
        
        prompt = ""
        current_attachments = request.env['ir.attachment'].sudo()
        history_attachments = request.env['ir.attachment'].sudo()
        chat_history_text = ""
        
        mail_message_id = kwargs.get('mail_message_id')
        
        if mail_message_id:
            msg = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if msg.exists():
                prompt = html2plaintext(msg.body) if msg.body else ""
                current_attachments = msg.attachment_ids
                
                # 🧠 السحر هنا: بناء الذاكرة (سحب آخر 6 رسائل من نفس المحادثة)
                if msg.model == 'discuss.channel':
                    history_msgs = request.env['mail.message'].sudo().search(
                        [('model', '=', 'discuss.channel'), ('res_id', '=', msg.res_id)],
                        order='id desc', limit=6
                    )
                    # ترتيب زمني صحيح ليفهم سياق الحديث
                    for h_msg in reversed(history_msgs):
                        sender = "User" if h_msg.author_id.id == request.env.user.partner_id.id else "AI"
                        msg_body = html2plaintext(h_msg.body) if h_msg.body else ""
                        if msg_body:
                            chat_history_text += f"{sender}: {msg_body}\n"
                        if h_msg.attachment_ids:
                            history_attachments |= h_msg.attachment_ids
        else:
            raw_prompt = kwargs.get('prompt') or kwargs.get('question') or kwargs.get('text') or ''
            prompt = html2plaintext(raw_prompt) if '<' in raw_prompt else raw_prompt
            att_ids = kwargs.get('attachments') or kwargs.get('attachment_ids') or []
            if att_ids:
                current_attachments = request.env['ir.attachment'].sudo().browse([int(i) for i in att_ids if str(i).isdigit()])
                history_attachments = current_attachments
            chat_history_text = f"User: {prompt}\n"

        has_history_files = len(history_attachments) > 0

        # 🛑 شرطي المرور الذكي: إذا مافي ملفات نهائياً في تاريخ المحادثة، حوّله لذكاء أودو الأصلي
        if not has_history_files:
            try:
                return super(AIControllerOverride, self).generate_response(**kwargs)
            except Exception as e:
                _logger.error(f"Native Odoo AI Failed: {e}")
                return {} 

        # ==========================================
        # 🚀 البرومبت الذكي (مع الذاكرة وصلاحية إنشاء الـ Leads)
        # ==========================================
        system_prompt = """You are 'Khales AI', a smart ERP assistant.
        You are provided with the CHAT HISTORY and attached documents. Read the history to understand the context of the user's latest request.
        
        CRITICAL RULES:
        1. LANGUAGE LOCK: Reply in the SAME LANGUAGE as the user's latest message. (Arabic for Arabic, English for English).
        2. 'chat' INTENT: If the user asks for a summary, explanation, or general question, set intent to 'chat'. Extract details into the "message" key. DO NOT create records.
        3. 'create_invoice' INTENT: ONLY if the user EXPLICITLY asks to create/record a bill or invoice.
        4. 'create_lead' INTENT: ONLY if the user EXPLICITLY asks to create a Lead/CRM opportunity (e.g., "create a lead", "أنشئ فرصة"). Extract the info requested.
        
        ALWAYS return ONLY valid JSON:
        {
          "intent": "create_invoice" or "create_lead" or "chat",
          "message": "ردك هنا بنفس لغة المستخدم.",
          "invoice_data": {
            "move_type": "in_invoice" or "out_invoice",
            "partner_name": "Name",
            "trn": "TRN",
            "vat_amount": 0.0,
            "lines": [{"desc": "Item", "qty": 1, "price": 10}]
          },
          "lead_data": {
            "name": "Subject/Title of the lead based on document",
            "email_from": "extracted email if any",
            "phone": "extracted phone if any",
            "description": "Short summary"
          }
        }"""
        
        # إرسال تاريخ المحادثة بالكامل لـ Gemini
        gemini_contents = [f"{system_prompt}\n\n--- CHAT HISTORY ---\n{chat_history_text}\n--- END HISTORY ---"]
        
        # إرفاق جميع الملفات الموجودة في المحادثة الأخيرة
        for att in history_attachments:
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
                chat_msg = data.get('message', 'تمت المعالجة.')

                # 🌟 مسار إنشاء فرصة (CRM Lead) 🌟
                if intent == 'create_lead' and data.get('lead_data'):
                    lead_data = data['lead_data']
                    env = request.env
                    
                    new_lead = env['crm.lead'].sudo().create({
                        'name': lead_data.get('name', 'AI Generated Lead'),
                        'email_from': lead_data.get('email_from', ''),
                        'phone': lead_data.get('phone', ''),
                        'description': lead_data.get('description', ''),
                    })
                    env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {'title': 'Success', 'message': f'Created Lead: {new_lead.name}', 'type': 'success', 'sticky': True})

                    # طباعة الرسالة بالشات قبل الفتح
                    if mail_message_id:
                        msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                        if msg_record.model == 'discuss.channel':
                            channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                            ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                            author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                            channel.message_post(body=chat_msg, author_id=author_id, message_type='comment')

                    return {'type': 'ir.actions.act_window', 'res_model': 'crm.lead', 'res_id': new_lead.id, 'views': [[False, 'form']], 'target': 'current'}

                # === مسار إنشاء الفاتورة ===
                elif intent == 'create_invoice' and data.get('invoice_data'):
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

                    if mail_message_id:
                        msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                        if msg_record.model == 'discuss.channel':
                            channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                            ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                            author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                            channel.message_post(body=chat_msg, author_id=author_id, message_type='comment')

                    return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': new_move.id, 'views': [[False, 'form']], 'target': 'current'}

                # === مسار الدردشة العادية ===
                if mail_message_id:
                    msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                    if msg_record.model == 'discuss.channel':
                        channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                        ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                        author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                        channel.message_post(body=chat_msg, author_id=author_id, message_type='comment')

                return {} 

            except json.JSONDecodeError:
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