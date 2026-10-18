# -*- coding: utf-8 -*-
from odoo import api, models


class SignRequestItemValue(models.Model):
    _inherit = "sign.request.item.value"

    def _kh_stamp_value(self, sign_item_id, sign_request_item_id):
        """Data-url of the company stamp for this (item, request item) pair,
        or False if this isn't a 'Signature' field or the document's
        company has no stamp configured."""
        signature_type = self.env.ref("sign.sign_item_type_signature", raise_if_not_found=False)
        item = self.env["sign.item"].browse(sign_item_id)
        if not signature_type or not item.exists() or item.type_id != signature_type:
            return False
        request_item = self.env["sign.request.item"].browse(sign_request_item_id)
        company = request_item.sign_request_id.company_id
        if not company or not company.sign_stamp_image:
            return False
        return "data:image/png;base64,%s" % company.sign_stamp_image.decode()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("sign_item_id") and vals.get("sign_request_item_id"):
                stamp = self._kh_stamp_value(vals["sign_item_id"], vals["sign_request_item_id"])
                if stamp:
                    vals["value"] = stamp
        return super().create(vals_list)

    def write(self, vals):
        if "value" not in vals:
            return super().write(vals)
        for record in self:
            stamp = record._kh_stamp_value(record.sign_item_id.id, record.sign_request_item_id.id)
            super(SignRequestItemValue, record).write({**vals, "value": stamp} if stamp else vals)
        return True
