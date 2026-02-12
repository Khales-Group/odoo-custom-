from odoo import models, api

class AIMessage(models.Model):
    _inherit = "ai.message"

    @api.model
    def create(self, vals):
        record = super().create(vals)

        if record.role == 'user':
            record.agent_id._answer_with_rag(record.message)

        return record
