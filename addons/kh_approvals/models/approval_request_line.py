# -*- coding: utf-8 -*-
from odoo import models, fields, api


class KhApprovalRequestLine(models.Model):
    _name = "kh.approval.request.line"
    _description = "Approval Request Product Line"

    request_id = fields.Many2one(
        "kh.approval.request",
        string="Approval Request",
        required=True,
        ondelete="cascade",
    )

    product_name = fields.Char(string="Name", required=True)

    product_qty = fields.Float(string="Qty", default=1)

    product_unit = fields.Char(string="Unit", default="pcs")

    product_price = fields.Float(string="Price", digits=(16, 2))

    product_subtotal = fields.Float(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True,
        digits=(16, 2),
    )

    @api.depends("product_qty", "product_price")
    def _compute_subtotal(self):
        for line in self:
            line.product_subtotal = (line.product_qty or 0.0) * (line.product_price or 0.0)
