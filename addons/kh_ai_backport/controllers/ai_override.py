# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.ai.controllers.main import AIController

import base64
import io
import logging
import time, random

_logger = logging.getLogger(__name__)

# Optional PDF reader
try:
    import PyPDF2
    HAS_PDF = True
except Exception:
    HAS_PDF = False

# google-genai SDK
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

        # If Gemini SDK not available, fallback
        if not HAS_GENAI:
            _logger.warning('Gemini SDK not available; falling back to original controller')
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # Get API key from System Parameters
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            _logger.warning('Gemini API key missing; falling back to original controller')
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # Initialize google-genai client (Odoo.sh: use API key only)
        try:
            _logger.info("GOOGLE PACKAGE PATH: %s", getattr(google, "__file__", "unknown"))
            client = genai.Client(api_key=api_key)
        except Exception as e:
            _logger.exception("Failed to init genai client: %s", e)
            return super(AIControllerOverride, self).generate_response(**kwargs)

        # small retry wrapper for transient errors (quota spikes)
        def call_with_retries(client, prompt, attempts=3):
            last_exc = None
            for i in range(1, attempts + 1):
                try:
                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[{"role": "user", "parts": [{"text": prompt}]}],
                    )
                    try:
                        return resp.candidates[0].content.parts[0].text
                    except Exception:
                        _logger.error("Gemini returned unexpected structure: %s", resp)
                        return "AI returned empty response."
                except Exception as exc:
                    last_exc = exc
                    _logger.warning("Gemini attempt %s failed: %s", i, str(exc))
                    if i < attempts:
                        time.sleep((2 ** (i - 1)) * 0.6 + random.uniform(0, 0.4))
            raise last_exc

        try:
            result_text = call_with_retries(client, final_prompt)
            return {'response': result_text}
        except Exception as e:
            _logger.exception('Gemini API error: %s', e)
            return {'response': "AI processing is temporarily unavailable. Please try again later or contact an administrator."}
