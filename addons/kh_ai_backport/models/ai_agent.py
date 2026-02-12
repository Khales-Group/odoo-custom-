from odoo import models, fields, api, _

class AiAgent(models.Model):
    _inherit = 'ai.agent'

    def _process_query(self, query, history=None, attachment_ids=None):
        # ميزة الـ Feedback: إشعار المستخدم بالمراحل
        self._send_ai_status_log(_("Step 1/2: Analyzing sources and attached documents..."))

        file_context = ""
        if attachment_ids:
            attachments = self.env['ir.attachment'].browse(attachment_ids)
            for attach in attachments:
                # أودو 19.0 يقوم بالفهرسة تلقائياً للملفات المدعومة
                text = attach.index_content or ""
                if text:
                    file_context += f"\n[File: {attach.name}]\n{text}\n"

        # دمج محتوى الملفات لتمكين الـ AI من "رؤيتها"
        enhanced_query = f"Context from uploaded files:\n{file_context}\n\nQuestion: {query}" if file_context else query

        self._send_ai_status_log(_("Step 2/2: Generating the final answer..."))
        return super(AiAgent, self)._process_query(enhanced_query, history=history)

    def _send_ai_status_log(self, message):
        for record in self:
            record.message_post(body=message, message_type='notification')

    def action_reprocess_sources(self):
        for source in self.sources_ids:
            source.state = 'processing'
            source._process_source()
        return True
