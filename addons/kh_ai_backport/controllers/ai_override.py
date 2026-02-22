# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import base64
import io
import logging

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
        _logger.info('===== GEMINI GENERIC CONTROLLER ACTIVE =====')

        prompt = kwargs.get('prompt') or kwargs.get('question') or ''
        attachments = kwargs.get('attachments') or []
        extracted_text = ""

        # 1. استخراج النصوص من المرفقات
        for item in attachments:
            try:
                att_id = int(item) if isinstance(item, (int, str)) and str(item).isdigit() else (item.get('id') if isinstance(item, dict) else None)
                if not att_id: continue
                attachment = request.env['ir.attachment'].sudo().browse(int(att_id))
                if not attachment: continue

                # PDF
                if HAS_PDF and attachment.mimetype == 'application/pdf' and attachment.datas:
                    pdf_data = base64.b64decode(attachment.datas)
                    reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
                    extracted_text += "".join([page.extract_text() or '' for page in reader.pages])
                # Text
                elif attachment.datas and 'text' in (attachment.mimetype or ''):
                    extracted_text += base64.b64decode(attachment.datas).decode('utf-8', errors='ignore')
            except Exception as e:
                _logger.error('Attachment processing failed: %s', e)

        # 2. بناء "برومبت عام" (مساعد ذكي غير مخصص لأودو)
        system_prompt = "You are a helpful, intelligent, and general AI assistant. Answer the user's questions clearly and accurately."
        
        if extracted_text:
            final_prompt = f"{system_prompt}\n\nContext from files:\n{extracted_text}\n\nUser Question: {prompt}"
        else:
            final_prompt = f"{system_prompt}\n\nUser Question: {prompt}"

        if not HAS_GENAI:
            return {'response': "Gemini SDK not available.", 'status': 'error'}

        # 3. جلب الـ API Key من System Parameters
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            return {'response': "Gemini API key missing in System Parameters.", 'status': 'error'}

        # 4. الاتصال المباشر بـ Gemini وإرجاع الرد
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=final_prompt
            )
            
            result_text = getattr(response, "text", str(response))
            _logger.info("FINAL TEXT SENT TO ODOO: %s", result_text)
            
            # إرجاع الرد بالشكل الذي تفهمه واجهة أودو 100%
            return {
                'answer': result_text,
                'response': result_text,
                'status': 'success',
            }

        except Exception as e:
            _logger.exception("Gemini API error: %s", e)
            return {
                'answer': f"AI processing error: {e}",
                'response': f"AI processing error: {e}",
                'status': 'error',
            }