# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.ai.controllers.main import AIController
import base64
import io
import logging

_logger = logging.getLogger(__name__)

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
        _logger.info('===== GEMINI DEFINITIVE FIX =====')

        prompt = kwargs.get('prompt') or kwargs.get('question') or ''
        attachments = kwargs.get('attachments') or []
        extracted_text = ""

        # 1. استخراج المرفقات
        for item in attachments:
            try:
                att_id = int(item) if isinstance(item, (int, str)) and str(item).isdigit() else (item.get('id') if isinstance(item, dict) else None)
                if not att_id: continue
                attachment = request.env['ir.attachment'].sudo().browse(att_id)
                if not attachment: continue

                if HAS_PDF and attachment.mimetype == 'application/pdf' and attachment.datas:
                    pdf_data = base64.b64decode(attachment.datas)
                    reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
                    extracted_text += "".join([page.extract_text() or '' for page in reader.pages])
                elif attachment.datas and 'text' in (attachment.mimetype or ''):
                    extracted_text += base64.b64decode(attachment.datas).decode('utf-8', errors='ignore')
            except Exception as e:
                _logger.error('Attachment error: %s', e)

        # 2. برومبت المساعد العام
        system_prompt = "You are a helpful, intelligent, and general AI assistant. Answer the user's questions clearly and accurately."
        final_prompt = f"{system_prompt}\n\nContext:\n{extracted_text}\n\nUser: {prompt}" if extracted_text else f"{system_prompt}\n\nUser: {prompt}"

        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        
        # إذا مافي API Key أو SDK، نرجع لأودو كاحتياط
        if not HAS_GENAI or not api_key:
            _logger.warning("Missing GenAI SDK or API Key. Falling back to Odoo AI.")
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # 3. الاتصال بـ Gemini (الصافي)
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=final_prompt
            )
            gemini_text = getattr(response, "text", str(response))
            _logger.info("FINAL TEXT FROM GEMINI READY")
            
            # السر الحقيقي هنا: نعيد القاموس بالاسم 'response' وبدون استخدام super() أبداً!
            return {'response': gemini_text}
            
        except Exception as e:
            _logger.error("Gemini failed: %s", e)
            # ما نستدعي super إلا لو جوجل فصلت أو الـ API Key خلص رصيده
            return super(AIControllerOverride, self).generate_response(**kwargs)