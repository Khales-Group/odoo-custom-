from odoo import http
from odoo.http import request
import json

class TenderController(http.Controller):

    # 1. Fetch BOQ Details for the Website
    @http.route('/api/tender/<string:token>', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_tender_details(self, token):
        project = request.env['project.project'].sudo().search([('tender_token', '=', token)], limit=1)
        
        if not project:
            return request.make_response(json.dumps({'error': 'Invalid Token'}), headers={'Content-Type': 'application/json'})

        # Prepare BOQ List from existing kh.project.boq.plan
        boq_data = []
        for line in project.boq_plan_ids: 
            boq_data.append({
                'id': line.id,
                'section': line.section_name,
                'name': line.item_description,
                'quantity': line.quantity,
                'uom': line.uom_id,
            })

        return request.make_response(json.dumps({
            'project_name': project.name,
            'boq_items': boq_data
        }), headers={'Content-Type': 'application/json'})

    # 2. Submit Bid from Website
    @http.route('/api/tender/submit', type='json', auth='public', methods=['POST'], cors='*')
    def submit_tender(self, **kwargs):
        data = request.jsonrequest
        token = data.get('token')
        project = request.env['project.project'].sudo().search([('tender_token', '=', token)], limit=1)

        if not project:
            return {'status': 'error', 'message': 'Invalid Project'}

        # Create the submission record
        submission = request.env['tender.submission'].sudo().create({
            'project_id': project.id,
            'contractor_name': data.get('contractor_name'),
            'contractor_email': data.get('email'),
            'contractor_phone': data.get('phone'),
        })

        # Create lines
        for item in data.get('items', []):
            request.env['tender.submission.line'].sudo().create({
                'submission_id': submission.id,
                'boq_item_id': item['boq_id'],
                'offered_price': item['price'],
            })

        return {'status': 'success', 'submission_id': submission.id}