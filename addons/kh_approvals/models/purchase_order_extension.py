# -*- coding: utf-8 -*-
from odoo import fields, models

class PurchaseOrderExtension(models.Model):
    _inherit = 'purchase.order'

    # 1. Add this field to store the link back to the approval
    kh_approval_id = fields.Many2one(
        'kh.approval.request', 
        string='Source Approval Request', 
        readonly=True, 
        copy=False,
        ondelete='set null'
    )

    # Keep your studio field if you still want the list view
    x_studio_approvals_requests_1 = fields.One2many(
        'kh.approval.request',
        'purchase_order_id',
        string='Approvals (Studio)',
        readonly=False,
        copy=False,
    )