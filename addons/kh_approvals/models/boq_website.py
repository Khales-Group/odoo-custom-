# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class BoqWebsiteController(http.Controller):

    @http.route('/boq/fill/<model("project.project"):project>', type='http', auth='public', website=True)
    def boq_fill_form(self, project, **kwargs):
        if project.boq_state != 'published':
            return request.render('kh_approvals.boq_not_published', {'project': project})
        
        # Group items by section
        grouped_items = {}
        # Ensure order is preserved
        sections = []
        for line in project.boq_plan_ids:
            if line.section_name not in grouped_items:
                grouped_items[line.section_name] = []
                sections.append(line.section_name)
            grouped_items[line.section_name].append(line)

        return request.render('kh_approvals.boq_fill_template', {
            'project': project,
            'grouped_items': grouped_items,
            'sections': sections,
        })

    @http.route('/boq/submit', type='http', auth='public', website=True, methods=['POST'])
    def boq_submit(self, **post):
        project_id = int(post.get('project_id'))
        project = request.env['project.project'].sudo().browse(project_id)
        
        # Create Submission
        submission = request.env['kh.boq.submission'].sudo().create({
            'project_id': project.id,
            'partner_id': request.env.user.partner_id.id if not request.env.user._is_public() else False,
        })

        # Parse lines
        # Inputs are named like "price_LINEID"
        for key, value in post.items():
            if key.startswith('price_'):
                try:
                    line_id = int(key.split('_')[1])
                    price = float(value)
                    
                    plan_line = request.env['kh.project.boq.plan'].sudo().browse(line_id)
                    if plan_line.exists():
                        request.env['kh.boq.line'].sudo().create({
                            'submission_id': submission.id,
                            'plan_line_id': plan_line.id,
                            'quantity': plan_line.quantity,
                            'unit_price': price,
                        })
                except ValueError:
                    continue
        
        return request.render('kh_approvals.boq_thank_you', {'submission': submission})