# -*- coding: utf-8 -*-
from odoo import models, api, _
from odoo.exceptions import UserError
import logging
import base64
import io

_logger = logging.getLogger(__name__)

# استيراد المكتبات مع التحقق
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

class AiAgentOverride(models.Model):
    _inherit = 'ai.agent'

    def _execute_query(self, query, history=None, attachment_ids=None, **kwargs):
        """
        نستبدل وظيفة الذكاء الاصطناعي الأصلية لاستخدام Gemini Vertex AI.
        بما أننا داخل الموديل، أودو سيتكفل تلقائياً بحفظ الرسالة وعرضها.
        """
        _logger.info("===== [PROD] VERTEX AI MODEL OVERRIDE START =====")

        # 1. التحقق من وجود المكتبة
        if not HAS_GENAI:
            _logger.warning("Gemini SDK missing. Using standard Odoo AI.")
            return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)

        combined_text = ""

        # 2. معالجة المرفقات (PDF & Text)
        if attachment_ids:
            try:
                # التأكد من أن attachment_ids قائمة أرقام صحيحة
                valid_ids = []
                if isinstance(attachment_ids, list):
                    valid_ids = [int(i) for i in attachment_ids if str(i).isdigit()]
                
                if valid_ids:
                    attachments = self.env['ir.attachment'].sudo().browse(valid_ids)
                    for att in attachments:
                        text = ""
                        # PDF extraction
                        if HAS_PDF and att.mimetype == 'application/pdf' and att.datas:
                            try:
                                reader = PyPDF2.PdfReader(io.BytesIO(base64.b64decode(att.datas)))
                                text = "".join([page.extract_text() or "" for page in reader.pages])
                            except Exception as e:
                                _logger.error(f"PDF Error in {att.name}: {e}")
                        
                        # Text extraction
                        elif att.datas and 'text' in (att.mimetype or ''):
                            try:
                                text = base64.b64decode(att.datas).decode('utf-8', errors='ignore')
                            except Exception:
                                pass
                        
                        if text:
                            combined_text += f"\n--- File: {att.name} ---\n{text}\n"
            except Exception as e:
                _logger.error(f"Error processing attachments: {e}")

        # 3. بناء السؤال النهائي
        final_prompt = f"Context:\n{combined_text}\n\nUser Question: {query}" if combined_text else query

        # 4. الاتصال بـ Vertex AI (باستخدام ملف JSON الخاص بك)
        try:
            client = genai.Client(
                vertexai=True,
                project="gen-lang-client-0937150406",
                location="us-central1",
                credentials_path="/home/odoo/vertex_key.json"
            )
            
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=final_prompt
            )
            
            result_text = response.text
            _logger.info("Gemini Vertex Response Success")
            
            # إرجاع النص فقط. أودو سيفهم هذا النص ويحفظه كرسالة.
            return result_text

        except Exception as e:
            _logger.exception("Vertex AI Failed: %s", e)
            # في حال الفشل، نعود لنظام أودو الأصلي كاحتياط
            return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)