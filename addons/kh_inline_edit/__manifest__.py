{
    "name": "Khales Inline Edit",
    "version": "19.0.1.0.0",
    "summary": "Edit fields directly on Kanban cards, without opening the record",
    "description": """
Khales Inline Edit
==================

Standard Odoo Kanban cards are read-only: fields show as plain text and the
only way to change anything is to open the record. This module adds two
field widgets that stay editable right on the card and save immediately:

- ``kh_inline``: picks the right control from the field type - a dropdown
  for selection fields, a search-as-you-type box for many2one fields, a date
  picker for dates, and a text box for text/number fields (numbers accept
  things like "2,000,000 AED" or "1.250.000").
- ``kh_status_dot``: a coloured dot (green / yellow / red) that opens a
  picker when clicked, no text.

Used by the Leads and Projects dashboards.
    """,
    "author": "Khales Group",
    "category": "Hidden/Tools",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "kh_inline_edit/static/src/inline_field.js",
            "kh_inline_edit/static/src/inline_field.xml",
            "kh_inline_edit/static/src/inline_field.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
