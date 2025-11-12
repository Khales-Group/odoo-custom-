{
    'name': 'Odoo Turbo AI Agent 🚀',
    'version': '1.1.3',
    'license': 'GPL-3',
    'summary': 'Odoo OpenAI Chatbot Integration with AI Agent',
    'description': 'The Odoo OpenAI Chatbot Integration with AI Agent fuses advanced AI with the robust Odoo ERP system. Utilizing OpenAIs natural language processing, it streamlines workflows, automates tasks, and enhances customer engagement. get your odoo erp answer from the ai.',
    'author': 'Techspawn Solutions',
    'company': 'Techspawn Solutions',
    'website': "https://www.techspawn.com/",
    'category': 'Extra Tools',
    'depends': ['base', 'base_setup', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/chatgpt_model_data.xml',
        'data/mail_channel_data.xml',
        'data/user_partner_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
        ],
    },
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
