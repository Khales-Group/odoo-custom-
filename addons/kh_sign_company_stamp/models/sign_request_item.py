# -*- coding: utf-8 -*-
from odoo import models


class SignRequestItem(models.Model):
    _inherit = "sign.request.item"

    def _get_user_signature(self, signature_type='sign_signature'):
        if signature_type == 'sign_signature':
            sign_request = self.sign_request_id
            company = sign_request.communication_company_id or sign_request.create_uid.company_id
            if company and company.sign_stamp_image:
                return company.sign_stamp_image
        return super()._get_user_signature(signature_type)
