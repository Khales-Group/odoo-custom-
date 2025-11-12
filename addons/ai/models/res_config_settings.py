from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    def _get_default_chatgpt_model(self):
        return self.env.ref('odoo_turbo_ai_agent.chatgpt_model_gpt_3_5_turbo').id

    openapi_api_key = fields.Char(string="API Key", help="Provide the API key here", config_parameter="odoo_turbo_ai_agent.openapi_api_key", required=True)
    chatgpt_model_id = fields.Many2one('chatgpt.model', 'ChatGPT Model', ondelete='cascade', default=_get_default_chatgpt_model,  config_parameter="odoo_turbo_ai_agent.chatgpt_model_id")

    #database fields
    odoodb_host = fields.Char(string="Host", help="Provide the host here", config_parameter="odoo_turbo_ai_agent.odoodb_host")
    odoodb_port = fields.Char(string="Port", help="Provide the port here", config_parameter="odoo_turbo_ai_agent.odoodb_port")
    odoodb_user = fields.Char(string="User", help="Provide the user here", config_parameter="odoo_turbo_ai_agent.odoodb_user")
    odoodb_password = fields.Char(string="Password", help="Provide the password here", config_parameter="odoo_turbo_ai_agent.odoodb_password")
    odoodb_dbname = fields.Char(string="Database Name", help="Provide the database name here", config_parameter="odoo_turbo_ai_agent.odoodb_dbname")
    odoo_user = fields.Char(string="Odoo User", help="Provide the Odoo user here", config_parameter="odoo_turbo_ai_agent.odoo_user")
    odoo_password = fields.Char(string="Odoo Password", help="Provide the Odoo password here", config_parameter="odoo_turbo_ai_agent.odoo_password")
