# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.tools import html2plaintext
import base64
import io
import logging

_logger = logging.getLogger(__name__)

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

class AIControllerGeminiDirect(http.Controller):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== GEMINI DIRECT (ULTIMATE FILE READER) =====')
        
        prompt = ""
        extracted_text = ""
        attachments = request.env['ir.attachment'].sudo()

        # 1. جلب الرسالة والمرفقات من قاعدة البيانات
        mail_message_id = kwargs.get('mail_message_id')
        if mail_message_id:
            message = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if message.exists():
                prompt = html2plaintext(message.body) if message.body else ""
                attachments = message.attachment_ids
                _logger.info("Found Message ID %s with %s attachments.", message.id, len(attachments))
        else:
            raw_prompt = kwargs.get('prompt') or kwargs.get('question') or kwargs.get('text') or ''
            prompt = html2plaintext(raw_prompt) if '<' in raw_prompt else raw_prompt

        # 2. استخراج النص بأقوى طريقة ممكنة
        for att in attachments:
            _logger.info("Processing File: %s (MimeType: %s)", att.name, att.mimetype)
            file_text = ""
            
            # الطريقة الأولى: استخدام محرك أودو الداخلي (الأقوى والأسرع)
            if att.index_content:
                file_text = att.index_content
                _logger.info("SUCCESS: Text extracted using Odoo index_content.")
            else:
                # الطريقة الثانية: فك التشفير اليدوي
                try:
                    file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                    if file_bytes:
                        if 'pdf' in (att.mimetype or ''):
                            try:
                                import PyPDF2
                                reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                                file_text = "".join([page.extract_text() or '' for page in reader.pages])
                                _logger.info("SUCCESS: Text extracted using PyPDF2.")
                            except Exception as e:
                                _logger.error("PyPDF2 failed: %s", e)
                        else:
                            file_text = file_bytes.decode('utf-8', errors='ignore')
                            _logger.info("SUCCESS: Text extracted using UTF-8 decode.")
                except Exception as e:
                    _logger.error("Manual extraction failed: %s", e)

            if file_text:
                extracted_text += f"\n--- [File: {att.name}] ---\n{file_text}\n"
            else:
                _logger.warning("FAILED: Could not extract any text from file %s", att.name)

        # 3. بناء البرومبت
        system_prompt = "You are a helpful AI assistant. Use the provided file context to answer the user's question. If no context is provided, answer normally."
        if extracted_text:
            final_prompt = f"{system_prompt}\n\n--- FILE CONTEXT ---\n{extracted_text}\n-------------------\n\nUser Question: {prompt}"
        else:
            final_prompt = f"{system_prompt}\n\nUser Question: {prompt}"

        # 4. الاتصال بجوجل
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
            _logger.info("FINAL TEXT FROM GEMINI RECEIVED.")
            
            return {
                'answer': result_text,
                'response': result_text,
                'status': 'success',
            }
        except Exception as e:
            _logger.exception("Gemini API error: %s", e)
            return {'response': f"AI error: {e}"}