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

        # 2. DEBUG LOG: Track if the bridge is being called
        _logger.info(f"Gemini Bridge: Intercepted message in channel '{self.name}' with author '{message.author_id.name}'")

        # 3. Skip notifications (system messages)
        if message_type == 'notification':
            _logger.debug(f"Gemini Bridge: Skipping notification message in channel '{self.name}'")
            return message
        
        # 4. Only process messages from real users (not bots/share accounts)
        # Check: author should not be a sharing partner
        if message.author_id.partner_share:
            _logger.debug(f"Gemini Bridge: Skipping share user message in channel '{self.name}'")
            return message
        
        # 5. Skip if author is the system/root user
        system_user_id = self.env.ref('base.partner_root').id
        if message.author_id.id == system_user_id:
            _logger.debug(f"Gemini Bridge: Skipping system user message in channel '{self.name}'")
            return message

        # 6. Process attachments if present
        if message.attachment_ids:
            _logger.info(f"Gemini Bridge: Found {len(message.attachment_ids)} attachment(s) in channel '{self.name}'")
            
            # Process the first valid document found
            for idx, attachment in enumerate(message.attachment_ids):
                _logger.info(f"Gemini Bridge: Processing attachment {idx+1}: {attachment.name} ({attachment.mimetype})")
                
                extracted_text = self._extract_pdf_text(attachment)
                
                # If not a PDF, try to extract plain text
                if not extracted_text and attachment.mimetype == 'text/plain':
                    try:
                        extracted_text = base64.b64decode(attachment.datas).decode('utf-8', errors='ignore')
                        _logger.info(f"Gemini Bridge: Successfully extracted text from {attachment.name}")
                    except Exception as e:
                        _logger.error(f"Gemini Bridge: Error decoding text file {attachment.name}: {str(e)}")
                        continue

                # 7. Call Gemini API if we have content and Gemini is configured
                if HAS_GENAI and extracted_text:
                    _logger.info(f"Gemini Bridge: Starting Gemini processing for {attachment.name}")
                    self._process_with_gemini(extracted_text, body, attachment.name)
                    break  # Process only the first valid document
                else:
                    if not extracted_text:
                        _logger.warning(f"Gemini Bridge: No text extracted from {attachment.name}")
                    if not HAS_GENAI:
                        _logger.warning(f"Gemini Bridge: Gemini not available (HAS_GENAI=False)")

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
            
            # Initialize Gemini client with the new google-genai SDK
            client = genai.Client(api_key=api_key)
            
            # Clean up HTML tags from Odoo's chat body
            from odoo.tools import html2plaintext
            user_prompt = html2plaintext(user_message) if user_message else f'Please summarize the document: {attachment_name}'
            
            _logger.info(f"Gemini Bridge: User prompt: {user_prompt[:100]}...")
            
            # Combine the document text and the user's question
            full_prompt = f"Here is a document ({attachment_name}):\n\n{extracted_text}\n\nBased on this document, answer the following user query: {user_prompt}"
            
            # Get the answer from Gemini using the new SDK
            _logger.info(f"Gemini Bridge: Sending request to Gemini API...")
            response = client.models.generate_content(
                model='gemini-2.0-flash',  # Using the latest flash model
                contents=full_prompt
            )
            ai_answer = response.text
            
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
