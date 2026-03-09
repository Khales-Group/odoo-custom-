# -*- coding: utf-8 -*-
from odoo import models, fields, http, api
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
import base64
import logging
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
        _logger.info('===== KH_AI: FUNCTION CALLING (NATIVE TOOLS) MODE =====')
        
        prompt = ""
        current_attachments = request.env['ir.attachment'].sudo()
        history_attachments = request.env['ir.attachment'].sudo()
        chat_history_text = ""
        mail_message_id = kwargs.get('mail_message_id')
        
        # --- 1. بناء الذاكرة (Context Memory) ---
        if mail_message_id:
            msg = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if msg.exists():
                prompt = html2plaintext(msg.body) if msg.body else ""
                current_attachments = msg.attachment_ids
                
                if msg.model == 'discuss.channel':
                    history_msgs = request.env['mail.message'].sudo().search(
                        [('model', '=', 'discuss.channel'), ('res_id', '=', msg.res_id)],
                        order='id desc', limit=6
                    )
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

        # --- 2. شرطي المرور (لأسئلة الداتابيز العادية) ---
        if not has_history_files:
            try:
                return super(AIControllerOverride, self).generate_response(**kwargs)
            except Exception as e:
                _logger.error(f"Native Odoo AI Failed: {e}")
                return {} 

        # ==========================================
        # 🚀 3. تجهيز الأدوات لـ Gemini (Function Calling Tools)
        # ==========================================
        if not HAS_GENAI: return {}
        
        # أداة 1: إنشاء الـ Lead
        create_lead_tool = types.FunctionDeclaration(
            name="ai_create_lead",
            description="Call this function ONLY when the user explicitly asks to create or open a CRM Lead/Opportunity.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "name": types.Schema(type=types.Type.STRING, description="Title of the lead"),
                    "email": types.Schema(type=types.Type.STRING, description="Extracted email address"),
                    "phone": types.Schema(type=types.Type.STRING, description="Extracted phone number"),
                    "description": types.Schema(type=types.Type.STRING, description="Summary of the request"),
                },
                required=["name"]
            )
        )

        # أداة 2: إنشاء الفاتورة
        create_invoice_tool = types.FunctionDeclaration(
            name="ai_create_invoice",
            description="Call this function ONLY when the user explicitly asks to create, add, or record a vendor bill or customer invoice.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "move_type": types.Schema(type=types.Type.STRING, description="Must be 'in_invoice' for bills or 'out_invoice' for invoices"),
                    "partner_name": types.Schema(type=types.Type.STRING, description="Name of the vendor or customer"),
                    "trn": types.Schema(type=types.Type.STRING, description="Tax Registration Number"),
                },
                required=["move_type", "partner_name"]
            )
        )

        gemini_tools = types.Tool(function_declarations=[create_lead_tool, create_invoice_tool])

        system_instruction = "You are 'Khales AI'. Read the chat history and documents. You have tools to create leads and invoices. USE TOOLS ONLY IF EXPLICITLY COMMANDED. Otherwise, just reply normally in the user's language."
        
        gemini_contents = [f"--- CHAT HISTORY ---\n{chat_history_text}\n--- END HISTORY ---"]
        for att in history_attachments:
            file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
            if file_bytes:
                gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        try:
            client = genai.Client(api_key=api_key)
            
            # إرسال الطلب مع تسليح Gemini بالأدوات
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=gemini_contents,
                config=types.GenerateContentConfig(
                    tools=[gemini_tools],
                    system_instruction=system_instruction,
                    temperature=0.1
                )
            )

            # ==========================================
            # ⚙️ 4. تنفيذ الأوامر إذا قرر Gemini استخدام أداة
            # ==========================================
            if response.function_calls:
                func = response.function_calls[0]
                args = func.args
                env = request.env
                
                # طباعة رسالة توضح إن الـ AI قرر يستخدم أداة
                chat_msg = f"✅ يتم الآن تنفيذ الأداة: {func.name}..."
                if mail_message_id:
                    msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                    if msg_record.model == 'discuss.channel':
                        channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                        ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                        author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                        channel.message_post(body=chat_msg, author_id=author_id, message_type='comment')

                # إذا ضغط Gemini على زر ai_create_lead
                if func.name == "ai_create_lead":
                    new_lead = env['crm.lead'].sudo().create({
                        'name': args.get('name', 'AI Generated Lead'),
                        'email_from': args.get('email', ''),
                        'phone': args.get('phone', ''),
                        'description': args.get('description', ''),
                    })
                    env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {'title': 'Tool Executed', 'message': f'Created Lead: {new_lead.name}', 'type': 'success', 'sticky': True})
                    return {'type': 'ir.actions.act_window', 'res_model': 'crm.lead', 'res_id': new_lead.id, 'views': [[False, 'form']], 'target': 'current'}

                # إذا ضغط Gemini على زر ai_create_invoice
                elif func.name == "ai_create_invoice":
                    move_type = args.get('move_type', 'in_invoice')
                    p_name = args.get('partner_name', 'Unknown')
                    partner = env['res.partner'].sudo().search([('name', '=ilike', p_name)], limit=1)
                    if not partner: partner = env['res.partner'].sudo().create({'name': p_name, 'vat': args.get('trn', '')})
                    acc_type = 'expense' if move_type == 'in_invoice' else 'income'
                    account = env['account.account'].sudo().search([('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)

                    new_move = env['account.move'].sudo().create({
                        'move_type': move_type,
                        'partner_id': partner.id,
                        'invoice_line_ids': [(0, 0, {'name': 'AI Extracted Item', 'quantity': 1.0, 'price_unit': 0.0, 'account_id': account.id if account else False})],
                        'ref': f"AI-REF-{args.get('trn', '')}"
                    })
                    env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {'title': 'Tool Executed', 'message': f'Created {move_type}', 'type': 'success', 'sticky': True})
                    return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': new_move.id, 'views': [[False, 'form']], 'target': 'current'}

            # ==========================================
            # 💬 5. مسار الدردشة العادية (إذا لم يقم Gemini باستدعاء أي أداة)
            # ==========================================
            else:
                result_text = getattr(response, "text", str(response)).strip()
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