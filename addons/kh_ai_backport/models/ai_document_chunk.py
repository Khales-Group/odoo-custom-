from odoo import models, fields

class AIDocumentChunk(models.Model):
    _name = "ai.document.chunk"
    _description = "AI Document Chunk"

    agent_id = fields.Many2one("ai.agent", ondelete="cascade", string="Agent")
    content = fields.Text(string="Content")
    embedding = fields.Binary(string="Embedding")
