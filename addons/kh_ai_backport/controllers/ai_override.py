# -*- coding: utf-8 -*-
from odoo import models, fields, http, api
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
import base64
import logging
import re
import json

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
        _logger.info('===== KH_AI: FLAWLESS FUNCTION CALLING MODE =====')
        
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

        # --- 2. شرطي المرور ---
        if not has_history_files:
            try:
                return super(AIControllerOverride, self).generate_response(**kwargs)
            except Exception as e:
                _logger.error(f"Native Odoo AI Failed: {e}")
                return {} 

        # ==========================================
        # 🚀 3. تجهيز الأدوات لـ Gemini (تم إصلاح مشكلة الأسطر واللغة)
        # ==========================================
        if not HAS_GENAI: return {}
        
        create_lead_tool = types.FunctionDeclaration(
            name="ai_create_lead",
            description="Use ONLY when user explicitly commands to create a lead/opportunity.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "name": types.Schema(type=types.Type.STRING, description="Title of the lead"),
                    "email": types.Schema(type=types.Type.STRING, description="Extracted email"),
                    "phone": types.Schema(type=types.Type.STRING, description="Extracted phone"),
                    "description": types.Schema(type=types.Type.STRING, description="Summary"),
                    "message_to_user": types.Schema(type=types.Type.STRING, description="MANDATORY: Message to reply to the user. MUST BE IN THE SAME LANGUAGE AS THE USER'S PROMPT (e.g., Arabic).")
                },
                required=["name", "message_to_user"]
            )
        )

        create_invoice_tool = types.FunctionDeclaration(
            name="ai_create_invoice",
            description="Use ONLY when user explicitly commands to create an invoice or bill.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "move_type": types.Schema(type=types.Type.STRING, description="'in_invoice' for Vendor Bills (Khales pays), 'out_invoice' for Customer Invoices (Khales receives money)"),
                    "partner_name": types.Schema(type=types.Type.STRING, description="Vendor or Customer name"),
                    "trn": types.Schema(type=types.Type.STRING, description="Tax Registration Number"),
                    "vat_amount": types.Schema(type=types.Type.NUMBER, description="Total VAT amount"),
                    "lines": types.Schema(
                        type=types.Type.ARRAY,
                        description="Invoice items list",
                        items=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "desc": types.Schema(type=types.Type.STRING),
                                "qty": types.Schema(type=types.Type.NUMBER),
                                "price": types.Schema(type=types.Type.NUMBER)
                            }
                        )
                    ),
                    "message_to_user": types.Schema(type=types.Type.STRING, description="MANDATORY: Friendly reply MUST BE IN THE SAME LANGUAGE AS THE USER'S PROMPT (e.g., strictly Arabic if user spoke Arabic). Explain if it's a Bill or Invoice.")
                },
                required=["move_type", "partner_name", "message_to_user", "lines"]
            )
        )

        gemini_tools = types.Tool(function_declarations=[create_lead_tool, create_invoice_tool])

        system_instruction = """You are 'Khales AI'. 
        CRITICAL RULES:
        1. LANGUAGE: ALWAYS reply in the exact language the user used. If Arabic, use only Arabic.
        2. INVOICE LINES: You must extract every single row from the invoice table into the 'lines' array.
        3. TOOLS: Call tools ONLY if the user gives a direct command like 'create invoice', 'أنشئ فاتورة', 'سوي ليد'. If they ask to 'read' or 'اشرح', just chat normally without tools."""
        
        gemini_contents = [f"--- CHAT HISTORY ---\n{chat_history_text}\n--- END HISTORY ---"]
        for att in history_attachments:
            file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
            if file_bytes:
                gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        try:
            client = genai.Client(api_key=api_key)
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
            # ⚙️ 4. تنفيذ الأوامر بدقة تامة
            # ==========================================
            if response.function_calls:
                func = response.function_calls[0]
                args = func.args
                env = request.env
                
                # الرد بلغتك أنت
                chat_msg = args.get('message_to_user', "تم تنفيذ الطلب بنجاح.")
                
                if mail_message_id:
                    msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                    if msg_record.model == 'discuss.channel':
                        channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                        ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                        author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                        channel.message_post(body=chat_msg, author_id=author_id, message_type='comment')

                if func.name == "ai_create_lead":
                    new_lead = env['crm.lead'].sudo().create({
                        'name': args.get('name', 'AI Generated Lead'),
                        'email_from': args.get('email', ''),
                        'phone': args.get('phone', ''),
                        'description': args.get('description', ''),
                    })
                    return {'type': 'ir.actions.act_window', 'res_model': 'crm.lead', 'res_id': new_lead.id, 'views': [[False, 'form']], 'target': 'current'}

                elif func.name == "ai_create_invoice":
                    move_type = args.get('move_type', 'in_invoice')
                    p_name = args.get('partner_name', 'Unknown')
                    trn = args.get('trn', '')
                    vat_amount = float(args.get('vat_amount', 0.0))
                    lines = args.get('lines', [])

                    partner = env['res.partner'].sudo().search([('name', '=ilike', p_name)], limit=1)
                    if not partner: partner = env['res.partner'].sudo().create({'name': p_name, 'vat': trn})
                    
                    acc_type = 'expense' if move_type == 'in_invoice' else 'income'
                    account = env['account.account'].sudo().search([('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)

                    invoice_lines = []
                    # 💡 الحل العبقري: استخراج الأسطر بدقة
                    for l in lines:
                        invoice_lines.append((0, 0, {
                            'name': l.get('desc', 'Product Item'),
                            'quantity': float(l.get('qty', 1.0)),
                            'price_unit': float(l.get('price', 0.0)),
                            'account_id': account.id if account else False
                        }))
                    
                    if vat_amount > 0:
                        invoice_lines.append((0, 0, {
                            'name': 'VAT / Tax',
                            'quantity': 1.0,
                            'price_unit': vat_amount,
                            'account_id': account.id if account else False
                        }))

                    # لضمان عدم وجود فاتورة فارغة
                    if not invoice_lines:
                        invoice_lines.append((0, 0, {'name': 'Default Item', 'quantity': 1.0, 'price_unit': 0.0, 'account_id': account.id if account else False}))

                    new_move = env['account.move'].sudo().create({
                        'move_type': move_type,
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_lines,
                        'ref': f"AI-REF-{trn}"
                    })
                    return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': new_move.id, 'views': [[False, 'form']], 'target': 'current'}

            # ==========================================
            # 💬 5. مسار الدردشة العادية
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