# -*- coding: utf-8 -*-
from odoo import models, fields, api


class KhApprovalRuleProduct(models.Model):
    _name = "kh.approval.rule.product"
    _description = "Approval Rule Products"
    _order = "id"

    rule_id = fields.Many2one(
        "kh.approval.rule", string="Approval Rule", required=True, ondelete="cascade", index=True
    )
    product_name = fields.Char(string="Product Name", required=True)
    product_qty = fields.Float(string="Quantity", default=1.0)
    product_unit = fields.Char(string="Unit")
    product_price = fields.Float(string="Unit Price", default=0.0)
    product_subtotal = fields.Float(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True
    )

    @api.depends("product_qty", "product_price")
    def _compute_subtotal(self):
        for rec in self:
            rec.product_subtotal = (rec.product_qty or 0.0) * (rec.product_price or 0.0)


class KhApprovalRuleExt(models.Model):
    _inherit = "kh.approval.rule"

    product_line_ids = fields.One2many(
        "kh.approval.rule.product", "rule_id", string="Products", copy=True
    )
    product_ids = fields.Many2many(
        "product.product",
        string="Products",
    )
    code = fields.Char(string="Code")
