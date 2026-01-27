from odoo import models, fields, api
from odoo.exceptions import UserError

class ProjectProject(models.Model):
    _inherit = 'project.project'

    # --- Existing Fields ---
    contractor_email = fields.Char(string="Contractor Email")
    is_manager = fields.Boolean(compute='_compute_is_manager')

    # --- NEW BOQ Fields ---
    boq_submission_count = fields.Integer(compute='_compute_boq_submission_count')

    # --- BOQ Logic: Count Submissions ---
    def _compute_boq_submission_count(self):
        for project in self:
            # Counts how many submissions differ for this project ID
            project.boq_submission_count = self.env['kh.boq.submission'].search_count([
                ('project_id', '=', project.id)
            ])

    # --- BOQ Logic: Smart Button Action ---
    def action_view_boq_submissions(self):
        self.ensure_one()
        return {
            'name': 'BOQ Submissions',
            'type': 'ir.actions.act_window',
            'res_model': 'kh.boq.submission',
            'view_mode': 'tree,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    # --- BOQ Logic: Website Helper ---
    def _get_boq_sections_for_website(self):
        self.ensure_one()
        # This returns the structure for the website form.
        # Ideally, fetch this from real product categories.
        return [
            {
                'id': 1, 'name': 'PRELIMINARIES / MOBILIZATION', 'items': [
                    {'product_id': 1, 'name': 'Site Preparation', 'description': 'Temp fencing, signage', 'qty': 1, 'uom_name': 'Unit', 'qty_available': 0, 'price': 0.0},
                    {'product_id': 2, 'name': 'Site Admin Facilities', 'description': 'Offices & Supervision', 'qty': 1, 'uom_name': 'Unit', 'qty_available': 0, 'price': 0.0},
                ]
            },
            {
                'id': 2, 'name': 'SITE WORKS / EARTH WORKS', 'items': [
                    {'product_id': 3, 'name': 'Excavation', 'description': 'Up to required level', 'qty': 500, 'uom_name': 'm3', 'qty_available': 0, 'price': 0.0},
                ]
            },
            # You can add the rest of the 15 sections here
        ]

    # --- Existing Security Logic ---
    @api.depends('user_id')
    def _compute_is_manager(self):
        for rec in self:
            rec.is_manager = (rec.user_id == self.env.user)

    def write(self, vals):
        protected_fields = ['contractor_email', 'partner_id', 'date_start']
        for project in self:
            is_manager = project.user_id == self.env.user
            trying_to_edit_protected = any(field in vals for field in protected_fields)

            if not is_manager and trying_to_edit_protected:
                raise UserError("عذراً! لا يمكنك تعديل هذه البيانات لأنك لست مدير المشروع.")

        return super(ProjectProject, self).write(vals)