# -*- coding: utf-8 -*-
from odoo import models, fields


class KhApprovalRuleProduct(models.Model):
    _name = "kh.approval.rule.product"
    _description = "Approval Rule Product"
    _order = "id"

    rule_id = fields.Many2one(
        "kh.approval.rule", string="Rule", required=True, ondelete="cascade", index=True
    )
    product_name = fields.Char(string="Product Name", required=True)
    quantity = fields.Float(string="Quantity", default=1.0)
    unit_price = fields.Float(string="Unit Price")  # simple float to avoid currency issues
    uom_id = fields.Many2one("uom.uom", string="UoM")


class KhApprovalRuleExt(models.Model):
    _inherit = "kh.approval.rule"

    product_line_ids = fields.One2many(
        "kh.approval.rule.product", "rule_id", string="Products", copy=True
    )
