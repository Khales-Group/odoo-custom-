# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    sign_stamp_image = fields.Binary(
        string="Signature Stamp",
        attachment=True,
        help="Static stamp/signature image for this company. When set, "
        "every 'Signature' field on a Sign document belonging to this "
        "company is filled automatically with this image instead of "
        "asking the signer to draw a personal signature.",
    )
