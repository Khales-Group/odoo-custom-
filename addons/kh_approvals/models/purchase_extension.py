from odoo import models, fields

class PurchaseOrderExtension(models.Model):
    _inherit = 'purchase.order'

    # Studio field referenced in your database views
    x_studio_approvals_requests_1 = fields.One2many(
        'kh.approval.request',
        'purchase_order_id',
        string='Approvals (Studio)',
        readonly=False,
        copy=False,
    )
