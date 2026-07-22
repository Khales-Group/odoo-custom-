from odoo import fields, models


class McpChatConversation(models.Model):
    """One AI chat thread. Grouping messages this way lets a user keep
    several separate conversations, like Claude.ai's chat history sidebar."""

    _name = "mcp.chat.conversation"
    _description = "MCP AI Chat Conversation"
    _order = "last_message_date desc, id desc"

    user_id = fields.Many2one(
        "res.users", required=True, index=True, ondelete="cascade"
    )
    name = fields.Char(default="New chat", required=True)
    last_message_date = fields.Datetime(default=fields.Datetime.now, index=True)
    message_ids = fields.One2many("mcp.chat.message", "conversation_id")
