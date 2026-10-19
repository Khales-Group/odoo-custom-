{
    "name": "Project Site Visits",
    "version": "19.0.1.0.0",
    "summary": "Log site visits (date + note) on a Project",
    "description": """
Project Site Visits
====================

Adds a "Site Visits" tab on the Project form where each visit is logged as a
simple line: visit date + a note. Nothing else - no workflow, no extra
fields - meant as a small, self-contained building block that can be lifted
into a larger "Visits" app.
    """,
    "author": "Khales Group",
    "category": "Project",
    "depends": ["project"],
    "data": [
        "security/ir.model.access.csv",
        "views/project_project_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
