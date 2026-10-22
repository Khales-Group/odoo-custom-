{
    "name": "Khales Projects Dashboard",
    "version": "19.0.1.2.0",
    "summary": "Project kanban dashboard matching the manager's paper 'Project Card 9.1'",
    "description": """
Khales Projects Dashboard
============================

A Kanban card dashboard for projects, matching the fields on the manager's
paper "Project Card 9.1": code, name, Emirate, company, client, contract
value, collected/remaining, status (Green/Yellow/Red) with a reason, owner,
and last update.

Collected/Remaining are computed live from real accounting data (amounts
received on posted customer invoices, minus credit notes), not a separate
manual entry. Invoices are tagged inconsistently, so each one is counted
once, for the first rule that identifies its project:
1. A project picked in the invoice lines' Analytic Distribution.
2. Otherwise the client (duplicate contacts with the same name count as one
   client): if the client has one project, that project; if several, the
   one whose number (e.g. 00134) is written on the invoice reference, notes
   or a line label.
3. Otherwise the payment is shown on the client's project cards as
   "Unlinked payments" and not added to Collected - guessing would put
   money on the wrong project.

Not included (not tracked anywhere in the system yet - would need a new
field if wanted): required outcome to close, "final uploaded to Odoo Y/N".
    """,
    "author": "Khales Group",
    "category": "Project",
    "depends": ["project", "account", "kh_collection", "kh_inline_edit"],
    "data": [
        "views/project_project_views.xml",
        "views/project_project_form_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
