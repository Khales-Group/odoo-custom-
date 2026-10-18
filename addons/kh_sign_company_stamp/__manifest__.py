{
    "name": "Sign - Static Company Stamp",
    "version": "19.0.1.0.0",
    "summary": "Every Signature field on a Sign document is filled with the company's static stamp instead of a personal signature",
    "description": """
Sign - Static Company Stamp
============================

We have 3 legal companies and the documents we send through Sign (offers,
contracts...) need the company's official stamp on them, not a personal
hand-drawn signature from whoever is assigned as the signer.

This module does not change anything in the Sign editor - no new field
type, no new button. The existing "Signature" field is used exactly as
before when preparing a document.

What changes is what happens when the signer opens the document and signs
it: instead of being asked to draw/type/upload a signature, every
"Signature" field is pre-filled automatically with the stamp image
configured on the document's company (Settings > Companies). The signer
only has to click "Sign" to finalize.

Setup: open Settings > Users & Companies > Companies, pick a company, and
upload its stamp image in the "Signature Stamp" field. Companies without a
stamp configured are unaffected - their Signature fields keep behaving
normally.
    """,
    "author": "Khales Group",
    "category": "Project",
    "depends": ["sign"],
    "data": [
        "views/res_company_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
