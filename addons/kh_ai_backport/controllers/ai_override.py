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

# Gemini SDK (google-generativeai)
try:
    import google.generativeai as genai
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

        # Get API key: prefer odoo.conf (gemini_api_key), fall back to system parameter
        from odoo.tools import config
        api_key = config.get('gemini_api_key') or request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            _logger.warning('Gemini API key missing; falling back to original controller')
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # Try SDK invocation compatible with either google-genai (genai.Client)
        # or google-generativeai (genai.GenerativeModel).
        try:
            if hasattr(genai, 'Client'):
                # google-genai style
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=final_prompt,
                )
                text = response.text
                return {'response': text}

            elif hasattr(genai, 'configure'):
                # google-generativeai style
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash-latest')
                response = model.generate_content(final_prompt)
                text = response.text
                return {'response': text}

            else:
                _logger.error('Gemini SDK present but unsupported API surface')
                return super(AIControllerOverride, self).generate_response(**kwargs)

        except Exception as e:
            _logger.exception('Gemini API error: %s', e)
            return super(AIControllerOverride, self).generate_response(**kwargs)
