# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class SignRequestItemValue(models.Model):
    _inherit = "sign.request.item.value"

    def _kh_stamp_value(self, sign_item_id, sign_request_item_id):
        """Data-url of the company stamp for this (item, request item) pair,
        or False if this isn't a 'Signature' field or the document's
        company has no stamp configured."""
        item = self.env["sign.item"].browse(sign_item_id)
        if not item.exists():
            _logger.info("KH_SIGN_STAMP: sign.item %s not found", sign_item_id)
            return False

        if item.type_id.item_type != "signature":
            _logger.info(
                "KH_SIGN_STAMP: item %s has item_type '%s' (not 'signature') - skipped",
                sign_item_id, item.type_id.item_type,
            )
            return False

        request_item = self.env["sign.request.item"].browse(sign_request_item_id)
        company = request_item.sign_request_id.company_id
        if not company:
            _logger.info(
                "KH_SIGN_STAMP: request item %s has no company on its sign.request - skipped",
                sign_request_item_id,
            )
            return False
        if not company.sign_stamp_image:
            _logger.info(
                "KH_SIGN_STAMP: company '%s' (id %s) has no sign_stamp_image configured - skipped",
                company.name, company.id,
            )
            return False

        _logger.info(
            "KH_SIGN_STAMP: applying stamp of company '%s' to item %s",
            company.name, sign_item_id,
        )
        return "data:image/png;base64,%s" % company.sign_stamp_image.decode()

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info("KH_SIGN_STAMP: create() ENTERED with %d vals: %s", len(vals_list), vals_list)
        for vals in vals_list:
            if vals.get("sign_item_id") and vals.get("sign_request_item_id"):
                stamp = self._kh_stamp_value(vals["sign_item_id"], vals["sign_request_item_id"])
                if stamp:
                    vals["value"] = stamp
            else:
                _logger.info(
                    "KH_SIGN_STAMP: create() called without sign_item_id/sign_request_item_id: %s",
                    vals,
                )
        return super().create(vals_list)

    def write(self, vals):
        _logger.info("KH_SIGN_STAMP: write() ENTERED on ids=%s with vals=%s", self.ids, vals)
        if "value" not in vals:
            return super().write(vals)
        for record in self:
            stamp = record._kh_stamp_value(record.sign_item_id.id, record.sign_request_item_id.id)
            super(SignRequestItemValue, record).write({**vals, "value": stamp} if stamp else vals)
        return True
