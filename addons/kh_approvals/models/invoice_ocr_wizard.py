from odoo import models, fields, _
from odoo.exceptions import UserError
import base64
import requests
import json
import logging

_logger = logging.getLogger(__name__)

# 🔴 YOUR API KEY (as requested)
GEMINI_API_KEY = "AIzaSyByJEePnY633napEEYMkTyE3CPfnikkm1Y"

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-1.5-pro:generateContent"
)

class InvoiceOCRWizard(models.TransientModel):
    _name = "invoice.ocr.wizard"
    _description = "Invoice OCR Wizard"

    move_id = fields.Many2one("account.move", required=True)
    file = fields.Binary("Invoice File", required=True)
    filename = fields.Char("Filename")

    def action_process(self):
        self.ensure_one()

        raw = base64.b64decode(self.file)
        mime = "application/pdf"
        if self.filename and self.filename.lower().endswith((".png", ".jpg", ".jpeg")):
            mime = "image/jpeg"

        parsed = self._call_gemini(raw, mime)

        if not parsed:
            raise UserError("OCR failed or returned empty data")

        self._apply_to_invoice(parsed, self.move_id)

        return {"type": "ir.actions.act_window_close"}

    def _call_gemini(self, file_bytes, mime):
        payload = {
            "contents": [{
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime,
                            "data": base64.b64encode(file_bytes).decode()
                        }
                    },
                    {
                        "text": (
                            "You are an invoice OCR engine.\n"
                            "Extract invoice data and return STRICT JSON ONLY.\n"
                            "Schema:\n"
                            "{\n"
                            "  supplier_name: string,\n"
                            "  invoice_number: string,\n"
                            "  invoice_date: YYYY-MM-DD,\n"
                            "  due_date: YYYY-MM-DD,\n"
                            "  currency: string,\n"
                            "  lines: [{description, quantity, unit_price}],\n"
                            "  total: number\n"
                            "}\n"
                            "NO MARKDOWN. NO EXPLANATION."
                        )
                    }
                ]
            }]
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        }

        r = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=90)

        if r.status_code != 200:
            _logger.error("Gemini error: %s", r.text)
            raise UserError("Gemini OCR failed")

        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)

    def _apply_to_invoice(self, data, move):
        Partner = self.env["res.partner"]

        # Partner
        partner = None
        if data.get("supplier_name"):
            partner = Partner.search(
                [("name", "ilike", data["supplier_name"])], limit=1
            )
            if not partner:
                partner = Partner.create({"name": data["supplier_name"]})
            move.partner_id = partner.id

        # Dates
        move.invoice_date = data.get("invoice_date")
        move.invoice_date_due = data.get("due_date")
        move.ref = data.get("invoice_number")

        # Currency
        if data.get("currency"):
            currency = self.env["res.currency"].search(
                [("name", "=", data["currency"])], limit=1
            )
            if currency:
                move.currency_id = currency.id

        # Clear lines
        move.line_ids = [(5, 0, 0)]

        # Account fallback
        account = self.env["account.account"].search(
            [("user_type_id.type", "=", "income")], limit=1
        )

        for l in data.get("lines", []):
            self.env["account.move.line"].create({
                "move_id": move.id,
                "name": l.get("description", "Item"),
                "quantity": float(l.get("quantity", 1)),
                "price_unit": float(l.get("unit_price", 0.0)),
                "account_id": account.id,
            })

        move._recompute_dynamic_lines()
