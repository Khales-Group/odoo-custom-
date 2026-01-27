from odoo import http
from odoo.http import request

class BoqWebsiteController(http.Controller):

    @http.route(['/boq/fill/<int:project_id>'], type='http', auth="public", website=True)
    def boq_fill_form(self, project_id, **kwargs):
        project = request.env['project.project'].sudo().browse(project_id)
        if not project.exists():
            return request.not_found()

        # Hardcoded Example: Grouping products by category for the UI
        # In reality, you'd fetch this dynamically from your products
        sections = []
        # Example data structure:
        # sections = [{'id': 1, 'name': 'Preliminaries', 'items': [...]}]
        
        vals = {
            'project': project,
            'sections': sections, # Pass real data here
        }
        return request.render("kh_approvals.boq_public_template", vals)

    @http.route(['/boq/submit'], type='json', auth="public", methods=['POST'], website=True)
    def boq_submit_json(self, project_id, applicant_name, lines, **kwargs):
        submission = request.env['kh.boq.submission'].sudo().create({
            'project_id': int(project_id),
            'applicant_name': applicant_name,
        })
        for line in lines:
            request.env['kh.boq.line'].sudo().create({
                'submission_id': submission.id,
                'product_id': int(line['product_id']),
                'quantity': float(line['qty']),
                'price_unit': float(line['price']),
            })
        return {'success': True, 'submission_id': submission.id}