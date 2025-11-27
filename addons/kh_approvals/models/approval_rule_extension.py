# -*- coding: utf-8 -*-
from odoo import models, fields, api


class KhApprovalRuleProduct(models.Model):
    _name = "kh.approval.rule.product"
    _description = "Approval Rule Product"
    _order = "id"

    rule_id = fields.Many2one(
        "kh.approval.rule", string="Rule", ondelete="cascade", required=True
    )
    product_id = fields.Many2one("product.product", string="Product", ondelete="set null")
    product_name = fields.Char(string="Product Name")
    quantity = fields.Float(string="Quantity", default=1.0)
    unit_price = fields.Float(string="Unit Price")
    subtotal = fields.Monetary(string="Subtotal", compute="_compute_subtotal", store=True, currency_field=False)
    uom_id = fields.Many2one("uom.uom", string="UoM")

    @api.depends('quantity', 'unit_price')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = (rec.quantity or 0.0) * (rec.unit_price or 0.0)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            # populate name and UoM from product when selected
            self.product_name = self.product_id.name
            if hasattr(self.product_id, 'uom_id'):
                self.uom_id = self.product_id.uom_id.id


class KhApprovalRuleExt(models.Model):
    _inherit = "kh.approval.rule"

    product_line_ids = fields.One2many(
        "kh.approval.rule.product", "rule_id", string="Products", copy=True
    )
