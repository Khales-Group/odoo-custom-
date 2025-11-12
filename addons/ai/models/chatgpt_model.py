from odoo import fields, models


class ChatGPTModel(models.Model):
    _name = 'chatgpt.model'
    _description = "ChatGPT Model"

    name = fields.Char(string='ChatGPT Model', required=True)



class ChatGPTOdoodb(models.Model):
    _name = 'chatgpt.odoodb'
    _description = "ChatGPT OdooDB"

    #database fields
    odoodb_host = fields.Char(string="Host", help="Provide the host here", config_parameter="odoo_turbo_ai_agent.odoodb_host", required=True)
    odoodb_port = fields.Char(string="Port", help="Provide the port here", config_parameter="odoo_turbo_ai_agent.odoodb_port", required=True)
    odoodb_user = fields.Char(string="User", help="Provide the user here", config_parameter="odoo_turbo_ai_agent.odoodb_user", required=True)
    odoodb_password = fields.Char(string="Password", help="Provide the password here", config_parameter="odoo_turbo_ai_agent.odoodb_password", required=True)
    odoodb_dbname = fields.Char(string="Database Name", help="Provide the database name here", config_parameter="odoo_turbo_ai_agent.odoodb_dbname", required=True)
    odoo_user = fields.Char(string="Odoo User", help="Provide the Odoo user here", config_parameter="odoo_turbo_ai_agent.odoo_user", required=True)
    odoo_password = fields.Char(string="Odoo Password", help="Provide the Odoo password here", config_parameter="odoo_turbo_ai_agent.odoo_password", required=True)