# addons/kh_approvals/__manifest__.py
{
    "name": "Khales Approvals",
    "summary": "Configurable multi-step approvals with routing rules.",
    "version": "18.0.1.0.0",
    "author": "Khales Team",
    "website": "https://khales.ae",
    "category": "Operations/Approvals",
    "depends": ["base", "mail"],
    "data": [
        # --- security first ---
        "security/kh_approvals_security.xml", # This file was missing, I've added it.
        "security/ir.model.access.csv",
        "security/kh_approvals_rules.xml",
        # --- data ---
        "data/sequence.xml",
        # --- views ---
        "views/approval_request_views.xml",
        "views/approval_rule_views.xml",
        "views/qweb_templates.xml",
        "views/department_views.xml",
        "views/dashboard_views.xml",

        # --- ACTIONS + MENUS LAST (they may reference the views above) ---
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "kh_approvals/static/src/css/approvals_backend.css",
            "kh_approvals/static/src/js/dashboard.js",
        ],
        "web.assets_qweb": [
            "kh_approvals/views/dashboard_views.xml",
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3",
}
