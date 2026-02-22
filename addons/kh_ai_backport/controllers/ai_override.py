# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.ai.controllers.main import AIController
import base64
import io
import logging
import time
import random

_logger = logging.getLogger(__name__)

# التحقق من وجود المكتبات اللازمة لضمان عدم توقف السيرفر
try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        """
        تجاوز دالة أودو الأصلية لتوجيه الطلب إلى Gemini عبر Vertex AI.
        """
        _logger.info('===== [PROD] GEMINI VERTEX AI OVERRIDE START =====')

        # 1. استخراج السؤال والمرفقات
        prompt = kwargs.get('prompt') or kwargs.get('question') or ''
        attachments_ids = kwargs.get('attachments') or []
        extracted_text = ''

        # 2. معالجة الملفات المرفقة واستخراج النصوص منها
        if attachments_ids:
            try:
                # تحويل المعرفات إلى أرقام صحيحة والبحث عنها في المرفقات
                ids = [int(i) for i in attachments_ids if str(i).isdigit()]
                attachments = request.env['ir.attachment'].sudo().browse(ids)
                
                for att in attachments:
                    if not att.datas:
                        continue
                        
                    # استخراج نص من ملفات PDF
                    if HAS_PDF and att.mimetype == 'application/pdf':
                        try:
                            pdf_data = base64.b64decode(att.datas)
                            reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
                            text = "".join([page.extract_text() or '' for page in reader.pages])
                            extracted_text += f"\n--- Content of {att.name} ---\n{text}\n"
                        except Exception as e:
                            _logger.error("Failed to parse PDF %s: %s", att.name, e)
                            
                    # استخراج نص من ملفات Text
                    elif 'text' in (att.mimetype or ''):
                        try:
                            text = base64.b64decode(att.datas).decode('utf-8', errors='ignore')
                            extracted_text += f"\n--- Content of {att.name} ---\n{text}\n"
                        except Exception as e:
                            _logger.error("Failed to parse text file %s: %s", att.name, e)
            except Exception as e:
                _logger.error("Error processing attachments: %s", e)

        # 3. بناء الـ Prompt النهائي مع السياق المستخرج
        final_prompt = f"System: You are an Odoo 19 expert. Use the following context to answer:\n{extracted_text}\n\nUser Question: {prompt}" if extracted_text else prompt

        # 4. التحقق من جاهزية المكتبة (Fallback Plan)
        if not HAS_GENAI:
            _logger.warning('Google GenAI SDK not installed. Falling back to default controller.')
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # 5. الاتصال بـ Vertex AI مع نظام إعادة المحاولة (Retry Logic)
        def call_gemini():
            # إعداد العميل باستخدام ملف الـ JSON الذي رفعته
            client = genai.Client(
                vertexai=True,
                project="gen-lang-client-0937150406",
                location="us-central1",
                credentials_path="/home/odoo/vertex_key.json"
            )
            
            # تنفيذ الطلب
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=final_prompt
            )
            return response.text

        # تنفيذ الطلب مع محاولات إعادة في حال حدوث خطأ عابر
        attempts = 3
        for i in range(attempts):
            try:
                result_text = call_gemini()
                _logger.info("Gemini response generated successfully.")
                
                # إرجاع الرد بالصيغة التي تتوقعها واجهة أودو 19
                return {
                    'answer': result_text,
                    'status': 'success',
                }
            except Exception as e:
                _logger.warning("Attempt %s failed: %s", i + 1, e)
                if i < attempts - 1:
                    time.sleep(1 * (i + 1)) # تأخير تصاعدي بسيط
                else:
                    _logger.error("All Gemini attempts failed. Falling back to original controller.")
                    # إذا فشل كل شيء، نعود للنظام الأصلي
                    return super(AIControllerOverride, self).generate_response(**kwargs)