# addons/kh_approvals/__manifest__.py
{
    "name": "Khales Approvals",
    "version": "18.0.3.0.0",
    "depends": ["base", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/kh_approvals_security.xml",
        "security/kh_approvals_rules.xml",
        "security/kh_approvals_mc_rules.xml",
        "data/sequence.xml",
        "views/department_views.xml",
        "views/approval_rule_views.xml",      # includes step_ids
        "views/approval_request_views.xml",   # uses rule_id
        "views/menu.xml",
    ],
    "application": True,
    "license": "LGPL-3",
}
