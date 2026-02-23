# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
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
        _logger.info('===== GEMINI DIRECT (FREEDOM MODE) =====')

        prompt = kwargs.get('prompt') or kwargs.get('question') or ''
        attachments = kwargs.get('attachments') or []

        extracted_text = ""
        
        # 1. معالجة قوية للمرفقات (PDF, TXT, CSV, JSON)
        for item in attachments:
            try:
                att_id = int(item) if isinstance(item, (int, str)) and str(item).isdigit() else (item.get('id') if isinstance(item, dict) else None)
                if not att_id: continue
                
                attachment = request.env['ir.attachment'].sudo().browse(int(att_id))
                if not attachment or not attachment.exists(): continue

                # جلب محتوى الملف بأمان (أودو 19 يستخدم raw أو datas)
                file_bytes = attachment.raw or (base64.b64decode(attachment.datas) if attachment.datas else b'')
                if not file_bytes: continue

                mime = attachment.mimetype or ''
                file_name = attachment.name or 'Unknown_File'

                # إذا كان PDF
                if HAS_PDF and 'pdf' in mime:
                    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                    extracted_text += f"\n--- [File: {file_name}] ---\n"
                    for page in reader.pages:
                        extracted_text += page.extract_text() or ''
                        
                # إذا كان ملف نصي (كود، نصوص، الخ)
                elif any(x in mime for x in ['text', 'csv', 'json']):
                    extracted_text += f"\n--- [File: {file_name}] ---\n"
                    extracted_text += file_bytes.decode('utf-8', errors='ignore')
                else:
                    _logger.warning("Unsupported file type for AI text extraction: %s", mime)

            except Exception as e:
                _logger.exception('File extraction failed: %s', e)

        # 2. البرومبت الموجه (لحل الهلوسة مع الملفات)
        system_prompt = "You are a helpful and intelligent AI assistant. If context files are provided, use them to answer the user's question accurately. Do not generate random topics."
        
        if extracted_text:
            final_prompt = f"{system_prompt}\n\n--- FILE CONTEXT ---\n{extracted_text}\n-------------------\n\nUser Question: {prompt}"
        else:
            final_prompt = f"{system_prompt}\n\nUser Question: {prompt}"

        # 3. التأكد من وجود المكتبة والمفتاح
        if not HAS_GENAI:
            return {'response': "Gemini SDK not available. Cannot process request."}

        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            return {'response': "Gemini API key missing in System Parameters."}

        try:
            client = genai.Client(api_key=api_key)
        except Exception as e:
            _logger.exception("Failed to init Gemini client: %s", e)
            return {'response': f"Gemini client initialization error: {e}"}

        # 4. الاتصال مع إعادة المحاولة
        def call_gemini(prompt_text, attempts=3):
            last_exc = None
            for i in range(1, attempts + 1):
                try:
                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[{"role": "user", "parts": [{"text": prompt_text}]}],
                    )
                    # دعم مباشر للردود المتعددة الأشكال
                    return resp.text if hasattr(resp, 'text') else resp.candidates[0].content.parts[0].text
                except Exception as exc:
                    last_exc = exc
                    _logger.warning("Gemini attempt %s failed: %s", i, str(exc))
                    if i < attempts:
                        time.sleep((2 ** (i - 1)) * 0.6 + random.uniform(0, 0.4))
            raise last_exc

        # 5. التنفيذ وإعادة الـ JSON
        try:
            result_text = call_gemini(final_prompt)
            _logger.info("FINAL TEXT SENT TO ODOO: %s", result_text)
            
            return {
                'answer': result_text,
                'response': result_text,
                'message': result_text,
                'status': 'success',
            }
        except Exception as e:
            _logger.exception("Gemini API error: %s", e)
            return {'response': f"AI processing error: {e}"}