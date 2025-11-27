# -*- coding: utf-8 -*-
from odoo import models, fields, api


class KhApprovalRequestProduct(models.Model):
    _name = "kh.approval.request.product"
    _description = "Products for Petty Cash Approval"

    request_id = fields.Many2one("kh.approval.request", string="Request", ondelete='cascade')

    product_name = fields.Char(string="Name", required=True)
    product_qty = fields.Float(string="Quantity", default=1)
    product_unit = fields.Char(string="Unit")
    product_price = fields.Float(string="Unit Price")
    product_subtotal = fields.Float(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True
    )

    @api.depends("product_qty", "product_price")
    def _compute_subtotal(self):
        for rec in self:
            rec.product_subtotal = (rec.product_qty or 0.0) * (rec.product_price or 0.0)
