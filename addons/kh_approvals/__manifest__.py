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
        "security/ir.model.access.csv",
        "security/kh_approvals_security.xml",
        "views/menu.xml",
        "views/approval_rule_views.xml",
        "views/approval_request_views.xml"
    ],
    "application": True,
    "installable": True,
    "license": "OEEL-1",
}
