# -*- coding: utf-8 -*-
from odoo import models, api, fields, _
import base64
import json
import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"

    def _extract_ocr_data(self):
        """Override Odoo OCR pipeline to use Gemini. Falls back to super() if anything missing."""
        for move in self:
            # take first binary attachment (same behaviour as default OCR)
            attachment = move.attachment_ids.filtered(lambda a: a.type == 'binary')[:1]
            if not attachment:
                # nothing to do, let super handle (or just continue)
                continue
            attachment = attachment[0]

            try:
                file_bytes = base64.b64decode(attachment.datas or b'')
            except Exception:
                _logger.exception("Failed to decode attachment %s for move %s", attachment.id, move.id)
                # fallback: let Odoo's default OCR try (if present)
                try:
                    super(AccountMove, move)._extract_ocr_data()
                except Exception:
                    pass
                continue

            # get API key from ir.config_parameter (DO NOT hardcode keys)
            gemini_key = self.env['ir.config_parameter'].sudo().get_param('your_module.gemini_api_key')
            if not gemini_key:
                _logger.warning("Gemini API key not configured. Falling back to super().")
                try:
                    super(AccountMove, move)._extract_ocr_data()
                except Exception:
                    pass
                continue

            # Build prompt - keep it strict and request JSON only
            prompt = """
You are an invoice OCR assistant. Given file content, return STRICT JSON only with this structure:
{
  "vendor": "Vendor name",
  "invoice_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "total": 0.0,
  "vat": 0.0,
  "lines": [
    {"description": "", "qty": 1, "unit_price": 0.0}
  ]
}
If a field is missing, return null for strings or 0 for numbers.
"""

            # Call Gemini (using google.generativeai library if available)
            try:
                # Try the official python client if installed
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)

                encoded = base64.b64encode(file_bytes).decode()
                mime = attachment.mimetype or 'application/pdf'
                model = genai.GenerativeModel("gemini-1.5-flash")
                result = model.generate_content([
                    {"mime_type": mime, "data": encoded},
                    prompt
                ])

                text = result.text
                parsed = json.loads(text)

            except Exception as exc:
                _logger.exception("Gemini OCR failed for attachment %s (move %s): %s", attachment.id, move.id, exc)
                # On failure, fallback to super so default OCR still may run
                try:
                    super(AccountMove, move)._extract_ocr_data()
                except Exception:
                    pass
                continue

            # Apply parsed data into the invoice safely
            try:
                move.sudo()._fill_invoice_from_ai(parsed)
            except Exception:
                _logger.exception("Failed to write AI data to move %s", move.id)
                # don't raise, continue with other moves
                continue

    def _fill_invoice_from_ai(self, data):
        """Map the parsed Gemini JSON into Odoo fields."""
        for move in self:
            partner_id = False
            vendor = data.get('vendor') if isinstance(data, dict) else None
            if vendor:
                partner = self.env['res.partner'].sudo().search([('name', 'ilike', vendor)], limit=1)
                if partner:
                    partner_id = partner.id
                else:
                    # Optionally: create partner
                    # partner = self.env['res.partner'].sudo().create({'name': vendor})
                    # partner_id = partner.id
                    pass

            invoice_date = data.get('invoice_date')
            due_date = data.get('due_date')
            total = data.get('total') or 0.0

            # Lines mapping
            lines = []
            for ln in data.get('lines', []) or []:
                desc = ln.get('description') or ''
                qty = ln.get('qty') or 1
                unit_price = ln.get('unit_price') or 0.0
                lines.append((0, 0, {
                    'name': desc,
                    'quantity': qty,
                    'price_unit': unit_price,
                }))

            vals = {}
            if partner_id:
                vals['partner_id'] = partner_id
            if invoice_date:
                vals['invoice_date'] = invoice_date
            if due_date:
                vals['invoice_date_due'] = due_date
            if lines:
                vals['invoice_line_ids'] = lines

            # Write as sudo to avoid access/record rule issues
            if vals:
                move.sudo().write(vals)
