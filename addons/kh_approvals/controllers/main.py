# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class ApprovalDashboard(http.Controller):

    @http.route('/kh_approvals/dashboard', type='json', auth='user')
    def get_approval_rules(self):
        user = request.env.user
        company_id = user.company_id.id
        
        # Search for approval rules matching the user's company
        approval_rules = request.env['kh.approval.rule'].search([
            ('company_id', '=', company_id)
        ])
        
        # Prepare data for the template
        rules_data = []
        for rule in approval_rules:
            rules_data.append({
                'id': rule.id,
                'name': rule.name,
            })
        
        return rules_data