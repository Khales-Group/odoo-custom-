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
    "models/gemini-1.5-flash:generateContent"
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
        b64 = base64.b64encode(file_bytes).decode()

        # 1) LIST AVAILABLE MODELS
        list_url = (
            "https://generativelanguage.googleapis.com/v1beta/models"
            f"?key={GEMINI_API_KEY}"
        )
        r = requests.get(list_url, timeout=30)
        if r.status_code != 200:
            _logger.error("Gemini list models failed: %s", r.text)
            raise UserError("Gemini: cannot list models")

        models = r.json().get("models", [])
        model_name = None

        # 2) PICK FIRST MODEL THAT SUPPORTS generateContent
        for m in models:
            if "generateContent" in m.get("supportedGenerationMethods", []):
                model_name = m["name"]
                _logger.info("Selected Gemini model: %s", model_name)
                break

        if not model_name:
            raise UserError("Gemini: no usable model found")

        # 3) CALL SELECTED MODEL
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"{model_name}:generateContent"
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
                            "You are an OCR parser. Read the attached invoice and extract the following fields as STRICT JSON ONLY:\n"
                            '{"supplier_name": "string", "invoice_number": "string", "invoice_date": "YYYY-MM-DD", "due_date": "YYYY-MM-DD", '
                            '"currency": "string", "lines":[{"description":"string","quantity":number,"unit_price":number}], "total": number}'
                        )
                    }
                ]
            }]
        }

        _logger.info("Sending request to Gemini model: %s", model_name)
        res = requests.post(url, json=payload, timeout=120)

        _logger.info("Gemini OCR Response Status: %s", res.status_code)
        _logger.info("Gemini OCR Response Body: %s", res.text[:2000])  # Log first 2000 chars

        if res.status_code != 200:
            _logger.error("Gemini HTTP error %s: %s", res.status_code, res.text)
            raise UserError("Gemini OCR failed (HTTP error)")

        data = res.json()
        _logger.info("Parsed Gemini response JSON: %s", json.dumps(data, indent=2)[:2000])

        # Extract text from response
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as e:
            _logger.error("Failed to extract text from Gemini response: %s", e)
            raise UserError("Gemini OCR: Invalid response structure")

        # Validate text is not empty
        if not text:
            _logger.error("Gemini OCR returned empty text")
            raise UserError("Gemini OCR returned empty result")

        # Remove markdown formatting if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]  # remove first line (```json or ```)
        if text.endswith("```"):
            text = text.rsplit("\n", 1)[0]  # remove last line (```)

        # Strip whitespace again after markdown removal
        text = text.strip()

        # Try to parse as JSON
        try:
            parsed = json.loads(text)
            _logger.info("Successfully parsed OCR JSON from Gemini")
            return parsed
        except json.JSONDecodeError as e:
            _logger.error("Gemini returned invalid JSON:\nText: %s\nError: %s", text, e)
            raise UserError(f"Gemini OCR returned invalid JSON: {text[:500]}")

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
