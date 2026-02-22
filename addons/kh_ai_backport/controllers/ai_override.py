# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
# هنا رجعنا الوراثة الصحيحة اللي كانت بكودك الأصلي
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
        _logger.info('===== GEMINI FINAL FIX ACTIVE =====')

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

                if HAS_PDF and attachment.mimetype == 'application/pdf' and attachment.datas:
                    pdf_data = base64.b64decode(attachment.datas)
                    reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
                    extracted_text += "".join([page.extract_text() or '' for page in reader.pages])
                elif attachment.datas and 'text' in (attachment.mimetype or ''):
                    extracted_text += base64.b64decode(attachment.datas).decode('utf-8', errors='ignore')
            except Exception as e:
                _logger.error('Attachment error: %s', e)

        # 2. البرومبت العام والمختصر
        system_prompt = "You are a helpful, intelligent, and general AI assistant. Answer the user's questions clearly and accurately."
        final_prompt = f"{system_prompt}\n\nContext:\n{extracted_text}\n\nUser: {prompt}" if extracted_text else f"{system_prompt}\n\nUser: {prompt}"

        # 3. جلب الرد من Gemini باستخدام System Parameters
        gemini_text = "Error: AI not processed."
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        
        if HAS_GENAI and api_key:
            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=final_prompt
                )
                gemini_text = getattr(response, "text", str(response))
                _logger.info("FINAL TEXT FROM GEMINI READY")
            except Exception as e:
                _logger.error("Gemini failed: %s", e)
                gemini_text = f"Gemini API Error: {e}"
        else:
            gemini_text = "Gemini SDK or API Key missing."

        # 4. السحر القديم تبعك (لمنع الشاشة البيضاء)
        try:
            # نجعل أودو يجهز القاموس والـ Metadata
            original_response = super(AIControllerOverride, self).generate_response(**kwargs)
            if isinstance(original_response, dict):
                # نستبدل رد أودو برد Gemini
                original_response['answer'] = gemini_text
                return original_response
            return original_response
        except Exception as e:
            _logger.error("Super call failed: %s", e)
            return {'answer': gemini_text, 'status': 'success'}