from odoo import models, api, fields, _
from odoo.exceptions import UserError
import base64
import io
import logging

_logger = logging.getLogger(__name__)

# Safely import the libraries
try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
    _logger.warning("PyPDF2 not installed. PDF processing disabled.")

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False
    _logger.warning("google-genai not installed. Gemini integration disabled.")


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _message_post(self, body='', subject=None, message_type='notification', **kwargs):
        """
        Override message posting to intercept files and send them to Gemini API
        for AI-powered document summarization and Q&A.
        """
        # 1. Post message normally first
        message = super()._message_post(body=body, subject=subject, message_type=message_type, **kwargs)

        # NOTE: Gemini bridge temporarily disabled on discuss.channel to avoid
        # duplicate processing. All AI handling is performed in `ai.agent`.
        return message

    def _extract_pdf_text(self, attachment):
        """Extract text from a PDF attachment."""
        if not HAS_PDF:
            _logger.warning("Gemini Bridge: PyPDF2 not available for PDF extraction")
            return ""
        
        if attachment.mimetype != 'application/pdf':
            _logger.debug(f"Gemini Bridge: Skipping {attachment.name} - not a PDF (mimetype: {attachment.mimetype})")
            return ""
        
        try:
            pdf_data = base64.b64decode(attachment.datas)
            pdf_file = io.BytesIO(pdf_data)
            reader = PyPDF2.PdfReader(pdf_file)
            extracted_text = ""
            page_count = len(reader.pages)
            _logger.info(f"Gemini Bridge: Extracting text from {page_count} pages in {attachment.name}")
            
            for page_num, page in enumerate(reader.pages, 1):
                page_text = page.extract_text() or ""
                extracted_text += page_text
                if page_text:
                    _logger.debug(f"Gemini Bridge: Extracted {len(page_text)} characters from page {page_num}")
            
            _logger.info(f"Gemini Bridge: Total extracted {len(extracted_text)} characters from {attachment.name}")
            return extracted_text
        except Exception as e:
            _logger.error(f"Gemini Bridge: Error extracting PDF text from {attachment.name}: {str(e)}")
            return ""

    def _process_with_gemini(self, extracted_text, user_message, attachment_name=""):
        """Send document to Gemini and post the response."""
        try:
            # Get API key from system parameters (stored securely)
            # Using the same key parameter as AiAgent for unified configuration
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'gemini.api.key'
            )
            
            if not api_key:
                _logger.warning("Gemini Bridge: Gemini API key not configured. Skipping AI processing.")
                self.sudo().message_post(
                    body="⚠️ Gemini API key is not configured. Please contact your administrator.",
                    author_id=self.env.ref('base.partner_root').id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
                return
            
            _logger.info(f"Gemini Bridge: Initializing Gemini client for {attachment_name}")
            client = genai.Client(api_key=api_key)
            from odoo.tools import html2plaintext
            user_prompt = html2plaintext(user_message) if user_message else f'Please summarize the document: {attachment_name}'
            _logger.info(f"Gemini Bridge: User prompt: {user_prompt[:100]}...")
            full_prompt = f"Here is a document ({attachment_name}):\n\n{extracted_text}\n\nBased on this document, answer the following user query: {user_prompt}"
            _logger.info(f"Gemini Bridge: Sending request to Gemini API...")
            
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=full_prompt
            )
            ai_answer = getattr(response, "text", str(response))
            
            _logger.info(f"Gemini Bridge: Received response ({len(ai_answer)} characters) from Gemini")
            
            # Post Gemini's answer back into the chat as OdooBot using sudo() to bypass permissions
            self.sudo().with_context(mail_create_nosubscribe=True).message_post(
                body=ai_answer,
                author_id=self.env.ref('base.partner_root').id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment'  # Ensures it appears as a real chat bubble
            )
            
            _logger.info(f"Gemini Bridge: Successfully processed document in channel {self.id}")
            
        except Exception as e:
            _logger.error(f"Gemini Bridge: API error: {str(e)}", exc_info=True)
            try:
                self.sudo().message_post(
                    body=f"<span style='color: red;'><b>Gemini Error:</b> {str(e)}</span>",
                    author_id=self.env.ref('base.partner_root').id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
            except Exception as post_error:
                _logger.error(f"Gemini Bridge: Failed to post error message: {str(post_error)}")
