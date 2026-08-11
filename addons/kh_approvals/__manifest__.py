# -*- coding: utf-8 -*-
{    'name': 'Khales Approvals',
    'summary': 'Approvals and workflow integrations (compatibility patch for v19)',
    'description': 'Compatibility layer for Studio fields and links to CRM/Project/Purchase after migration to Odoo 19.',
    'author': 'Prepared by ChatGPT for Khales',
    'website': 'https://khales.ae',
    'category': 'Uncategorized',
    'version': '19.0.1.0.0',
    'depends': ['base', 'mail', 'hr', 'project', 'purchase', 'hr_payroll', 'account', 'mcp_server', 'hr_timesheet'],
    'external_dependencies': {
        'python': ['anthropic'],
    },
    'data': [
        'security/kh_approvals_security.xml',
        'security/ir.model.access.csv',
        'security/kh_approvals_rules.xml',
        'security/wizard_access.xml',
        'views/menu.xml',
        # project_ai_manager_views.xml لازم يتحمّل أول أي ملف تاني بيعمل
        # inherit لـ project.edit_project - لأنه Odoo بيتحقق من الأرشيف
        # المجمّع (كل الـ views الوارثة) وقت أي تحديث، فإذا هذا الملف تحمّل
        # لأخّر، الملفات التانية بتشوف نسخته القديمة بالداتابيز وقت التحقق
        # وتطلع "Field does not exist" لحقول تغيّرت أسماءها.
        'views/project_ai_manager_views.xml',
        'views/timeline_import_wizard_views.xml',
        'views/project_project_views.xml',
        'views/approval_request_views.xml',
        'views/approval_rule_views.xml',
        'views/department_views.xml',
        'views/approval_reject_wizard.xml',  # <--- Add this line
        'views/project_email_views.xml',
        'views/project_views.xml',
        'views/project_ai_manager_kanban_views.xml',
        'views/mail_activity_views.xml',
        # kh_ai_dashboard_tile_views.xml لازم يتحمّل قبل dashboard_views.xml
        # لأنه هذا الأخير بيربط menuitem بـ action_kh_ai_dashboard_tiles.
        'views/kh_ai_dashboard_tile_views.xml',
        'views/dashboard_views.xml',
        'views/hr_employee_views_extension.xml',
        'views/payslip_views.xml',
        'views/website_boq_template.xml',
        'views/qweb_templates.xml',
        'data/sequence.xml',
        'data/email_categories.xml',
        'data/kh_ai_project_manager_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kh_approvals/static/src/xml/attachment_uploader_info.xml',
            'kh_approvals/static/src/js/maintenance_banner.js',
            'kh_approvals/static/src/xml/maintenance_banner.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
