from odoo import models, fields, api, _
import logging
import base64
import io

_logger = logging.getLogger(__name__)

# Try to import Gemini SDK
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# Try to import PDF support
try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


class AiAgent(models.Model):
    _inherit = 'ai.agent'

    # Define custom fields for this agent
    status = fields.Selection([
        ('idle', 'Idle'),
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('error', 'Error')
    ], default='idle', string='Status')

    chunk_ids = fields.One2many(
        comodel_name='ai.document.chunk',
        inverse_name='agent_id',
        string='Document Chunks'
    )

    knowledge_source_ids = fields.One2many(
        comodel_name='ai.agent.source',
        inverse_name='agent_id',
        string="Knowledge Sources"
    )

    partner_id = fields.Many2one('res.partner', string="Partner")

    def _execute_query(self, query, history=None, attachment_ids=None, **kwargs):
        """
        هذه هي الدالة 'الأم' في أودو 19 التي يناديها الـ Controller مباشرة.
        إذا نجحنا في اعتراضها هنا، فقد سيطرنا على الـ AI بالكامل.
        """
        _logger.info("===== [FORCE DEBUG] تم اختراق تنفيذ الـ AI بنجاح! =====")

        if attachment_ids:
            # إذا وجدنا ملفات، نلغي كل منطق أودو ونستخدم جيمناي
            _logger.info(f"===== [FORCE DEBUG] جاري معالجة {len(attachment_ids)} ملفات =====")

            # استدعاء جسر جيمناي الخاص بك
            combined_text = ""
            attachments = self.env['ir.attachment'].sudo().browse(attachment_ids)
            for attach in attachments:
                text = self._extract_pdf_text(attach) or self._extract_text(attach)
                if text:
                    combined_text += f"\n[Document: {attach.name}]\n{text}\n"

            if combined_text:
                _logger.info("===== [FORCE DEBUG] جاري استدعاء Gemini =====")
                prompt = f"Context from files:\n{combined_text}\n\nUser Question: {query}"
                answer = self._ask_gemini(prompt)
                if answer:
                    _logger.info("===== [FORCE DEBUG] تم استقبال الرد من Gemini =====")
                    return answer

        # إذا لم توجد ملفات، نترك أودو يكمل عمله الأصلي
        _logger.info("===== [FORCE DEBUG] لا توجد ملفات، نعود للنظام الأصلي =====")
        return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)


    def _extract_text(self, attachment):
        """Extract text from plain text files."""
        if not attachment:
            return ""

        # Prefer indexed content
        if attachment.index_content:
            return attachment.index_content

        # Try decoding from base64
        if attachment.datas and attachment.mimetype == 'text/plain':
            try:
                return base64.b64decode(attachment.datas).decode('utf-8', errors='ignore')
            except Exception:
                return ""

        return ""

    def _extract_pdf_text(self, attachment):
        """Extract text from PDF using PyPDF2."""
        if not HAS_PDF or attachment.mimetype != 'application/pdf':
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
            _logger.error(f"===== [FORCE DEBUG] PDF extraction failed: {str(e)} =====")
            return ""

    def _ask_gemini(self, prompt):
        """Call Gemini API using google-genai SDK."""
        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        if not api_key:
            _logger.error("===== [FORCE DEBUG] API key not configured =====")
            return "API key not configured."

        try:
            _logger.info("===== [FORCE DEBUG] Initializing Gemini client =====")
            client = genai.Client(api_key=api_key)

            _logger.info("===== [FORCE DEBUG] Sending request to Gemini =====")
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )

            result = response.text
            _logger.info(f"===== [FORCE DEBUG] Received response: {len(result)} chars =====")
            return result

        except Exception as e:
            _logger.error(f"===== [FORCE DEBUG] Gemini API error: {str(e)} =====")
            return f"Gemini error: {e}"

