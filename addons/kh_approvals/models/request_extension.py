# -*- coding: utf-8 -*-
from odoo import models, fields


class KhApprovalRequestExt(models.Model):
    _inherit = "kh.approval.request"

    approval_rule_id = fields.Many2one(
        "kh.approval.rule",
        string="Approval Rule",
        ondelete="set null",
        index=True,
    )
