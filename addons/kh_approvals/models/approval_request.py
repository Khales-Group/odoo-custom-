# location: addons/kh_approvals/models/approval_request.py
from odoo import models, fields, api

class ApprovalRequest(models.Model):
    _name = 'kh.approval.request'
    _description = 'Approval Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Description', required=True)
    
    # The fields that were causing "Field does not exist" errors
    date_from = fields.Date(string='Date From', required=True)
    date_to = fields.Date(string='Date To', required=True)
    
    # User fields
    requester_id = fields.Many2one('res.users', string='Requester', default=lambda self: self.env.user, readonly=True)
    approver_id = fields.Many2one('res.users', string='Approver')
    
    # State management
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True)

    # Boolean for button visibility
    is_current_user_approver = fields.Boolean(compute='_compute_is_approver')

    @api.depends('approver_id')
    def _compute_is_approver(self):
        for rec in self:
            rec.is_current_user_approver = (rec.approver_id == self.env.user)

    # Button Actions
    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_draft(self):
        self.write({'state': 'draft'})
