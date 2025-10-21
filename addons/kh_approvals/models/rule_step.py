# -*- coding: utf-8 -*-
from odoo import fields, models

class KhApprovalRuleStep(models.Model):
    _name = "kh.approval.rule.step"
    _description = "Approval Rule Step"
    _order = "sequence, id"

    rule_id = fields.Many2one(
        "kh.approval.rule",
        string="Rule",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10, required=True)
    name = fields.Char(string="Step Name")
    approver_id = fields.Many2one("res.users", string="Approver", required=True)
