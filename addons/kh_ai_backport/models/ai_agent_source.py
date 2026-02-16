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
    
    # Required field for native Odoo 19 AI logic (garbage collection cron job)
    attachment_id = fields.Many2one(
        comodel_name='ir.attachment',
        string='Attachment',
        help='Document attachment associated with this knowledge source'
    )

    def _process_source(self):
        self.status = 'done'
