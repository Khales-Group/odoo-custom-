from odoo import models, fields, api

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
