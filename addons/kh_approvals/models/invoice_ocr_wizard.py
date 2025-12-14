from odoo import models, fields, _
from odoo.exceptions import UserError
import base64
import requests
import json
import logging

_logger = logging.getLogger(__name__)

# ⚠️ For production: move this to ir.config_parameter
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

    # ------------------------------------------------------------
    # Main action
    # ------------------------------------------------------------
    def action_process(self):
        self.ensure_one()

        if not self.file:
            raise UserError("No file uploaded")

        raw = base64.b64decode(self.file)

        # MIME detection
        if not self.filename:
            raise UserError("Filename missing")

        name = self.filename.lower()
        if name.endswith(".pdf"):
            mime = "application/pdf"
        elif name.endswith(".png"):
            mime = "image/png"
        elif name.endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        else:
            raise UserError("Unsupported file type")

        parsed = self._call_gemini(raw, mime)

        if not parsed:
            raise UserError("OCR returned no data")

        self._apply_to_invoice(parsed, self.move_id)

        return {"type": "ir.actions.act_window_close"}

    # ------------------------------------------------------------
    # Gemini call (FIXED)
    # ------------------------------------------------------------
    def _call_gemini(self, file_bytes, mime):
        prompt = (
            "You are an invoice OCR engine.\n"
            "Extract invoice data and return STRICT JSON ONLY.\n\n"
            "Schema:\n"
            "{\n"
            '  "supplier_name": "string",\n'
            '  "invoice_number": "string",\n'
            '  "invoice_date": "YYYY-MM-DD",\n'
            '  "due_date": "YYYY-MM-DD",\n'
            '  "currency": "AED",\n'
            '  "lines": [\n'
            "    {\n"
            '      "description": "string",\n'
            '      "quantity": number,\n'
            '      "unit_price": number\n'
            "    }\n"
            "  ],\n"
            '  "total": number\n'
            "}\n\n"
            "Rules:\n"
            "- NO markdown\n"
            "- NO explanation\n"
            "- ONLY valid JSON\n"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(file_bytes).decode()
                            }
                        }
                    ]
                }
            ]
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        }

        response = requests.post(
            GEMINI_URL,
            headers=headers,
            json=payload,
            timeout=120
        )

        if response.status_code != 200:
            _logger.error(
                "Gemini HTTP %s: %s",
                response.status_code,
                response.text
            )
            raise UserError("Gemini OCR failed (HTTP error)")

        result = response.json()

        try:
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except Exception as e:
            _logger.error(
                "Gemini response parse failed: %s\nFull response:\n%s",
                e,
                json.dumps(result, indent=2)
            )
            raise UserError("Gemini OCR failed (invalid JSON)")

    # ------------------------------------------------------------
    # Apply parsed data to invoice (Odoo 18 safe)
    # ------------------------------------------------------------
    def _apply_to_invoice(self, data, move):
        Partner = self.env["res.partner"]

        # Partner
        if data.get("supplier_name"):
            partner = Partner.search(
                [("name", "ilike", data["supplier_name"])],
                limit=1
            )
            if not partner:
                partner = Partner.create({"name": data["supplier_name"]})
            move.partner_id = partner.id

        # Dates & reference
        move.invoice_date = data.get("invoice_date")
        move.invoice_date_due = data.get("due_date")
        move.ref = data.get("invoice_number")

        # Currency
        if data.get("currency"):
            currency = self.env["res.currency"].search(
                [("name", "=", data["currency"])],
                limit=1
            )
            if currency:
                move.currency_id = currency.id

        # Remove old lines
        move.invoice_line_ids.unlink()

        # Account fallback (expense for vendor bills)
        account = self.env["account.account"].search(
            [("account_type", "=", "expense")],
            limit=1
        )
        if not account:
            raise UserError("No expense account found")

        for line in data.get("lines", []):
            self.env["account.move.line"].create({
                "move_id": move.id,
                "name": line.get("description", "Item"),
                "quantity": float(line.get("quantity", 1)),
                "price_unit": float(line.get("unit_price", 0.0)),
                "account_id": account.id,
            })

        # ✅ Odoo 18 safe recompute
        move._compute_amount()
