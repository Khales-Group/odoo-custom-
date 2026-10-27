# -*- coding: utf-8 -*-
from odoo import api, fields, models

class KhApprovalsDepartment(models.Model):
    _name = "kh.approvals.department"
    _description = "Approvals Department"
    _rec_name = "name"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)
    kh_auto_bill = fields.Boolean(
        string="Create Bill When Paid",
        help="When an approval of this department is marked Paid (with an amount), "
             "a draft vendor bill is created and linked to it for the accountant to "
             "check and confirm.",
    )
