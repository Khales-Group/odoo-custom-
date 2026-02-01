from odoo import models, fields, api, _
from odoo.exceptions import UserError
import uuid

class ProjectProject(models.Model):
    _inherit = 'project.project'

    boq_plan_ids = fields.One2many('kh.project.boq.plan', 'project_id', string="Master BOQ Plan")
    boq_submission_ids = fields.One2many('kh.boq.submission', 'project_id', string="Received Bids")
    submission_count = fields.Integer(compute='_compute_submission_count', string="Bids Count")

    boq_state = fields.Selection([
        ('draft', 'Draft'), 
        ('published', 'Published')
    ], default='draft', string="BOQ Status", copy=False)
    
    tender_token = fields.Char("Tender Token", copy=False, readonly=True)
    tender_url = fields.Char(string="Tender Link", compute="_compute_tender_url")

    @api.depends('boq_submission_ids')
    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.boq_submission_ids)

    @api.depends('tender_token', 'boq_state')
    def _compute_tender_url(self):
        base_url = "https://khales.ae"
        for rec in self:
            if rec.tender_token and rec.boq_state == 'published':
                rec.tender_url = f"{base_url}/tender/{rec.tender_token}"
            else:
                rec.tender_url = False

    def action_load_default_boq_template(self):
        self.ensure_one()
        if self.boq_plan_ids: return
        # ... (قائمة البنود الافتراضية كما هي في الكود السابق) ...
        default_items = [
            ('(1) PRELIMINARIES', 'Site Preparation, Temp Fencing, Site Sign Board', 'Unit'),
            # ... (يمكنك إبقاء القائمة الطويلة هنا كما كانت) ...
        ]
        # إذا كنت تريد اختصار الكود هنا للتجربة، وإلا اترك القائمة كما كانت لديك
        lines = [(0, 0, {'section_name': s, 'item_description': n, 'uom_id': u, 'quantity': 0.0}) for s, n, u in default_items]
        self.write({'boq_plan_ids': lines})

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

    def action_publish_boq(self):
        for rec in self:
            rec.boq_state = 'published'
            if not rec.tender_token:
                rec.tender_token = str(uuid.uuid4())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_reset_boq(self):
        self.boq_state = 'draft'

    # --- التصحيح هنا: استخدام الحقول النصية بدلاً من contractor_id ---
    def action_submit_boq_from_contractor(self):
        self.ensure_one()
        if not self.env.user.partner_id:
             raise UserError("User must be linked to a Partner.")
        
        partner = self.env.user.partner_id
        
        # إنشاء سجل التقديم بالبيانات النصية
        submission = self.env['kh.boq.submission'].create({
            'project_id': self.id,
            'contractor_name': partner.name,          # ✅ الاسم نصياً
            'contractor_email': partner.email,        # ✅ الايميل نصياً
            'contractor_phone': partner.phone or partner.mobile, # ✅ الهاتف نصياً
            # 'contractor_id': partner.id, # ألغيت هذا السطر لأنه سبب الخطأ
        })
        
        for line in self.boq_plan_ids:
            self.env['kh.boq.line'].create({
                'submission_id': submission.id,
                'plan_line_id': line.id,
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

# --- باقي الموديلات (Submission, Lines, Plan) ---

class BoqSubmission(models.Model):
    _name = 'kh.boq.submission'
    _description = 'BOQ Submission'
    _rec_name = 'contractor_name'
    _order = 'submission_date desc'

    project_id = fields.Many2one('project.project', string="Project", required=True)
    
    # الحقول النصية الجديدة
    contractor_name = fields.Char(string="Contractor Name", required=True)
    contractor_email = fields.Char(string="Email")
    contractor_phone = fields.Char(string="Phone")
    
    # أبقيت هذا الحقل كـ اختياري لعدم كسر الكود إذا كان موجوداً في مكان آخر، 
    # لكن الزر أعلاه لم يعد يعتمد عليه
    contractor_id = fields.Many2one('res.partner', string="Linked Partner (Optional)")

    submission_date = fields.Datetime(string="Submission Date", default=fields.Datetime.now)
    line_ids = fields.One2many('kh.boq.line', 'submission_id', string="Pricing Lines")
    total_amount = fields.Float(string="Total Bid Value", compute="_compute_total", store=True)

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(line.subtotal for line in rec.line_ids)

class BoqSubmissionLine(models.Model):
    _name = 'kh.boq.line'
    _description = 'Submission Line'

    submission_id = fields.Many2one('kh.boq.submission')
    plan_line_id = fields.Many2one('kh.project.boq.plan', string="Item Ref", required=True)
    
    section_name = fields.Char(related='plan_line_id.section_name', store=True)
    item_description = fields.Char(related='plan_line_id.item_description', store=True)
    uom_id = fields.Char(related='plan_line_id.uom_id', string="Unit", store=True)
    quantity = fields.Float(related='plan_line_id.quantity', string="Qty", store=True)
    
    unit_price = fields.Float(string="Unit Price")
    subtotal = fields.Float(string="Subtotal", compute="_compute_subtotal", store=True)

    @api.depends('quantity', 'unit_price')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = rec.quantity * rec.unit_price

class ProjectBoqPlan(models.Model):
    _name = 'kh.project.boq.plan'
    _description = 'Master BOQ Item'
    
    project_id = fields.Many2one('project.project')
    section_name = fields.Char()
    item_description = fields.Char()
    quantity = fields.Float()
    uom_id = fields.Char()
    contractor_unit_price = fields.Float(string="Your Price")