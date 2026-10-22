{
    "name": "Khales Projects Dashboard",
    "version": "19.0.1.0.0",
    "summary": "Project kanban dashboard matching the manager's paper 'Project Card 9.1'",
    "description": """
Khales Projects Dashboard
============================

A Kanban card dashboard for projects, matching the fields on the manager's
paper "Project Card 9.1": code, name, Emirate, company, client, contract
value, collected/remaining, status (Green/Yellow/Red) with a reason, owner,
and last update.

Collected/Remaining are computed live from real accounting data, not a
separate manual entry:
- Primary source: invoice lines whose Analytic Distribution points at this
  project's own Analytic Account (account_id) - the normal way an
  accountant ties an invoice to a project.
- Fallback: if no invoice is tagged that way and the client has exactly one
  project (no ambiguity), sum that client's posted invoices directly. Left
  at 0 if the client has more than one project and nothing is tagged -
  guessing which project an untagged invoice belongs to would be worse than
  showing nothing.

Not included (not tracked anywhere in the system yet - would need a new
field if wanted): required outcome to close, "final uploaded to Odoo Y/N".
    """,
    "author": "Khales Group",
    "category": "Project",
    "depends": ["project", "account", "kh_collection"],
    "data": [
        "views/project_project_views.xml",
        "views/project_project_form_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "kh_projects_dashboard/static/src/js/state_selection_colors.js",
            "kh_projects_dashboard/static/src/scss/state_selection_colors.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
