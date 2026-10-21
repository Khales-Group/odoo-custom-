# -*- coding: utf-8 -*-
import mimetypes

from odoo.addons.web.controllers.webmanifest import WebManifest
from odoo.http import request
from odoo.tools import file_path


class KhWebManifest(WebManifest):
    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        company = request.env.company
        if company.logo:
            manifest["icons"] = [
                {
                    "src": "/web/image/res.company/%d/logo/%s" % (company.id, size),
                    "sizes": size,
                    "type": "image/png",
                }
                for size in ("192x192", "512x512")
            ]
        return manifest

    def _get_scoped_app_icons(self, app_id):
        # Core only looks for <app>/static/description/icon.svg and falls
        # back to the generic Odoo icon otherwise - our modules (and most
        # standard Odoo apps) only ship icon.png, so per-app "Install" was
        # silently always using the generic icon. Check png too before
        # giving up.
        for ext in ("svg", "png"):
            rel_path = "%s/static/description/icon.%s" % (app_id, ext)
            try:
                file_path(rel_path)
            except FileNotFoundError:
                continue
            return [{
                "src": "/%s" % rel_path,
                "sizes": "any",
                "type": mimetypes.guess_type(rel_path)[0] or "image/png",
            }]
        return super()._get_scoped_app_icons(app_id)
