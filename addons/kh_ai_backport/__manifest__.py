# -*- coding: utf-8 -*-
{
    'name': 'Khales AI 19.1 Backport',
    'summary': 'Backporting File Attachments & AI Feedback Stages to 19.0',
    'version': '1.2',
    'author': 'Nezar Abou Hamdan',
    'depends': ['base', 'mail', 'ai'],
    'external_dependencies': {
        'python': ['requests', 'numpy', 'pickle', 'base64'],
    },
    'data': [
        'security/ir.model.access.csv',  # Add this exactly here
        'views/ai_agent_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
        ],
    },
    'installable': True,
    'license': 'OEEL-1',
}
