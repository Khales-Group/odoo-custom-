from odoo import fields, models


class LawDocument(models.Model):
    _name = "kh.law.document"
    _description = "Required Document (PRO checklist)"
    _order = "sequence, id"

    report_id = fields.Many2one("x_reports", string="File", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Document", required=True)
    kh_is_received = fields.Boolean(string="Received")
    kh_note = fields.Char(string="Note")
