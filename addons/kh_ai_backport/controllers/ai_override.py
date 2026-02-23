# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.tools import html2plaintext
import base64
import io
import logging
import time, random

_logger = logging.getLogger(__name__)

# دعم الـ PDF
try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

# دعم Gemini
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

class AIControllerGeminiDirect(http.Controller):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== GEMINI DIRECT (MAIL MESSAGE MODE) =====')
        
        prompt = ""
        extracted_text = ""
        attachments = []

        # 1. السر: قراءة الرسالة من قاعدة البيانات عبر الـ ID
        mail_message_id = kwargs.get('mail_message_id')
        
        if mail_message_id:
            message = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if message.exists():
                # أودو يحفظ الرسالة كـ HTML، نحولها لنص عادي عشان يفهمها Gemini
                prompt = html2plaintext(message.body) if message.body else ""
                # جلب الملفات المرفقة بالرسالة مباشرة
                attachments = message.attachment_ids
        else:
            # خطة احتياطية لو تم الإرسال بالطريقة القديمة
            raw_prompt = kwargs.get('prompt') or kwargs.get('question') or kwargs.get('text') or ''
            prompt = html2plaintext(raw_prompt) if '<' in raw_prompt else raw_prompt
            att_ids = kwargs.get('attachments') or kwargs.get('attachment_ids') or []
            if att_ids:
                attachments = request.env['ir.attachment'].sudo().browse([int(i) for i in att_ids if str(i).isdigit()])

        # 2. استخراج النصوص من المرفقات
        for att in attachments:
            try:
                file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if not file_bytes: continue

                mime = att.mimetype or ''
                file_name = att.name or 'Unknown_File'

                if HAS_PDF and 'pdf' in mime:
                    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                    extracted_text += f"\n--- [File: {file_name}] ---\n"
                    for page in reader.pages:
                        extracted_text += page.extract_text() or ''
                        
                elif any(x in mime for x in ['text', 'csv', 'json']):
                    extracted_text += f"\n--- [File: {file_name}] ---\n"
                    extracted_text += file_bytes.decode('utf-8', errors='ignore')
                else:
                    _logger.warning("Unsupported file type for AI text extraction: %s", mime)

            except Exception as e:
                _logger.exception('File extraction failed: %s', e)

        # 3. البرومبت الحر (Freedom Mode)
        system_prompt = "You are a helpful and intelligent AI assistant. Use provided context files to answer user questions if applicable."
        if extracted_text:
            final_prompt = f"{system_prompt}\n\n--- FILE CONTEXT ---\n{extracted_text}\n-------------------\n\nUser Question: {prompt}"
        else:
            final_prompt = f"{system_prompt}\n\nUser Question: {prompt}"

        # 4. التحقق من الإعدادات
        if not HAS_GENAI:
            return {'response': "Gemini SDK not available."}

        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            return {'response': "Gemini API key missing in System Parameters."}

        try:
            client = genai.Client(api_key=api_key)
        except Exception as e:
            return {'response': f"Gemini initialization error: {e}"}

        # 5. الاتصال بـ Gemini مع نظام إعادة المحاولة
        def call_gemini(prompt_text, attempts=3):
            last_exc = None
            for i in range(1, attempts + 1):
                try:
                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[{"role": "user", "parts": [{"text": prompt_text}]}],
                    )
                    return resp.text if hasattr(resp, 'text') else resp.candidates[0].content.parts[0].text
                except Exception as exc:
                    last_exc = exc
                    if i < attempts:
                        time.sleep((2 ** (i - 1)) * 0.6 + random.uniform(0, 0.4))
            raise last_exc

        # 6. التنفيذ النهائي
        try:
            result_text = call_gemini(final_prompt)
            _logger.info("FINAL TEXT FROM GEMINI: %s", result_text)
            
            return {
                'answer': result_text,
                'response': result_text,
                'message': result_text,
                'status': 'success',
            }
        except Exception as e:
            _logger.exception("Gemini API error: %s", e)
            return {'response': f"AI processing error: {e}"}