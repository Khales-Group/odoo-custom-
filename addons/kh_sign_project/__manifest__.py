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
- "New Document for Signature" button on the Project form, and a standalone
  "Upload Document for Signature" menu under Project, that open a small
  wizard where the project is picked explicitly at upload time.
- "Project" selector added directly next to "Tags" on the Sign document
  editor's top bar, so it can be set/changed while editing the document.
    """,
    "author": "Khales Group",
    "category": "Project",
    "depends": ["project", "sign"],
    "data": [
        "security/ir.model.access.csv",
        "views/sign_upload_wizard_views.xml",
        "views/project_project_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "kh_sign_project/static/src/js/sign_template_header_project.js",
            "kh_sign_project/static/src/js/sign_template_header_project.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
