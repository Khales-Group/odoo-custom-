from odoo import fields, models


class McpChatMessage(models.Model):
    """Persisted turn of the in-system AI chat, one row per Claude
    'messages' entry (role + content), so conversations survive page
    reloads and can be audited like any other MCP activity."""

    _name = "mcp.chat.message"
    _description = "MCP AI Chat Message"
    _order = "id asc"

    user_id = fields.Many2one(
        "res.users", required=True, index=True, ondelete="cascade"
    )
    role = fields.Selection(
        [("user", "User"), ("assistant", "Assistant")], required=True
    )
    content = fields.Text(
        required=True,
        help="JSON-encoded Claude message content (string or list of blocks).",
    )
