from odoo import models, api

class AIAgentMessage(models.Model):
    _inherit = "ai.agent.message"

    @api.model
    def create(self, vals):
        record = super().create(vals)

        # Only trigger on user messages
        if record.role == 'user' and record.agent_id:
            # Note: Ensure 'body' is the correct field name in ai.agent.message. It might be 'content'.
            content = vals.get('body') or vals.get('content') or record.body
            record.agent_id._answer_with_rag(content)

        return record
