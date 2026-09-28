{
    "name": "Khales Law & PRO",
    "version": "19.0.1.0.1",
    "summary": "Legal Affairs and PRO departments on top of the Studio 'Law' model",
    "description": """
Khales Law & PRO
================

The Law model (x_reports) and its stages (x_reports_stage) were built with
Odoo Studio. This module takes ownership of both in code, under the same
technical names, so existing records keep working. The Studio fields
themselves (x_studio_type, x_studio_company_id, ...) are left untouched and
Studio-managed; only the stage field is redefined. The department of a file
is its Studio field x_studio_type (Law / PRO). The module adds:

- A department dashboard (Legal Affairs / PRO) as the app's entry screen.
- Separate stages per department (Legal: Open > Preparation > Hearings >
  Judgment > Execution > Closed; PRO: Not Started > Preparing Documents >
  Submitted > Awaiting Government > Completed).
- Legal: priority stars, lawyer's assessment, outcome, fees expected vs
  collected, last update and "days without activity" warning, duration.
- PRO: service type, expiry date with a coloured countdown, target date and
  late flag, required-documents checklist, fines and rejections.
- Reports per department and periodic manager evaluations.

Install/uninstall notes: the pre-init hook marks the Studio models as
code-owned (otherwise the Studio definitions would replace the Python ones at
load time); the post-init hook migrates the existing stages; the uninstall
hook hands the models back to Studio.
    """,
    "author": "Khales Group",
    "category": "Services",
    "depends": ["mail", "project"],
    "data": [
        "security/kh_law_security.xml",
        "security/ir.model.access.csv",
        "data/kh_law_department_data.xml",
        "views/x_reports_views.xml",
        "views/x_reports_stage_views.xml",
        "views/kh_law_report_views.xml",
        "views/kh_law_evaluation_views.xml",
        "views/kh_law_department_views.xml",
        "views/kh_law_menus.xml",
    ],
    "pre_init_hook": "pre_init_hook",
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
