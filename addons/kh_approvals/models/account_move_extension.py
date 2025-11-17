# top-level imports
import base64, io, json, os
from odoo import models, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

try:
    from google import genai
except ImportError:
    _logger.warning("google-genai library not found. Please install it using 'pip install google-genai'")
    genai = None

try:
    from PIL import Image
except ImportError:
    _logger.warning("Pillow library not found. Please install it using 'pip install Pillow'")
    Image = None

try:
    from pdf2image import convert_from_bytes
except ImportError:
    _logger.warning("pdf2image library not found. Please install it using 'pip install pdf2image'")
    convert_from_bytes = None


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _call_gemini_extract(self, image_bytes, api_key):
        """Call Gemini to extract a JSON with fields. Returns dict or None."""
        if not genai or not Image:
            return None
        try:
            genai.configure(api_key=api_key)
            prompt = (
                "You are a reliable invoice parser. Extract these fields and return **only valid JSON**: "
                "supplier_name, invoice_number, invoice_date (YYYY-MM-DD if possible), due_date, lines (list of {description, qty, unit_price, subtotal}), subtotal, tax, total. "
                "If a field is not present set it to null. Parse numbers as pure numbers (no currency symbols)."
            )
            model = genai.GenerativeModel('gemini-1.5-flash')
            img = Image.open(io.BytesIO(image_bytes))
            response = model.generate_content([prompt, img])

            text = response.text
            if '```json' in text:
                text = text[text.find('```json') + 7:text.rfind('```')]
            parsed = json.loads(text)
            return parsed
        except Exception as e:
            _logger.exception("Gemini extraction failed: %s", e)
            return None

    def _extract_ocr_data(self):
        for move in self:
            try:
                attachment = move.attachment_ids.filtered(lambda a: a.type == 'binary')[:1]
                if not attachment:
                    _logger.debug("No binary attachment for move %s", move.id)
                    continue
                data_b64 = attachment.datas or getattr(attachment, 'db_datas', None)
                if not data_b64:
                    continue
                data = base64.b64decode(data_b64)
                images = []
                if (attachment.mimetype and 'pdf' in (attachment.mimetype or '')) or (attachment.name or '').lower().endswith('.pdf'):
                    if not convert_from_bytes:
                        _logger.warning("pdf2image is not installed, cannot extract from PDF.")
                        continue
                    try:
                        images = convert_from_bytes(data, dpi=200)
                    except Exception as e:
                        _logger.exception("PDF to images conversion failed: %s", e)
                        continue
                else:
                    if not Image:
                        continue
                    images = [Image.open(io.BytesIO(data))]

                api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
                if not api_key:
                    _logger.warning("No Gemini API key configured; skipping Gemini extraction")
                    continue

                if images:
                    img_byte_arr = io.BytesIO()
                    images[0].save(img_byte_arr, format='PNG')
                    img_bytes = img_byte_arr.getvalue()
                    parsed = self._call_gemini_extract(img_bytes, api_key)
                    if parsed:
                        vals = {}
                        if parsed.get('supplier_name'):
                            partner = self.env['res.partner'].search([('name', 'ilike', parsed['supplier_name'])], limit=1)
                            if partner:
                                vals['partner_id'] = partner.id
                        if parsed.get('invoice_date'):
                            vals['invoice_date'] = parsed['invoice_date']
                        if parsed.get('due_date'):
                            vals['invoice_date_due'] = parsed['due_date']
                        if parsed.get('invoice_number') and (not move.name or move.name == '/'):
                            vals['name'] = parsed['invoice_number']
                        
                        if parsed.get('lines'):
                            # This will overwrite existing lines, which is generally what you want when importing from OCR
                            move.invoice_line_ids = [(5, 0, 0)] 
                            lines_to_create = []
                            for ln in parsed['lines']:
                                lines_to_create.append({
                                    'name': ln.get('description') or 'Line',
                                    'quantity': ln.get('qty') or 1.0,
                                    'price_unit': ln.get('unit_price') or ln.get('subtotal') or 0.0,
                                })
                            vals['invoice_line_ids'] = [(0, 0, line) for line in lines_to_create]

                        if vals:
                            move.sudo().write(vals)

            except Exception as e:
                _logger.exception("Gemini invoice extraction error for move %s: %s", move.id, e)