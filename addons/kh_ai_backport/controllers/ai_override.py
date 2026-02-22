# -*- coding: utf-8 -*-
from odoo import models, api, _
import logging
import base64
import io

_logger = logging.getLogger(__name__)

# التحقق من وجود المكتبة
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# التحقق من وجود مكتبة PDF
try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

class AiAgentOverride(models.Model):
    _inherit = 'ai.agent'

    def _execute_query(self, query, history=None, attachment_ids=None, **kwargs):
        """
        استبدال منطق الذكاء الاصطناعي لاستخدام Gemini عبر API Key فقط.
        """
        
        # 1. إذا لم تكن المكتبة موجودة، ارجع لنظام أودو الأصلي
        if not HAS_GENAI:
            return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)

        # 2. جلب الـ API Key من إعدادات النظام
        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        
        # إذا لم يوجد مفتاح، ارجع لنظام أودو الأصلي
        if not api_key:
            _logger.warning("Gemini API Key not found in System Parameters.")
            return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)

        _logger.info("===== GEMINI API KEY MODE ACTIVE =====")

        combined_text = ""
        
        # 3. معالجة المرفقات (اختياري، لزيادة الذكاء)
        if attachment_ids:
            try:
                # التعامل مع IDs سواء كانت قائمة أو رقم مفرد
                ids_to_browse = []
                if isinstance(attachment_ids, list):
                    ids_to_browse = [int(i) for i in attachment_ids if str(i).isdigit()]
                elif isinstance(attachment_ids, int):
                    ids_to_browse = [attachment_ids]
                
                if ids_to_browse:
                    attachments = self.env['ir.attachment'].sudo().browse(ids_to_browse)
                    for att in attachments:
                        file_content = ""
                        # PDF
                        if HAS_PDF and att.mimetype == 'application/pdf' and att.datas:
                            try:
                                reader = PyPDF2.PdfReader(io.BytesIO(base64.b64decode(att.datas)))
                                file_content = "".join([page.extract_text() or "" for page in reader.pages])
                            except Exception: pass
                        # Text
                        elif att.datas and 'text' in (att.mimetype or ''):
                            try:
                                file_content = base64.b64decode(att.datas).decode('utf-8', errors='ignore')
                            except Exception: pass
                        
                        if file_content:
                            combined_text += f"\n--- File: {att.name} ---\n{file_content}\n"
            except Exception as e:
                _logger.error(f"Attachment processing error: {e}")

        # 4. تجهيز النص النهائي
        final_prompt = f"Context:\n{combined_text}\n\nUser Question: {query}" if combined_text else query

        # 5. الاتصال بـ Gemini
        try:
            # تهيئة العميل بالمفتاح فقط
            client = genai.Client(api_key=api_key)
            
            # طلب الرد (يمكنك تغيير الموديل إلى gemini-1.5-flash إذا أردت)
            response = client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=final_prompt
            )
            
            result_text = response.text
            _logger.info("Gemini Response Received Successfully")
            
            # إرجاع النص فقط (أودو سيتولى عرضه في الشاشة)
            return result_text

        except Exception as e:
            _logger.exception("Gemini API Error: %s", e)
            # في حال حدوث خطأ (مثل 429)، العودة لنظام أودو الأصلي بدلاً من التوقف
            return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)