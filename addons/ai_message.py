from odoo import models, api, fields

class AIAgentMessage(models.Model):
    _name = "ai.agent.message"
    _description = "AI Agent Message"

    agent_id = fields.Many2one('ai.agent', required=True)
    role = fields.Selection([('user', 'User'), ('assistant', 'Assistant')], required=True)
    body = fields.Html(string="Message Body")

    @api.model
    def create(self, vals):
        record = super().create(vals)

        # Only trigger on user messages
        if record.role == 'user' and record.agent_id:
            # Note: Ensure 'body' is the correct field name in ai.agent.message. It might be 'content'.
            content = vals.get('body') or vals.get('content') or record.body
            record.agent_id._answer_with_rag(content)

        return record
