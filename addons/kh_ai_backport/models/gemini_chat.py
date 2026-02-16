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
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False
    _logger.warning("google-generativeai not installed. Gemini integration disabled.")


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _message_post(self, body='', subject=None, message_type='notification', **kwargs):
        """
        Override message posting to intercept PDFs and send them to Gemini API
        for AI-powered document summarization and Q&A.
        """
        # 1. Let Odoo post the user's message and attachment normally first
        message = super()._message_post(body=body, subject=subject, message_type=message_type, **kwargs)

        # 2. Check if we should trigger the AI (avoid infinite loops from AI replying to itself)
        # Only process if the message is from a real user (not the system user)
        system_user_id = self.env.ref('base.partner_root').id
        if message.author_id.id != system_user_id:
            
            # 3. Check if the user uploaded an attachment
            if message.attachment_ids:
                attachment = message.attachment_ids[0]
                
                # 4. Extract Text if it's a PDF
                extracted_text = self._extract_pdf_text(attachment)
                
                # 5. Call Gemini API if we have a PDF and Gemini is configured
                if HAS_GENAI and extracted_text:
                    self._process_with_gemini(extracted_text, body)

        return message

    def _extract_pdf_text(self, attachment):
        """Extract text from a PDF attachment."""
        if not HAS_PDF:
            return ""
        
        if attachment.mimetype != 'application/pdf':
            return ""
        
        try:
            pdf_data = base64.b64decode(attachment.datas)
            pdf_file = io.BytesIO(pdf_data)
            reader = PyPDF2.PdfReader(pdf_file)
            extracted_text = ""
            for page in reader.pages:
                extracted_text += page.extract_text() or ""
            return extracted_text
        except Exception as e:
            _logger.error(f"Error extracting PDF text: {str(e)}")
            return ""

    def _process_with_gemini(self, extracted_text, user_message):
        """Send document to Gemini and post the response."""
        try:
            # Get API key from system parameters (stored securely)
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'kh_ai_backport.gemini_api_key'
            )
            
            if not api_key:
                _logger.warning("Gemini API key not configured. Skipping AI processing.")
                self.message_post(
                    body="⚠️ Gemini API key is not configured. Please contact your administrator.",
                    author_id=self.env.ref('base.partner_root').id,
                    message_type='comment'
                )
                return
            
            # Configure Gemini
            genai.configure(api_key=api_key)
            
            # Using Flash because it is blazing fast and cheap
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            # Clean up HTML tags from Odoo's chat body
            from odoo.tools import html2plaintext
            user_prompt = html2plaintext(user_message) if user_message else 'Please summarize this document.'
            
            # Combine the PDF text and the user's question
            full_prompt = f"Here is a document:\n\n{extracted_text}\n\nBased on this document, answer the following user query: {user_prompt}"
            
            # Get the answer from Gemini
            response = model.generate_content(full_prompt)
            ai_answer = response.text
            
            # 6. Post Gemini's answer back into the chat as OdooBot
            self.with_context(mail_create_nosubscribe=True).message_post(
                body=ai_answer,
                author_id=self.env.ref('base.partner_root').id,
                message_type='comment'
            )
            
            _logger.info(f"Successfully processed document with Gemini in channel {self.id}")
            
        except Exception as e:
            _logger.error(f"Gemini API error: {str(e)}")
            self.message_post(
                body=f"<span style='color: red;'><b>Gemini Error:</b> {str(e)}</span>",
                author_id=self.env.ref('base.partner_root').id,
                message_type='comment'
            )
