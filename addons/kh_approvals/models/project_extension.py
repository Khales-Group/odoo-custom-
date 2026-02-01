from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ProjectProject(models.Model):
    _inherit = 'project.project'

    # --- Existing Fields ---
    boq_plan_ids = fields.One2many('kh.project.boq.plan', 'project_id', string="Master BOQ Plan")
    boq_state = fields.Selection([('draft', 'Draft'), ('published', 'Published')], default='draft', string="BOQ Status")
    
    # --- New: Smart Button Logic ---
    boq_submission_ids = fields.One2many('kh.boq.submission', 'project_id', string="Received Bids")
    submission_count = fields.Integer(compute='_compute_submission_count', string="Bids Count")

    @api.depends('boq_submission_ids')
    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.boq_submission_ids)

    def action_view_submissions(self):
        self.ensure_one()
        return {
            'name': _('Received Bids'),
            'type': 'ir.actions.act_window',
            'res_model': 'kh.boq.submission',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    # --- Actions ---
    def action_publish_boq(self):
        self.boq_state = 'published'

    def action_reset_boq(self):
        self.boq_state = 'draft'

    def action_submit_boq_from_contractor(self):
        self.ensure_one()
        # تأكد من وجود مستخدم مرتبط
        if not self.env.user.partner_id:
             raise UserError("User must be linked to a Partner.")

        # إنشاء سجل التقديم (Submission)
        submission = self.env['kh.boq.submission'].create({
            'project_id': self.id,
            'contractor_id': self.env.user.partner_id.id, # تخزين اسم المقاول
        })

        # إنشاء الأسطر وربطها بالبيانات الأصلية
        for line in self.boq_plan_ids:
            # نقوم بنقل السطر حتى لو السعر 0 ليظهر كل شيء
            self.env['kh.boq.line'].create({
                'submission_id': submission.id,
                'plan_line_id': line.id, # ربط بالسطر الأصلي لجلب الوصف
                'quantity': line.quantity,
                'unit_price': line.contractor_unit_price,
            })

        return {
            'name': 'Bid Submitted',
            'type': 'ir.actions.act_window',
            'res_model': 'kh.boq.submission',
            'res_id': submission.id,
            'view_mode': 'form',
            'target': 'current',
        }

# --- Master BOQ Plan (كما هو) ---
class ProjectBoqPlan(models.Model):
    _name = 'kh.project.boq.plan'
    _description = 'Master BOQ Item'

    project_id = fields.Many2one('project.project')
    section_name = fields.Char(required=True)
    item_description = fields.Char(required=True)
    quantity = fields.Float(string="Qty", required=True)
    uom_id = fields.Char(string="Unit", default="Unit")
    contractor_unit_price = fields.Float(string="Your Price") # السعر الذي يعبئه المقاول
