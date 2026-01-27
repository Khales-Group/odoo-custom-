# -*- coding: utf-8 -*-
{
    'name': 'Khales Approvals',
    'summary': 'Approvals and workflow integrations (compatibility patch for v19)',
    'description': 'Compatibility layer for Studio fields and links to CRM/Project/Purchase after migration to Odoo 19.',
    'author': 'Prepared by ChatGPT for Khales',
    'website': 'https://khales.ae',
    'category': 'Uncategorized',
    'version': '19.0.1.0.0',
    'depends': ['base', 'mail', 'hr', 'project', 'purchase', 'hr_payroll', 'website'], # Added 'website' to depends
    'data': [
        'security/kh_approvals_security.xml',
        'security/ir.model.access.csv',
        'security/kh_approvals_rules.xml',
        'security/wizard_access.xml',
        'views/menu.xml',
        'views/approval_request_views.xml',
        'views/approval_rule_views.xml',
        'views/department_views.xml',
        'views/approval_reject_wizard.xml',
        'views/project_email_views.xml',
        'views/project_views.xml',
        'views/mail_activity_views.xml',
        'views/dashboard_views.xml',
        'views/hr_employee_views_extension.xml',
        'views/payslip_views.xml',
        'views/qweb_templates.xml',
        'views/boq_submission_views.xml',  # <--- MAKE SURE THIS IS HERE
        'views/website_boq_template.xml', # Ensure this is in the data list
        'data/sequence.xml',
        'data/email_categories.xml',
    ],
    # --- THIS IS THE NEW PART YOU NEED ---
    'assets': {
        'web.assets_frontend': [
            'kh_approvals/static/src/js/boq_website.js',
            # If you add a CSS file later, put it here too:
            # 'kh_approvals/static/src/css/boq_style.css',
        ],
    },
    # -------------------------------------
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}