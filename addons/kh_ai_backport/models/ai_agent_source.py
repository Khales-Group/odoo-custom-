from odoo import models, fields

class AiAgentSource(models.Model):
    _name = 'ai.agent.source'
    _description = 'AI Knowledge Source'

    agent_id = fields.Many2one(
        comodel_name='ai.agent',
        ondelete='cascade',
        required=True
    )
    name = fields.Char()
    status = fields.Selection(
        [('draft', 'Draft'), ('processing', 'Processing'), ('done', 'Done')],
        default='draft',
        string='Source Status'
    )

    def _process_source(self):
        self.status = 'done'
