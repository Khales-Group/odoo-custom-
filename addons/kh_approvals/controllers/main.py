from odoo import http
from odoo.http import request
import json

class TenderApiController(http.Controller):
    @http.route('/api/tender/<string:token>', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_tender_details(self, token):
        project = request.env['project.project'].sudo().search([
            ('tender_token', '=', token),
            ('boq_state', '=', 'published')
        ], limit=1)
        
        if not project:
            return request.make_response(json.dumps({'error': 'Tender not found or not published'}), headers={'Content-Type': 'application/json'})

        data = {
            'project_name': project.name,
            'boq_items': [
                {
                    'section': line.section_name,
                    'description': line.item_description,
                    'quantity': line.quantity,
                    'uom': line.uom_id,
                } for line in project.boq_plan_ids
            ]
        }
        return request.make_response(json.dumps(data), headers={'Content-Type': 'application/json'})
