from odoo import models

class AccountMove(models.Model):
    _inherit = "account.move"

    def action_open_gemini_ocr(self):
        return {
            "name": "Invoice OCR",
            "type": "ir.actions.act_window",
            "res_model": "invoice.ocr.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_move_id": self.id},
        }
