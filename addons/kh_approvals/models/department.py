from odoo import fields, models

class KhApprovalsDepartment(models.Model):
    _name = "kh.approvals.department"
    _description = "Approvals Department"
    _rec_name = "name"
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True, index=True)
