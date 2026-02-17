# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.ai.controllers.main import AIController

import base64
import io
import logging

_logger = logging.getLogger(__name__)

# Optional PDF reader
try:
    import PyPDF2
    HAS_PDF = True
except Exception:
    HAS_PDF = False

# Gemini SDK (google-genai)
try:
    from google import genai
    import google
    HAS_GENAI = True
except Exception:
    HAS_GENAI = False


class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user')
    def generate_response(self, **kwargs):
        _logger.info('===== GEMINI OVERRIDE ACTIVE =====')

        prompt = kwargs.get('prompt') or kwargs.get('question') or ''
        attachments = kwargs.get('attachments') or []

        extracted_text = ''
        # attachments may be list of ids or dicts
        for item in attachments:
            try:
                att_id = int(item) if isinstance(item, (int, str)) and str(item).isdigit() else (item.get('id') if isinstance(item, dict) else None)
            except Exception:
                att_id = None
            if not att_id:
                continue
            attachment = request.env['ir.attachment'].sudo().browse(int(att_id))
            if not attachment:
                continue
            # PDF extraction
            if HAS_PDF and attachment.mimetype == 'application/pdf' and attachment.datas:
                try:
                    pdf_data = base64.b64decode(attachment.datas)
                    reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
                    for page in reader.pages:
                        extracted_text += page.extract_text() or ''
                except Exception as e:
                    _logger.exception('PDF extraction failed: %s', e)
            # plain text
            if not extracted_text and attachment.datas and attachment.mimetype == 'text/plain':
                try:
                    extracted_text = base64.b64decode(attachment.datas).decode('utf-8', errors='ignore')
                except Exception:
                    extracted_text = ''

        # Build final prompt
        final_prompt = f"""
You are an expert Odoo 19 Enterprise ERP consultant.
You solve technical, functional, HR, accounting and development issues.

Use the following document content if provided:
{extracted_text}

User question:
{prompt}

Give a precise, professional answer.
"""

        # If Gemini not available, fallback to super
        if not HAS_GENAI:
            _logger.warning('Gemini SDK not available; falling back to original controller')
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # Use new google-genai SDK (Client)
        try:
            _logger.info("GOOGLE PACKAGE PATH: %s", google.__file__)
            
            # Vertex AI Configuration
            key_path = "/home/odoo/vertex_key.json"
            client = genai.Client(
                vertexai=True,
                project="gen-lang-client-0937150406", # تم استخراجه من الملف الذي أرفقته
                location="us-central1",
                credentials_path=key_path # هنا حددنا الملف مباشرة بدون الحاجة لمتغيرات بيئة
            )
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=final_prompt,
            )
            text = getattr(response, "text", str(response))
            return {'response': text}

        except Exception as e:
            _logger.exception('Gemini API error: %s', e)
            return super(AIControllerOverride, self).generate_response(**kwargs)
