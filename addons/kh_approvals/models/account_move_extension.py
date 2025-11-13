# -*- coding: utf-8 -*-
import base64
import logging
import json
import requests

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_gemini_api_key(self):
        """Fetches the Gemini API key from Odoo's system parameters."""
        return self.env['ir.config_parameter'].sudo().get_param('gemini.api_key')

    def _call_gemini_api(self, attachment):
        """
        Calls the Google Gemini API to analyze the invoice attachment.
        """
        api_key = self._get_gemini_api_key()
        if not api_key:
            _logger.error("Gemini API key is not set in system parameters (gemini.api_key).")
            return {}

        headers = {
            'Content-Type': 'application/json',
        }
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": """
                            You are an expert accounting assistant. Analyze the following invoice document. 
                            Extract the following information:
                            - vendor_name: The name of the company that sent the invoice.
                            - invoice_date: The date the invoice was issued.
                            - due_date: The date the payment is due.
                            - invoice_number: The unique identifier for the invoice.
                            - total_amount: The final total amount, including taxes and fees.
                            - tax_amount: The total amount of tax.
                            - line_items: A list of all items, where each item has a "description", "quantity", "unit_price", and "subtotal".
                            
                            Return this information ONLY as a valid JSON object. Do not include any other text, explanations, or markdown formatting in your response.
                            """
                        },
                        {
                            "inline_data": {
                                "mime_type": attachment.mimetype,
                                "data": attachment.datas.decode('utf-8')
                            }
                        }
                    ]
                }
            ]
        }

        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent?key={api_key}",
                headers=headers,
                data=json.dumps(payload),
                timeout=60
            )
            response.raise_for_status()
            
            response_json = response.json()
            # The actual content is nested. We need to extract the JSON string.
            content_text = response_json['candidates'][0]['content']['parts'][0]['text']
            return json.loads(content_text)

        except requests.exceptions.RequestException as e:
            _logger.error("Failed to call Gemini API: %s", e)
        except (ValueError, KeyError) as e:
            _logger.error("Failed to parse Gemini API response: %s", e)
        
        return {}

    @api.model
    def _create_invoice_from_attachment(self, attachment_ids=None):
        """
        Overrides the default method to create a vendor bill from an attachment.
        This new method will use Gemini to extract data from the document.
        """
        invoices = super(AccountMove, self)._create_invoice_from_attachment(attachment_ids=attachment_ids)
        
        if not invoices or not self.env.context.get('default_move_type') == 'in_invoice':
            return invoices

        attachment = self.env['ir.attachment'].browse(attachment_ids[0])
        if not attachment.datas:
            return invoices

        extracted_data = self._call_gemini_api(attachment)

        if not extracted_data:
            _logger.warning("Could not extract data from attachment %s using Gemini.", attachment.name)
            return invoices

        invoice_vals = {}
        if extracted_data.get('vendor_name'):
            partner = self.env['res.partner'].search([('name', 'ilike', extracted_data['vendor_name'])], limit=1)
            if partner:
                invoice_vals['partner_id'] = partner.id

        if extracted_data.get('invoice_date'):
            invoice_vals['invoice_date'] = extracted_data['invoice_date']
        
        if extracted_data.get('due_date'):
            invoice_vals['invoice_date_due'] = extracted_data['due_date']

        if extracted_data.get('invoice_number'):
            invoice_vals['ref'] = extracted_data['invoice_number']

        if extracted_data.get('line_items'):
            invoice_vals['invoice_line_ids'] = [(5, 0, 0)]
            for item in extracted_data['line_items']:
                line_vals = {
                    'name': item.get('description'),
                    'quantity': item.get('quantity', 1),
                    'price_unit': item.get('unit_price', 0),
                }
                invoice_vals['invoice_line_ids'].append((0, 0, line_vals))

        if invoices and invoice_vals:
            invoices.write(invoice_vals)
            _logger.info("Successfully updated invoice %s with data from Gemini.", invoices.name)

        return invoices
# ===================================================================
# === THE FINAL, CORRECT "AUTOMATIC SYNC" SCRIPT (USE THIS ONE) ===
# ===================================================================

# --- PART 1: AUTO-COMMIT AND PUSH YOUR WORK ---

# Go to your separate code folder
cd C:\Users\Khales\odoo-custom-

# Get on your working branch
git checkout approvals-test2
git pull

# Add any unsaved changes you have
git add .

# Commit your changes with an automatic message
git commit -m "Auto-sync: Save latest local edits"

# Push your new code to your "source of truth" branch
git push origin approvals-test2


# --- PART 2: AUTO-UPDATE AND REBUILD THE ODOO.SH PROJECT ---

# Go to the main Odoo.sh project folder
cd C:\Users\Khales\Khales-System

# !! IMPORTANT !! Get on your current branch
git checkout final-activity-updates8
git pull

# Go into the submodule to sync it
cd Khales-Group/odoo-custom-

# Fetch the latest information from the server
git fetch origin

# THIS IS THE CORRECT COMMAND THAT FIXES THE PROBLEM:
# Force the submodule to become an EXACT copy of your 'approvals-test2' branch.
git reset --hard origin/approvals-test2

# Go back to the main project
cd ../../

# Commit the pointer update
git add Khales-Group/odoo-custom-
git commit -m "Auto-sync: Update submodule from approvals-test2"

# Create an empty commit to guarantee a rebuild
git commit --allow-empty -m "FORCE REBUILD"

# Push everything to Odoo.sh
# !! IMPORTANT !! Use your current branch name
git push -u origin final-activity-updates8


# --- SCRIPT FINISHED ---\