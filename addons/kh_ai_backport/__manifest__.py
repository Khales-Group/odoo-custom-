# -*- coding: utf-8 -*-
{
    'name': 'Khales AI 19.1 Backport',
    'summary': 'Backporting File Attachments & AI Feedback Stages to 19.0',
    'version': '1.2',
    'author': 'Nezar Abou Hamdan',
    'depends': ['ai_app', 'mail'], # تم التحديث بناءً على الـ External ID الصحيح
    'external_dependencies': {
        'python': ['requests', 'numpy', 'pickle', 'base64'],
    },
    'data': [
        'views/ai_agent_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kh_ai_backport/static/src/components/ai_chat_patch.js',
        ],
    },
    'installable': True,
    'license': 'OEEL-1',
}
