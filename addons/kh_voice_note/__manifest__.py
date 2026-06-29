# -*- coding: utf-8 -*-
{
    'name': 'Khales Voice Notes (STT)',
    'summary': 'تسجيل صوتي في اللوغ نوت مع تحويل نص عربي/إنجليزي بـ Deepgram nova-3',
    'version': '19.0.1.0.0',
    'author': 'Khales Group',
    'category': 'Discuss',
    'depends': ['mail'],
    'assets': {
        'web.assets_backend': [
            'kh_voice_note/static/src/css/voice_note.css',
            'kh_voice_note/static/src/xml/voice_note.xml',
            'kh_voice_note/static/src/js/voice_note.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
