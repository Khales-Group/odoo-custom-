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


class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'

    # 🛠️ نقوم بتعريف الحقل مرة أخرى مع تزويده بالخيارات التي يطلبها أودو
    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text')
    ], string='Source Type', required=True, default='file')


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
        الاعتراض هنا يضمن أن أودو سيأخذ النص الذي نعيده،
        ويقوم هو بإنشاء فقاعة الدردشة في واجهة المستخدم تلقائياً.
        """
        _logger.info("===== [PROD] GEMINI AI MODEL OVERRIDE TRIGGERED =====")

        if not HAS_GENAI:
            _logger.warning("Gemini SDK not found. Falling back to default Odoo AI.")
            return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)

        combined_text = ""

        # 1. معالجة المرفقات (إن وجدت)
        if attachment_ids:
            attachments = self.env['ir.attachment'].sudo().browse(attachment_ids)
            for att in attachments:
                text = ""
                # PDF
                if HAS_PDF and att.mimetype == 'application/pdf' and att.datas:
                    try:
                        reader = PyPDF2.PdfReader(io.BytesIO(base64.b64decode(att.datas)))
                        text = "".join([page.extract_text() or "" for page in reader.pages])
                    except Exception as e:
                        _logger.error("PDF parsing error: %s", e)
                # Text
                elif att.datas and 'text' in (att.mimetype or ''):
                    try:
                        text = base64.b64decode(att.datas).decode('utf-8', errors='ignore')
                    except Exception:
                        pass
                
                if text:
                    combined_text += f"\n[File: {att.name}]\n{text}\n"

        # 2. تجهيز السؤال النهائي
        final_prompt = f"System: Use context to answer precisely.\nContext:\n{combined_text}\n\nUser: {query}" if combined_text else query

        try:
            # استخدام API Key الموجود في الإعدادات لضمان العمل على ويندوز
            api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
            if not api_key:
                _logger.warning("Gemini API Key missing.")
                return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)

            client = genai.Client(api_key=api_key)
            
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=final_prompt
            )
            
            _logger.info("Gemini response generated successfully.")
            # إرجاع النص مباشرة! أودو سيتكفل بعرضه في الشاشة كرسالة
            return getattr(response, "text", str(response))

        except Exception as e:
            _logger.error("Gemini Call Failed: %s", e)
            # إذا تعطلت جوجل لسبب ما، نعود للذكاء الاصطناعي الافتراضي لأودو
            return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)
