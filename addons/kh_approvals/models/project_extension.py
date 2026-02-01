from odoo import models, fields, api, _
from odoo.exceptions import UserError
import uuid

class ProjectProject(models.Model):
    _inherit = 'project.project'

    # --- Fields from previous step ---
    boq_plan_ids = fields.One2many('kh.project.boq.plan', 'project_id', string="Master BOQ Plan")
    boq_submission_ids = fields.One2many('kh.boq.submission', 'project_id', string="Received Bids")
    submission_count = fields.Integer(compute='_compute_submission_count', string="Bids Count")

    # --- Fields from user's new code ---
    boq_state = fields.Selection([
        ('draft', 'Draft'), 
        ('published', 'Published')
    ], default='draft', string="BOQ Status", copy=False)
    tender_token = fields.Char("Tender Token", copy=False, readonly=True)
    tender_url = fields.Char(string="Tender Link", compute="_compute_tender_url")

    # --- Compute methods ---
    @api.depends('boq_submission_ids')
    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.boq_submission_ids)

    @api.depends('tender_token', 'boq_state')
    def _compute_tender_url(self):
        base_url = "https://khales-next-25yo.vercel.app"
        for rec in self:
            if rec.tender_token and rec.boq_state == 'published':
                rec.tender_url = f"{base_url}/tender/{rec.tender_token}"
            else:
                rec.tender_url = False

    # --- Actions ---
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
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_reset_boq(self):
        self.boq_state = 'draft'

    def action_submit_boq_from_contractor(self):
        self.ensure_one()
        if not self.env.user.partner_id:
             raise UserError("User must be linked to a Partner.")
        submission = self.env['kh.boq.submission'].create({
            'project_id': self.id,
            'contractor_id': self.env.user.partner_id.id,
        })
        for line in self.boq_plan_ids:
            self.env['kh.boq.line'].create({
                'submission_id': submission.id,
                'plan_line_id': line.id,
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
