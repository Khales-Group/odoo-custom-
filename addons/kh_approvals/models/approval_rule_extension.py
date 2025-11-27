# -- coding: utf-8 --
from odoo import models, fields

class KhApprovalRuleProduct(models.Model):
    _name = "kh.approval.rule.product"
    _description = "Approval Rule Product"
    _order = "id"

    rule_id = fields.Many2one("kh.approval.rule", "Rule", ondelete="cascade", required=True)
    product_name = fields.Char("Product/Service", required=True)
    quantity = fields.Float("Qty", default=1.0)
    unit_price = fields.Float("Unit Price")
    uom_id = fields.Many2one("uom.uom", "UoM")

class KhApprovalRuleExt(models.Model):
    _inherit = "kh.approval.rule"

    product_line_ids = fields.One2many(
    "kh.approval.rule.product", "rule_id", string="Products", copy=True
)
