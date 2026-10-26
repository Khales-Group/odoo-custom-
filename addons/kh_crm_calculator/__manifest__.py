{
    "name": "Khales CRM Website Calculator",
    "version": "19.0.1.0.0",
    "summary": "x_calc_* fields on leads for the website's villa cost calculator (XML-RPC)",
    "description": """
Khales CRM Website Calculator
=============================

Prepares crm.lead to receive leads from the website's villa cost calculator,
which creates them over XML-RPC (execute_kw "create" on crm.lead):

- 34 plain x_calc_* fields (Char/Float/Integer/Boolean/Text) with the exact
  names and types the website sends. Fields that already exist as manual
  fields are taken over in place, keeping their data (see hooks.py); on
  uninstall they're handed back as manual fields, data included.
- A read-only "Calculator" page on the lead form, shown on calculator leads.
- Search filters (Calculator leads, Design requests, Budget reviews) and
  group-bys (country, city, request type, finish level, start timing) in
  Leads and Pipeline.
- Tags "Calculator v2", "Design request", "Budget review" and the source
  "Website Calculator v2", reused by name when they already exist.

No automation: the module never changes what the website writes.
No new models, so no access rules: the integration user gets the standard
Sales group "User: All Documents".
    """,
    "author": "Khales Group",
    "category": "Sales/CRM",
    "depends": ["crm", "utm"],
    "data": [
        "data/crm_calculator_data.xml",
        "views/crm_lead_views.xml",
    ],
    "pre_init_hook": "pre_init_hook",
    "uninstall_hook": "uninstall_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
