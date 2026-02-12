from odoo import models, fields, api, _

class AiAgent(models.Model):
    _inherit = 'ai.agent'

    def _get_system_prompt(self):
        """
        تعديل الـ System Prompt لتمكين العميل من فهم الفلترة الزمنية يدوياً
        كما في نسخة 19.1.
        """
        prompt = super(AiAgent, self)._get_system_prompt()
        time_logic = (
            "\n\n[TIME FILTERING LOGIC]: If the user asks for records in a specific timeframe "
            "(e.g., 'last week', 'this quarter'), you must use your search tools with a domain "
            "filter on 'create_date' or 'date_order'. Translate 'last week' into the specific "
            "dates relative to Today."
        )
        return prompt + time_logic

    def action_reprocess_sources(self):
        """
        دالة يدوية لإعادة فهرسة المصادر (Backport من 19.1)
        """
        for source in self.sources_ids:
            # إعادة حالة المصدر إلى "قيد المعالجة"
            source.state = 'processing' 
            # استدعاء دالة المعالجة الأصلية الموجودة في 19.0
            source._process_source() 
        return True

    def _execute_query_with_feedback(self, query):
        """
        تنفيذ الاستعلام مع إظهار مراحل العمل (Backport من 19.1)
        """
        # المرحلة 1: إبلاغ المستخدم ببداية البحث
        self._log_ai_status(_("Step 1/3: Searching knowledge sources..."))
        
        # المرحلة 2: تحليل البيانات المستخرجة
        # (هنا يتم استدعاء المنطق الأصلي لـ 19.0)
        result = self._process_query(query)
        
        # المرحلة 3: صياغة الإجابة النهائية
        self._log_ai_status(_("Step 3/3: Drafting final response..."))
        
        return result

    def _log_ai_status(self, message):
        # إرسال ملاحظة مؤقتة في الـ Chatter ليراها المستخدم
        for record in self:
            record.message_post(body=message, message_type='notification')

    def _process_query(self, query, history=None, attachment_ids=None):
        """
        توسيع دالة المعالجة لدعم قراءة الملفات المرسلة لحظياً (Backport من 19.1)
        """
        file_context = ""
        if attachment_ids:
            attachments = self.env['ir.attachment'].browse(attachment_ids)
            for attach in attachments:
                # استخراج النص المستخلص تلقائياً بواسطة أودو
                text = attach.index_content or ""
                if text:
                    file_context += f"\n[Document: {attach.name}]\n{text}\n"

        # إذا وُجد نص من الملفات، نقوم بدمجه في السؤال الموجه للـ AI
        if file_context:
            enhanced_query = f"Context from attached files:\n{file_context}\n\nQuestion: {query}"
        else:
            enhanced_query = query

        return super(AiAgent, self)._process_query(enhanced_query, history=history)

    def _get_recent_attachments(self):
        """
        البحث عن آخر مرفق تم رفعه في جلسة الشات الحالية
        """
        messages = self.message_ids.sorted('create_date', reverse=True)
        for message in messages:
            if message.attachment_ids:
                return message.attachment_ids.ids
        return []
