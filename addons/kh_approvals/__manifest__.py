# addons/kh_approvals/__manifest__.py
{
    "name": "Khales Approvals",
    "summary": "Configurable multi-step approvals with routing rules.",
    "version": "18.0.1.0.0",
    "author": "Khales Team",
    "website": "https://khales.ae",
    "category": "Operations/Approvals",
    "depends": ["base", "mail"],   # no need to add 'discuss' because we guard its usage
    "data": [
        # security first
        "security/ir.model.access.csv",
        "security/kh_approvals_security.xml",
        "security/kh_approvals_rules.xml",
        "views/mail_activity_views.xml",
        "views/approval_rule_views.xml",
        "views/approval_request_views.xml",
        "views/menu.xml",
    ],
    "application": True,
    "installable": True,
    "license": "LGPL-3",
}
