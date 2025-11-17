from odoo import models

class AccountJournal(models.Model):
    _inherit = "account.journal"

    def create_document_from_attachment(self, attachment_ids=None):
        # Call Odoo normal behavior
        moves = super().create_document_from_attachment(attachment_ids=attachment_ids)

        # Call your Gemini OCR method
        if moves:
            moves._extract_ocr_data()

        return moves
