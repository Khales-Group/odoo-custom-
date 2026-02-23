# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.tools import html2plaintext
# استيراد الكنترولر الأصلي لأودو عشان نقدر نشغله وقت الحاجة
from odoo.addons.ai.controllers.main import AIController
import base64
import io
import logging

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

# الوراثة من الكنترولر الأصلي
class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== SMART AI ROUTER (ODOO + GEMINI) =====')
        
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        # 1. جلب الرسالة والمرفقات لفحصها
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

        # ==========================================
        # 🚦 شرطي المرور الذكي (The Router) 🚦
        # ==========================================
        
        # قائمة الكلمات التي تدل على أن المستخدم يريد بيانات من قاعدة البيانات
        # (تقدر تضيف أو تعدل عليها براحتك مستقبلاً)
        db_keywords = [
            'موظف', 'موظفين', 'مبيعات', 'عملاء', 'عميل', 'فواتير', 'فاتورة', 'مخزن',
            'كم عدد', 'موظف عنا', 'employee', 'sales', 'customer', 'invoice', 'how many'
        ]

        # هل السؤال يحتوي على كلمة من القائمة؟
        needs_database = any(keyword in prompt_lower for keyword in db_keywords)

        # القرار: إذا طلب داتا ومافي ملفات -> روح لأودو (Odoo Native AI)
        if needs_database and not has_files:
            _logger.info("🚦 ROUTER: Routing to Odoo Native AI (Database query detected)")
            # تشغيل محرك أودو الأصلي وإرجاع النتيجة
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # القرار: غير كذا -> روح لـ Gemini (ملفات، أسئلة عامة، ترجمة، الخ)
        _logger.info("🚦 ROUTER: Routing to Gemini AI (Files or General query detected)")
        # ==========================================

        # --- مسار GEMINI ---
        extracted_text = ""
        
        # استخراج النص من الملفات المرفقة
        for att in attachments:
            file_text = ""
            if att.index_content:
                file_text = att.index_content
            else:
                try:
                    file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                    if file_bytes:
                        if 'pdf' in (att.mimetype or ''):
                            try:
                                reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                                file_text = "".join([page.extract_text() or '' for page in reader.pages])
                            except Exception: pass
                        else:
                            file_text = file_bytes.decode('utf-8', errors='ignore')
                except Exception: pass

            if file_text:
                extracted_text += f"\n--- [File: {att.name}] ---\n{file_text}\n"

        # بناء البرومبت لـ Gemini
        system_prompt = "You are a helpful AI assistant. Use the provided file context to answer the user's question. If no context is provided, answer normally."
        final_prompt = f"{system_prompt}\n\n--- FILE CONTEXT ---\n{extracted_text}\n-------------------\n\nUser Question: {prompt}" if extracted_text else f"{system_prompt}\n\nUser Question: {prompt}"

        # الاتصال بجوجل
        if not HAS_GENAI:
            return {'response': "Gemini SDK not available."}

        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            return {'response': "Gemini API key missing."}

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=final_prompt
            )
            result_text = getattr(response, "text", str(response))
            _logger.info("SUCCESS: Text received from Gemini.")
            
            # زراعة الرسالة في الشاشة (نفس حركتنا السحرية الأخيرة)
            channel_id = kwargs.get('channel_id')
            if channel_id:
                channel = request.env['discuss.channel'].sudo().browse(int(channel_id))
                if channel.exists():
                    html_body = result_text.replace('\n', '<br>')
                    bot_id = request.env.ref('base.partner_root').id
                    channel.message_post(
                        body=html_body,
                        author_id=bot_id,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                    )
                    
            return {
                'answer': result_text,
                'response': result_text,
                'status': 'success',
            }
            
        except Exception as e:
            _logger.exception("Gemini API error: %s", e)
            return {'response': f"AI error: {e}"}