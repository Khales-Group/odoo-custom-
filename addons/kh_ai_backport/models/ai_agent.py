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
