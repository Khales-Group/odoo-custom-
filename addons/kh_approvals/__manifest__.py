# addons/kh_approvals/__manifest__.py
{
    "name": "Khales Approvals",
    "summary": "Configurable multi-step approvals with routing rules.",
    "version": "18.0.1.0.0",
    "author": "Khales Team",
    "website": "https://khales.ae",
    "category": "Operations/Approvals",
    "depends": ["base", "mail", "hr", "hr_payroll", "account", "project"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        # --- security first ---
        "security/kh_approvals_security.xml", # This file was missing, I've added it.
        "security/ir.model.access.csv",
        "security/kh_approvals_manager_access.xml",
        "security/kh_approvals_rules.xml",
        # --- data ---
        "data/sequence.xml",
        # --- views ---
        "views/approval_request_views.xml",
        "views/approval_rule_views.xml",
        "views/qweb_templates.xml",
        "views/department_views.xml",
        "views/approval_request_tree_view.xml",
        "views/hr_employee_views_extension.xml",
        "views/payslip_views.xml",

        # --- ACTIONS + MENUS LAST (they may reference the views above) ---
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "kh_approvals/static/src/css/approvals_backend.css",
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3",
}