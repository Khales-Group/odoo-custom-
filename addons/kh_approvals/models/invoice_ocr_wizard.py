from odoo import models, fields, _
from odoo.exceptions import UserError
import base64
import requests
import json
import logging

_logger = logging.getLogger(__name__)

# ⚠️ For production: move this to ir.config_parameter
GEMINI_API_KEY = "AIzaSyByJEePnY633napEEYMkTyE3CPfnikkm1Y"
GEMINI_MODEL = "models/gemini-1.5-pro-latest"


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
        b64 = base64.b64encode(file_bytes).decode()

        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"{GEMINI_MODEL}:generateContent"
            f"?key={GEMINI_API_KEY}"
        )

        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime,
                            "data": b64
                        }
                    },
                    {
                        "text": (
                            "You are a financial document extraction engine.\n"
                            "Return VALID JSON ONLY. No markdown. No commentary.\n"
                            "If unsure, return null.\n\n"
                            "{"
                            "\"supplier_name\": string | null,"
                            "\"invoice_number\": string | null,"
                            "\"invoice_date\": \"YYYY-MM-DD\" | null,"
                            "\"due_date\": \"YYYY-MM-DD\" | null,"
                            "\"currency\": string | null,"
                            "\"lines\": ["
                                "{"
                                "\"description\": string,"
                                "\"quantity\": number,"
                                "\"unit_price\": number"
                                "}"
                            "],"
                            "\"subtotal\": number | null,"
                            "\"vat\": number | null,"
                            "\"total\": number | null"
                            "}"
                        )
                    }
                ]
            }],
            "generationConfig": {
                "temperature": 0.0,
                "topP": 0.1,
                "maxOutputTokens": 2048
            }
        }

        res = requests.post(url, json=payload, timeout=120)

        if res.status_code != 200:
            raise UserError(f"Gemini OCR failed: {res.text}")

        data = res.json()

        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            raise UserError("Gemini returned unexpected structure")

        text = text.strip()

        # hard JSON validation
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            raise UserError(f"Gemini returned invalid JSON:\n{text[:500]}")

        return parsed

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
