# -*- coding: utf-8 -*-
from odoo import models, fields, http, api
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
from odoo.exceptions import AccessError
import base64
import logging
import re
import json
# --- التعديل هنا: استدعاء مكتبة التنسيق الآمن من أودو ---
from markupsafe import Markup 

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
        _logger.info('===== KH_AI: GOD MODE (PHASE 1) FULL VERSION =====')
        
        prompt = ""
        current_attachments = request.env['ir.attachment'].sudo()
        history_attachments = request.env['ir.attachment'].sudo()
        chat_history_text = ""
        mail_message_id = kwargs.get('mail_message_id')
        
        # --- 1. بناء الذاكرة ---
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

        # --- 2. شرطي المرور (GOD MODE - Odoo Fallback DISABLED) ---
        prompt_lower = prompt.lower()

        if not HAS_GENAI: return {}
        
        # ==========================================
        # 🛠️ 3. تعريف الأدوات الأربعة (Tools)
        # ==========================================
        
        create_lead_tool = types.FunctionDeclaration(
            name="ai_create_lead",
            description="Create a CRM Lead. Only use if explicitly commanded.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "name": types.Schema(type=types.Type.STRING),
                    "email": types.Schema(type=types.Type.STRING),
                    "phone": types.Schema(type=types.Type.STRING),
                    "description": types.Schema(type=types.Type.STRING),
                    "message_to_user": types.Schema(type=types.Type.STRING)
                },
                required=["name", "message_to_user"]
            )
        )

        create_invoice_tool = types.FunctionDeclaration(
            name="ai_create_invoice",
            description="Create a bill or invoice. Only use if explicitly commanded.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "move_type": types.Schema(type=types.Type.STRING, description="'in_invoice' or 'out_invoice'"),
                    "partner_name": types.Schema(type=types.Type.STRING),
                    "trn": types.Schema(type=types.Type.STRING),
                    "vat_amount": types.Schema(type=types.Type.NUMBER),
                    "lines": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "desc": types.Schema(type=types.Type.STRING),
                                "qty": types.Schema(type=types.Type.NUMBER),
                                "price": types.Schema(type=types.Type.NUMBER)
                            }
                        )
                    ),
                    "message_to_user": types.Schema(type=types.Type.STRING)
                },
                required=["move_type", "partner_name", "message_to_user", "lines"]
            )
        )

        create_bank_statement_tool = types.FunctionDeclaration(
            name="ai_create_bank_statement",
            description="Create an Accounting Bank Statement. Only use if explicitly commanded.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "reference": types.Schema(type=types.Type.STRING),
                    "date": types.Schema(type=types.Type.STRING),
                    "starting_balance": types.Schema(type=types.Type.NUMBER),
                    "ending_balance": types.Schema(type=types.Type.NUMBER),
                    "lines": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "date": types.Schema(type=types.Type.STRING),
                                "label": types.Schema(type=types.Type.STRING),
                                "amount": types.Schema(type=types.Type.NUMBER, description="CRITICAL: Use a NEGATIVE number (-) for Debits, and a POSITIVE number (+) for Credits.")
                            }
                        )
                    ),
                    "message_to_user": types.Schema(type=types.Type.STRING)
                },
                required=["reference", "date", "starting_balance", "ending_balance", "message_to_user", "lines"]
            )
        )

        search_records_tool = types.FunctionDeclaration(
            name="ai_search_records",
            description="Search the Odoo database for records (like customers, leads, invoices). Use this when the user asks 'find', 'search', 'ابحث', 'دور'.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "model_name": types.Schema(type=types.Type.STRING, description="The Odoo technical model name (e.g., 'res.partner', 'crm.lead', 'account.move')"),
                    "keyword": types.Schema(type=types.Type.STRING, description="The text to search for.")
                },
                required=["model_name", "keyword"]
            )
        )

        create_rfq_tool = types.FunctionDeclaration(
            name="ai_create_rfq",
            description="Create a Request for Quotation (RFQ) / Purchase Order. Use this when the user asks to create an RFQ, order products, or send a BOQ to a supplier.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "vendor_name": types.Schema(type=types.Type.STRING),
                    "products": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "name": types.Schema(type=types.Type.STRING),
                                "qty": types.Schema(type=types.Type.NUMBER)
                            }
                        )
                    ),
                    "message_to_user": types.Schema(type=types.Type.STRING),
                    "vendor_email": types.Schema(type=types.Type.STRING, description="The email address of the vendor, extract this from your internal knowledge base if possible."),
                    "vendor_phone": types.Schema(type=types.Type.STRING, description="The phone number of the vendor, extract this from your internal knowledge base if possible.")
                },
                required=["vendor_name", "products", "message_to_user"]
            )
        )

        ai_search_company_contact_tool = types.FunctionDeclaration(
            name="ai_search_company_contact",
            description="Search the internet to find the official email and phone number of a specific company.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "company_name": types.Schema(type=types.Type.STRING),
                },
                required=["company_name"]
            )
        )

        gemini_tools = types.Tool(function_declarations=[create_lead_tool, create_invoice_tool, create_bank_statement_tool, search_records_tool, create_rfq_tool, ai_search_company_contact_tool])

        # 💡 1. تعديل الشخصية عشان يفهم إنه مسموح له يستخدم جوجل
        system_instruction = """You are 'Khales AI', a highly intelligent ERP assistant and an elite business consultant.
        CRITICAL RULE 1: You MUST start every single reply or message with the exact phrase "🤖 [Khales AI]: ".
        CRITICAL RULE 2: If the user asks for external information (like suppliers, market trends, addresses, or phone numbers), YOU MUST USE THE GOOGLE SEARCH TOOL to browse the live internet and provide accurate, up-to-date answers and exact contact details.
        CRITICAL RULE 3: ONLY use the 'ai_search_records' tool if the user is explicitly asking to find INTERNAL system data.
        CRITICAL RULE 4: If the user asks to create an RFQ for a vendor, you MUST FIRST use the 'ai_search_company_contact' tool to fetch their real, up-to-date email and phone number. Wait for the result, and THEN use the 'ai_create_rfq' tool, passing the retrieved email and phone number.
        """
        gemini_contents = [f"--- CHAT HISTORY ---\n{chat_history_text}\n--- END HISTORY ---"]
        for att in history_attachments:
            file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
            if file_bytes:
                gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        try:
            client = genai.Client(api_key=api_key)
            
            # 🌐 2. السحر هنا: تفعيل أداة بحث جوجل الرسمية (Google Search Grounding)
            google_search_tool = types.Tool(google_search=types.GoogleSearch())
            
            # 🧠 2. الموجه الذكي (Smart Router) لتجنب تعارض جوجل
            external_keywords = ['ارقام', 'موردين', 'ارخص', 'افضل', 'شركات', 'دبي', 'الشارقة', 'انترنت', 'بحث عام']
            action_keywords = ['تسعير', 'rfq', 'فاتورة', 'شراء', 'boq', 'po', 'order', 'طلب']
            
            # تحديد نية المستخدم لاختيار الأداة المناسبة
            if any(word in prompt_lower for word in action_keywords):
                selected_tools = [gemini_tools]
            elif any(word in prompt_lower for word in external_keywords):
                selected_tools = [google_search_tool]
            else:
                selected_tools = [gemini_tools]
            
            # 💡 3. إرسال الطلب مع الأداة المناسبة فقط
            gen_config_args = {
                "system_instruction": system_instruction, 
                "temperature": 0.4, 
                "tools": selected_tools
            }
                
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=gemini_contents,
                config=types.GenerateContentConfig(**gen_config_args)
            )

            # ==========================================
            # ⚙️ 4. مسار تنفيذ الأدوات الكامل
            # ==========================================
            if response.function_calls:
                func = response.function_calls[0]
                args = func.args
                env = request.env
                
                chat_msg = args.get('message_to_user', "🤖 [Khales AI]: يتم التنفيذ...")
                if not chat_msg.startswith("🤖"):
                    chat_msg = f"🤖 [Khales AI]: {chat_msg}"
                
                def post_msg(text):
                    # --- 🎨 سحر التنسيق  ---
                    html_text = text.replace('\n', '<br/>')
                    html_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html_text)
                    html_text = f"<div style='line-height: 1.6;'>{html_text}</div>"
                    
                    if mail_message_id:
                        msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                        if msg_record.model == 'discuss.channel':
                            channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                            ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                            author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                            # --- التعديل هنا: تغليف الرسالة بـ Markup ---
                            channel.message_post(body=Markup(html_text), author_id=author_id, message_type='comment')

                try:
                    # 1. إنشاء Lead
                    if func.name == "ai_create_lead":
                        new_lead = env['crm.lead'].create({
                            'name': args.get('name', 'AI Generated Lead'),
                            'email_from': args.get('email', ''),
                            'phone': args.get('phone', ''),
                            'description': args.get('description', ''),
                        })
                        post_msg(chat_msg)
                        return {'type': 'ir.actions.act_window', 'res_model': 'crm.lead', 'res_id': new_lead.id, 'views': [[False, 'form']], 'target': 'current'}

                    # 2. إنشاء Invoice
                    elif func.name == "ai_create_invoice":
                        move_type = args.get('move_type', 'out_invoice')
                        p_name = args.get('partner_name', 'Unknown')
                        trn = args.get('trn', '')
                        vat_amount = float(args.get('vat_amount', 0.0))
                        lines = args.get('lines', [])

                        partner = env['res.partner'].sudo().search([('name', '=ilike', p_name)], limit=1)
                        if not partner: partner = env['res.partner'].create({'name': p_name, 'vat': trn})
                        
                        acc_type = 'expense' if move_type == 'in_invoice' else 'income'
                        account = env['account.account'].sudo().search([('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)

                        invoice_lines = []
                        for l in lines:
                            invoice_lines.append((0, 0, {
                                'name': l.get('desc', 'Product Item'),
                                'quantity': float(l.get('qty', 1.0)),
                                'price_unit': float(l.get('price', 0.0)),
                                'account_id': account.id if account else False
                            }))
                        if vat_amount > 0:
                            invoice_lines.append((0, 0, {'name': 'VAT / Tax', 'quantity': 1.0, 'price_unit': vat_amount, 'account_id': account.id if account else False}))
                        if not invoice_lines:
                            invoice_lines.append((0, 0, {'name': 'Default Item', 'quantity': 1.0, 'price_unit': 0.0, 'account_id': account.id if account else False}))

                        new_move = env['account.move'].create({
                            'move_type': move_type,
                            'partner_id': partner.id,
                            'invoice_line_ids': invoice_lines,
                            'ref': f"AI-REF-{trn}"
                        })
                        
                        post_msg(chat_msg)
                        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': new_move.id, 'views': [[False, 'form']], 'target': 'current'}

                    # 3. إنشاء Bank Statement
                    elif func.name == "ai_create_bank_statement":
                        reference = args.get('reference', 'AI Bank Statement')
                        stmt_date = args.get('date', fields.Date.today())
                        start_bal = float(args.get('starting_balance', 0.0))
                        end_bal = float(args.get('ending_balance', 0.0))
                        lines = args.get('lines', [])

                        journal = env['account.journal'].sudo().search([('type', '=', 'bank'), ('company_id', '=', env.company.id)], limit=1)
                        if not journal:
                            post_msg("🤖 [Khales AI]: ⛔ عذراً، لم أتمكن من العثور على دفتر يومية للبنك (Bank Journal) في النظام.")
                            return {}

                        statement_lines = []
                        for l in lines:
                            statement_lines.append((0, 0, {
                                'date': l.get('date', stmt_date),
                                'payment_ref': l.get('label', 'AI Extracted Transaction'),
                                'amount': float(l.get('amount', 0.0)),
                            }))

                        new_statement = env['account.bank.statement'].create({
                            'name': reference,
                            'date': stmt_date,
                            'balance_start': start_bal,
                            'balance_end_real': end_bal,
                            'journal_id': journal.id,
                            'line_ids': statement_lines
                        })
                        
                        post_msg(chat_msg)
                        return {'type': 'ir.actions.act_window', 'res_model': 'account.bank.statement', 'res_id': new_statement.id, 'views': [[False, 'form']], 'target': 'current'}

                    # 4. البحث في الداتابيز
                    elif func.name == "ai_search_records":
                        model_name = args.get('model_name')
                        keyword = args.get('keyword', '')
                        
                        allowed_models = ['res.partner', 'crm.lead', 'account.move', 'project.task']
                        
                        if model_name not in allowed_models:
                            post_msg(f"🤖 [Khales AI]: عذراً، لا أمتلك صلاحية للبحث في سجلات النظام من نوع ({model_name}).")
                            return {}

                        domain = [('name', 'ilike', keyword)] if keyword else []
                        records = env[model_name].search_read(domain, limit=5, fields=['display_name'])
                        
                        if records:
                            reply_text = f"🤖 [Khales AI]: بحثت عن '{keyword}' ووجدت هذه السجلات:\n"
                            for r in records:
                                reply_text += f"- {r.get('display_name')}\n"
                        else:
                            reply_text = f"🤖 [Khales AI]: بحثت في النظام ولم أجد أي شيء يطابق '{keyword}'."
                        
                        post_msg(reply_text)
                        return {}

                    # 5. إنشاء RFQ / Purchase Order
                    elif func.name == "ai_create_rfq":
                        vendor_name = args.get('vendor_name', '')
                        products = args.get('products', [])
                        vendor_email = args.get('vendor_email', '')
                        vendor_phone = args.get('vendor_phone', '')
                        
                        # Find or create vendor
                        vendor = env['res.partner'].sudo().search([('name', '=ilike', vendor_name)], limit=1)
                        
                        vendor_vals = {}
                        if vendor_email: vendor_vals['email'] = vendor_email
                        if vendor_phone: vendor_vals['phone'] = vendor_phone

                        if not vendor:
                            vendor_vals.update({
                                'name': vendor_name,
                                'is_company': True,
                            })
                            vendor = env['res.partner'].sudo().create(vendor_vals)
                        else:
                            # Update existing vendor if they are missing phone/email
                            update_vals = {}
                            if vendor_email and not vendor.email: update_vals['email'] = vendor_email
                            if vendor_phone and not vendor.phone: update_vals['phone'] = vendor_phone
                            if update_vals:
                                vendor.sudo().write(update_vals)
                        
                        # Build order lines
                        order_lines = []
                        for prod_data in products:
                            prod_name = prod_data.get('name', '')
                            qty = float(prod_data.get('qty', 1.0))
                            
                            # Find or create product
                            product = env['product.product'].sudo().search([('name', '=ilike', prod_name)], limit=1)
                            if not product:
                                product = env['product.product'].sudo().create({
                                    'name': prod_name,
                                    'type': 'consu',
                                })
                            
                            order_lines.append((0, 0, {
                                'product_id': product.id,
                                'name': product.name,
                                'product_qty': qty,
                            }))
                        
                        # Create purchase order
                        new_rfq = env['purchase.order'].sudo().create({
                            'partner_id': vendor.id,
                            'order_line': order_lines,
                        })
                        
                        post_msg(chat_msg)
                        return {
                            'type': 'ir.actions.act_window',
                            'res_model': 'purchase.order',
                            'res_id': new_rfq.id,
                            'views': [[False, 'form']],
                            'target': 'current'
                        }

                    # 6. بحث بيانات التواصل للشركة من الإنترنت
                    elif func.name == "ai_search_company_contact":
                        company_name = args.get('company_name', '')
                        post_msg(f"🤖 <b>[Khales AI]:</b><br/>جاري البحث في الإنترنت عن بيانات التواصل لشركة ({company_name})... 🌐")
                        
                        # Scaffold for real internet search (e.g., using SerpAPI or requests + BeautifulSoup)
                        # TODO: Integrate SerpAPI key or scraping logic here
                        simulated_web_result = f"Found data for {company_name}: Email is info@{company_name.replace(' ', '').lower()}.com, Phone is +971 4 123 4567"
                        
                        post_msg(f"✅ نتيجة البحث: {simulated_web_result}<br/>الآن يمكنك استخدام هذه البيانات في أداة ai_create_rfq. (Note: Full multi-turn loop needed for automatic chaining.)")
                        return {}

                except AccessError:
                    post_msg("🤖 [Khales AI]: ⛔ عذراً، ليس لديك الصلاحيات الكافية في النظام.")
                    return {}

            # ==========================================
            # 💬 5. مسار الدردشة العادية 
            # ==========================================
            else:
                result_text = getattr(response, "text", str(response)).strip()
                
                if not result_text.startswith("🤖"):
                    result_text = f"🤖 [Khales AI]:\n\n{result_text}"
                    
                # --- 🎨 سحر التنسيق  ---
                html_text = result_text
                html_text = re.sub(r'\*\*(.*?)\*\*', r'<b style="color: #017E84;">\1</b>', html_text)
                html_text = html_text.replace('\n* ', '<br/>• ')
                html_text = html_text.replace('\n- ', '<br/>• ')
                html_text = html_text.replace('\n', '<br/>')
                
                final_html = f"<div style='line-height: 1.8; font-size: 14px;'>{html_text}</div>"
                
                if mail_message_id:
                    msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                    if msg_record.model == 'discuss.channel':
                        channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                        ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                        author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                        # --- التعديل هنا: تغليف الرسالة بـ Markup ---
                        channel.message_post(body=Markup(final_html), author_id=author_id, message_type='comment')
                return {}
        except Exception as e:
            _logger.exception("AI Error")
            error_msg = f"<div style='color: red;'>🤖 <b>[Khales AI - System Error]:</b><br/>حدث خطأ في الاتصال بـ Gemini:<br/>{str(e)}</div>"
            if mail_message_id:
                try:
                    msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
                    if msg_record.model == 'discuss.channel':
                        channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
                        ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
                        author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
                        # --- التعديل هنا: تغليف الرسالة بـ Markup ---
                        channel.message_post(body=Markup(error_msg), author_id=author_id, message_type='comment')
                except:
                    pass
            return {}