from odoo import http
from odoo.http import request

class BoqWebsiteController(http.Controller):

    @http.route(['/boq/submit'], type='json', auth="public", methods=['POST'], website=True)
    def boq_submit_json(self, project_id, applicant_name, lines, **kwargs):
        submission = request.env['kh.boq.submission'].sudo().create({
            'project_id': int(project_id),
            'applicant_name': applicant_name,
        })
        
        for line in lines:
            # If product_id is 0 (dummy), we just skip linking to a product
            # You might need to add a 'description' field to your kh.boq.line model
            # to store the name if product_id is empty.
            prod_id = int(line['product_id']) if line['product_id'] else False
            
            request.env['kh.boq.line'].sudo().create({
                'submission_id': submission.id,
                'product_id': prod_id, 
                'quantity': float(line['qty']),
                'price_unit': float(line['price']),
            })
            
        return {'success': True, 'submission_id': submission.id}