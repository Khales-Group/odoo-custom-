# -*- coding: utf-8 -*-
{
    'name': 'Khales AI Employee Report',
    'summary': 'تقرير شهري لتوثيق الموظفين مع تحليل AI',
    'version': '19.0.1.0.0',
    'depends': ['base', 'mail', 'project', 'hr_timesheet'],
    'external_dependencies': {
        'python': ['google-genai'],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}