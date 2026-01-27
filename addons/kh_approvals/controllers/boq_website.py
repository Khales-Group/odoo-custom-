from odoo import http
from odoo.http import request

class BoqWebsiteController(http.Controller):

    @http.route(['/boq/fill/<int:project_id>'], type='http', auth="public", website=True)
    def boq_fill_form(self, project_id, **kwargs):
        project = request.env['project.project'].sudo().browse(project_id)
        
        if not project.exists():
            return "Project not found"
        
        # إذا لم يقم الموظف بالنشر بعد، لا تظهر الصفحة
        if project.boq_state != 'published':
            return request.render("website.404") # أو صفحة انتظار

        # تجميع البنود حسب القسم
        sections = {}
        for line in project.boq_plan_ids:
            if line.section_name not in sections:
                sections[line.section_name] = []
            
            sections[line.section_name].append({
                'id': line.id, # معرف البند الأصلي
                'name': line.item_description,
                'qty': line.quantity, # الكمية التي أدخلها الموظف
                'uom': line.uom_id
            })

        vals = {
            'project': project,
            'grouped_sections': sections,
        }
        return request.render("kh_approvals.boq_public_template", vals)

    @http.route(['/boq/submit'], type='json', auth="public", methods=['POST'], website=True)
    def boq_submit_json(self, project_id, applicant_name, lines, **kwargs):
        # 1. إنشاء سجل التقديم
        submission = request.env['kh.boq.submission'].sudo().create({
            'project_id': int(project_id),
            'applicant_name': applicant_name,
        })
        
        # 2. إنشاء السطور
        for line in lines:
            # نجلب بيانات البند الأصلي للتأكد
            plan_line = request.env['kh.project.boq.plan'].sudo().browse(int(line['plan_id']))
            
            request.env['kh.boq.line'].sudo().create({
                'submission_id': submission.id,
                'product_name_snapshot': plan_line.item_description, # حفظ الاسم كمرجع
                'quantity': plan_line.quantity,   # الكمية ثابتة من المخطط
                'price_unit': float(line['price']), # السعر من المقاول
            })
            
        return {'success': True, 'submission_id': submission.id}