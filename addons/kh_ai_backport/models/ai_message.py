from odoo import models, api

class AIConversationMessage(models.Model):
    _inherit = "ai.conversation.message"

    @api.model
    def create(self, vals):
        record = super().create(vals)

        # Only trigger on user messages
        if record.role == 'user' and record.agent_id:
            record.agent_id._answer_with_rag(record.body)

        return record
