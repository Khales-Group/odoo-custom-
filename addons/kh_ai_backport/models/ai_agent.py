from odoo import models, fields, api, _
import logging
import base64
import io

_logger = logging.getLogger(__name__)

# محاولة استيراد المكتبات لضمان استقرار السيرفر
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


class AiAgent(models.Model):
    _inherit = 'ai.agent'

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

    def action_reprocess_sources(self):
        """
        Action triggered by the 'Reprocess Sources' button.
        """
        # TODO: Implement logic to reprocess knowledge sources (e.g. re-index vector store)
        return True

    def _execute_query(self, query, history=None, attachment_ids=None, **kwargs):
        """
        هذه هي الدالة الأساسية في أودو 19. اعتراضها هنا يضمن السيطرة على الرد.
        """
        _logger.info("===== [DEBUG] AI EXECUTION TRIGGERED =====")

        if attachment_ids and HAS_GENAI:
            _logger.info(f"===== [DEBUG] Intercepting {len(attachment_ids)} files for Gemini =====")
            
            combined_text = ""
            # جلب الملفات المرفقة
            attachments = self.env['ir.attachment'].sudo().browse(attachment_ids)
            for attach in attachments:
                text = ""
                # محاولة استخراج النص من PDF
                if HAS_PDF and attach.mimetype == 'application/pdf':
                    text = self._extract_pdf_text(attach)
                
                # محاولة استخراج النص إذا كان ملف نصي عادي
                if not text:
                    text = self._extract_text(attach)
                
                if text:
                    combined_text += f"\n[File: {attach.name}]\n{text}\n"

            if combined_text:
                _logger.info("===== [DEBUG] Sending Document context to Gemini 2.0 Flash =====")
                prompt = f"Using this document content, answer the user query accurately:\n{combined_text}\n\nUser Question: {query}"
                answer = self._ask_gemini(prompt)
                
                if answer:
                    _logger.info("===== [DEBUG] Gemini response received successfully =====")
                    return answer

        # العودة لنظام أودو الأصلي في حال عدم وجود مرفقات أو فشل الجسر
        return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)

    def _extract_text(self, attachment):
        if not attachment: return ""
        if attachment.index_content: return attachment.index_content
        if attachment.datas and attachment.mimetype == 'text/plain':
            try:
                return base64.b64decode(attachment.datas).decode('utf-8', errors='ignore')
            except Exception: return ""
        return ""

    def _extract_pdf_text(self, attachment):
        if not HAS_PDF or attachment.mimetype != 'application/pdf': return ""
        try:
            pdf_data = base64.b64decode(attachment.datas)
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
            return "".join([page.extract_text() or "" for page in reader.pages])
        except Exception as e:
            _logger.error(f"PDF Extraction failed: {e}")
            return ""

    def _ask_gemini(self, prompt):
        # تأكد من استخدام نفس المفتاح المعرف في السيستم
        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            return "Error: Gemini API key is missing in System Parameters."
        try:
            # Configure the SDK and call the Client API (using API key only)
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
            )
            try:
                return response.candidates[0].content.parts[0].text
            except Exception:
                _logger.error("Gemini returned unexpected structure: %s", response)
                return "AI returned empty response."
        except Exception as e:
            _logger.error("Gemini API Call failed: %s", e, exc_info=True)
            # تمييز خطأ الموارد (مثلاً quota) لتسهيل التشخيص
            return f"Gemini connection error: {e}"
