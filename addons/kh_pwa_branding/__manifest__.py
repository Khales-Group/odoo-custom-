{
    "name": "Khales PWA Branding",
    "version": "19.0.1.0.0",
    "summary": "Use the company logo as the installed-app icon instead of the default Odoo icon",
    "description": """
Khales PWA Branding
====================

Three fixes to Odoo's "Install App" (PWA) feature:

1. The whole-Odoo install manifest hard-codes the generic Odoo icon instead
   of the active company's logo.
2. The per-app scoped install (icon.svg lookup) never finds our modules'
   icon.png, so it also falls back to the generic icon.
3. The "Install App" menu item only offers a per-app scoped install (its own
   icon) for "barcode", "field-service" and "shop-floor" - every other app
   just gets the generic whole-Odoo prompt. This lifts that restriction for
   any app with a web_icon set on its root menu.
    """,
    "author": "Khales Group",
    "category": "Hidden",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "kh_pwa_branding/static/src/js/install_pwa_item.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
