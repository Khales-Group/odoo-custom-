{
    "name": "Sign - Project Link",
    "version": "19.0.1.0.0",
    "summary": "Link Sign documents and templates to a Project",
    "description": """
Sign - Project Link
====================

Adds a Project field to Sign templates and signature requests, so a document
uploaded for signature can be tied to a project:

- "Project" field on the sign document (sign.template) and on every
  signature request created from it (sign.request). A request created from
  a template that already has a project keeps that project automatically.
- "Signature Requests" smart button on the Project form to see every
  signed/pending document linked to that project.
- "New Document for Signature" button on the Project form to upload a new
  document straight into the Sign app, pre-linked to that project.
    """,
    "author": "Khales Group",
    "category": "Project",
    "depends": ["project", "sign"],
    "data": [
        "views/project_project_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
