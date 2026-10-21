# -*- coding: utf-8 -*-
from odoo.addons.web.controllers.webmanifest import WebManifest
from odoo.http import request


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
