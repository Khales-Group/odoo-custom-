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
        """
        Robust Gemini caller:
        - tries several model endpoints known to support file input
        - tries two payload shapes (text-first and file-first)
        - logs responses and returns parsed JSON on success
        - raises a UserError with concise diagnostics on total failure
        """
        # small helper to truncate long texts for logs
        def short(s, n=1000):
            if not isinstance(s, str):
                s = str(s)
            return (s[:n] + '...') if len(s) > n else s

        # Models to try (order matters)
        models = [
            "gemini-1.5-flash",
            "gemini-1.0-pro-vision",
            "gemini-1.5-pro",  # sometimes present, sometimes not
        ]

        # Two payload shapes: text-first and file-first.
        prompt = (
            "You are an invoice OCR engine.\n"
            "Extract invoice data and return STRICT JSON ONLY.\n\n"
            "Schema:\n"
            '{\n'
            '  "supplier_name": "string",\n'
            '  "invoice_number": "string",\n'
            '  "invoice_date": "YYYY-MM-DD",\n'
            '  "due_date": "YYYY-MM-DD",\n'
            '  "currency": "string",\n'
            '  "lines": [ { "description": "string", "quantity": number, "unit_price": number } ],\n'
            '  "total": number\n'
            '}\n\n'
            "Rules:\n- RETURN ONLY JSON, no commentary, no markdown.\n"
        )

        # candidate payload constructors (two variations)
        def payload_text_first(mime, b64):
            return {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inlineData": {"mimeType": mime, "data": b64}
                            }
                        ]
                    }
                ]
            }

        def payload_file_first(mime, b64):
            return {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "inlineData": {"mimeType": mime, "data": b64}
                            },
                            {"text": prompt}
                        ]
                    }
                ]
            }

        b64 = base64.b64encode(file_bytes).decode()

        # store diagnostic per attempt
        attempts = []

        for model in models:
            url_base = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{model}:generateContent"
            )
            # MUST pass key as query param for API-key auth
            url = f"{url_base}?key={GEMINI_API_KEY}"

            for payload_fn in (payload_text_first, payload_file_first):
                payload = payload_fn(mime, b64)
                try:
                    response = requests.post(url, json=payload, timeout=120)
                except Exception as e:
                    # network-level error
                    _logger.error("Gemini request exception for model %s: %s", model, e)
                    attempts.append({
                        "model": model,
                        "status": "exception",
                        "detail": short(str(e), 2000)
                    })
                    continue

                status = response.status_code
                body = None
                try:
                    body = response.text
                except Exception:
                    body = "<unreadable body>"

                _logger.error(
                    "Gemini attempt model=%s status=%s body=%s",
                    model, status, short(body, 2000)
                )

                attempts.append({
                    "model": model,
                    "status": status,
                    "body": short(body, 2000)
                })

                # If HTTP error, try next
                if status != 200:
                    # continue to next attempt
                    continue

                # parse JSON result and extract content
                try:
                    result = response.json()
                except Exception as e:
                    _logger.error("Gemini: failed to parse JSON response for model %s: %s", model, e)
                    attempts.append({
                        "model": model,
                        "status": "invalid_json",
                        "detail": short(str(e), 2000)
                    })
                    continue

                # try to find the textual JSON candidate
                try:
                    # typical path: candidates[0].content.parts[0].text
                    cand = result.get("candidates") or []
                    if cand and isinstance(cand, list):
                        # iterate candidates to find a valid text part
                        for c in cand:
                            content = c.get("content", {})
                            parts = content.get("parts", []) if isinstance(content, dict) else []
                            for p in parts:
                                # prefer 'text' part which should contain our JSON
                                if p.get("text"):
                                    text = p.get("text")
                                    text_stripped = text.strip()
                                    # try parse
                                    try:
                                        parsed = json.loads(text_stripped)
                                        _logger.info("Gemini parsed JSON successfully using model %s", model)
                                        return parsed
                                    except Exception as e:
                                        # if not JSON, log and continue search
                                        _logger.error("Gemini candidate text not valid JSON: %s", e)
                                        attempts.append({
                                            "model": model,
                                            "status": "invalid_json_candidate",
                                            "candidate_preview": short(text_stripped, 2000),
                                            "parse_error": short(str(e), 2000)
                                        })
                                        # continue to next part/candidate
                    # fallback: sometimes content may be under 'output' keys - try to find any text value
                    def find_text_values(obj):
                        texts = []
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if isinstance(v, str):
                                    texts.append(v)
                                else:
                                    texts.extend(find_text_values(v))
                        elif isinstance(obj, list):
                            for item in obj:
                                texts.extend(find_text_values(item))
                        return texts

                    for txt in find_text_values(result)[:10]:
                        try:
                            parsed = json.loads(txt.strip())
                            _logger.info("Gemini parsed JSON from fallback text using model %s", model)
                            return parsed
                        except Exception:
                            continue

                    # If we get here, 200 but no valid JSON candidate
                    attempts.append({
                        "model": model,
                        "status": "200_but_no_json",
                        "response_preview": short(json.dumps(result), 2000)
                    })
                    # try next model/shape
                except Exception as e:
                    _logger.error("Unexpected processing error for model %s: %s", model, e)
                    attempts.append({
                        "model": model,
                        "status": "processing_exception",
                        "detail": short(str(e), 2000)
                    })
                    continue

        # If we tried everything and none succeeded, raise a helpful UserError with diagnostics
        msg_lines = [
            "Gemini OCR failed (HTTP error / no valid JSON). Diagnostic summary of attempts (most recent first):"
        ]
        # show last 6 attempts
        for a in attempts[-6:][::-1]:
            line = f"- model={a.get('model')} status={a.get('status')}"
            if 'body' in a:
                line += f" body_preview={a.get('body')}"
            if 'candidate_preview' in a:
                line += f" candidate_preview={a.get('candidate_preview')}"
            msg_lines.append(line)
        msg_lines.append("Check: API key validity, Generative Language API enabled, API key restrictions (remove HTTP referrer restrictions), and project billing.")
        msg = "\n".join(msg_lines)
        _logger.error(msg)
        # Provide shorter user-facing message while showing the top cause
        raise UserError(_("Gemini OCR failed. See server logs for details."))

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
