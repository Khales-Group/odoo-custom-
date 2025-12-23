from odoo import models, fields

class CrmLeadExtension(models.Model):
    _inherit = 'crm.lead'

    # Studio field referenced in your database views: show related approvals
    x_studio_approvals = fields.One2many(
        'kh.approval.request',
        'crm_lead_id',
        string='Approvals (Studio)',
        readonly=False,
        copy=False,
    )
