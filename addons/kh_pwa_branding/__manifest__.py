{
    "name": "Khales PWA Branding",
    "version": "19.0.1.0.0",
    "summary": "Use the company logo as the installed-app icon instead of the default Odoo icon",
    "description": """
Khales PWA Branding
====================

Odoo's "Install App" (PWA) feature hard-codes the generic Odoo icon
(web/static/img/odoo-icon-*.png) for the home-screen/desktop shortcut - there
is no setting for this. This module overrides the web manifest so the
installed icon is the active company's logo instead.
    """,
    "author": "Khales Group",
    "category": "Hidden",
    "depends": ["web"],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
