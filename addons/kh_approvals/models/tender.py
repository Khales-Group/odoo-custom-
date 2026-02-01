from odoo import models, fields

class TenderSubmission(models.Model):
    _name = 'tender.submission'
    _description = 'Contractor Bid'

    project_id = fields.Many2one('project.project', string="Project", required=True)
    contractor_name = fields.Char("Contractor Name", required=True)
    contractor_email = fields.Char("Email")
    contractor_phone = fields.Char("Phone")
    line_ids = fields.One2many('tender.submission.line', 'submission_id', string="Bid Lines")

class TenderSubmissionLine(models.Model):
    _name = 'tender.submission.line'
    _description = 'Bid Line Detail'

    submission_id = fields.Many2one('tender.submission', string="Submission")
    # Linked to your existing BOQ Plan model
    boq_item_id = fields.Many2one('kh.project.boq.plan', string="BOQ Item") 
    offered_price = fields.Float("Offered Price")