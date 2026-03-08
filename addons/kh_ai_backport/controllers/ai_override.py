# -*- coding: utf-8 -*-
from odoo import models, fields, http, api, _
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
import base64
import logging
import json
import re
import io

_logger = logging.getLogger(__name__)

# محاولة استيراد المكتبات
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

# ==========================================
# 🛠️ 1. حل مشكلة الـ AssertionError (Registry)
# ==========================================
class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'

    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text')
    ], string='Source Type', required=True, default='file')


# ==========================================
# 🚀 2. كودك القديم (الذي يعمل بنجاح تام)
# ==========================================
class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== KH_AI: DEEP ANALYSIS MODE (BILL VS INVOICE) =====')
        
        # 1. جلب المستندات (نفس المنطق السابق)
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()
        mail_message_id = kwargs.get('mail_message_id')
        if mail_message_id:
            message = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if message.exists():
                prompt = html2plaintext(message.body) if message.body else ""
                attachments = message.attachment_ids
        else:
            raw_prompt = kwargs.get('prompt') or kwargs.get('question') or kwargs.get('text') or ''
            prompt = html2plaintext(raw_prompt) if '<' in raw_prompt else raw_prompt
            att_ids = kwargs.get('attachments') or kwargs.get('attachment_ids') or []
            if att_ids:
                attachments = request.env['ir.attachment'].sudo().browse([int(i) for i in att_ids if str(i).isdigit()])

        # 2. البرومبت التحليلي (التفكير قبل التنفيذ)
        system_prompt = """You are a senior auditor for Khales Group. 
        Analyze the document visually and take your time to understand:
        1. ROLES: Who is the SENDER (Vendor) and who is the RECEIVER (Customer)? 
           - If Khales Group or Al Masar is the RECEIVER, this is a 'Vendor Bill' (type: in_invoice).
           - If Khales Group is the SENDER, this is a 'Customer Invoice' (type: out_invoice).
        2. TAXES: Look for VAT or Tax fields. Extract the exact VAT amount.
        3. DATA: Extract Partner Name, TRN (Tax Registration Number), and all Table Lines.

        Return ONLY JSON:
        {
          "move_type": "in_invoice" or "out_invoice",
          "partner_name": "Exact Name",
          "trn": "TRN Number if found",
          "lines": [{"desc": "Item Name", "qty": 1, "price": 100.0}],
          "vat_amount": 0.0
        }"""
        
        gemini_contents = [f"{system_prompt}\n\nUser Question: {prompt}"]
        for att in attachments:
            file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
            if file_bytes:
                gemini_contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

        if not HAS_GENAI: return {'response': "Error: SDK Missing"}
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=gemini_contents)
            result_text = getattr(response, "text", str(response)).strip()
            clean_json_str = re.sub(r'```json|```', '', result_text).strip()

            try:
                data = json.loads(clean_json_str)
                move_type = data.get('move_type')
                
                if move_type in ['in_invoice', 'out_invoice']:
                    env = request.env
                    partner = env['res.partner'].sudo().search([('name', '=ilike', data.get('partner_name'))], limit=1)
                    if not partner:
                        partner = env['res.partner'].sudo().create({
                            'name': data.get('partner_name'),
                            'vat': data.get('trn')
                        })
                    
                    # اختيار الحساب: Expense للمورد و Income للعميل
                    acc_type = 'expense' if move_type == 'in_invoice' else 'income'
                    account = env['account.account'].sudo().search([
                        ('account_type', '=', acc_type), 
                        ('company_ids', 'in', env.company.id)
                    ], limit=1)

                    invoice_lines = []
                    # إضافة أسطر المنتجات
                    for l in data.get('lines', []):
                        invoice_lines.append((0, 0, {
                            'name': l.get('desc'),
                            'quantity': float(l.get('qty', 1.0)),
                            'price_unit': float(l.get('price', 0.0)),
                            'account_id': account.id if account else False
                        }))
                    
                    # إضافة سطر الضريبة بشكل يدوي لضمان الدقة
                    if data.get('vat_amount', 0) > 0:
                        invoice_lines.append((0, 0, {
                            'name': 'VAT (Extracted)',
                            'quantity': 1.0,
                            'price_unit': float(data.get('vat_amount')),
                            'account_id': account.id if account else False
                        }))

                    new_move = env['account.move'].sudo().create({
                        'move_type': move_type,
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_lines,
                        'ref': f"AI-REF-{data.get('trn', '')}"
                    })

                    # إشعار نجاح ذكي
                    friendly_name = "Vendor Bill" if move_type == 'in_invoice' else "Customer Invoice"
                    env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {
                        'title': 'Deep Analysis Complete',
                        'message': f'Success! Created {friendly_name} for {partner.name}',
                        'type': 'success',
                        'sticky': True,
                    })

                    return {
                        'type': 'ir.actions.act_window',
                        'res_model': 'account.move',
                        'res_id': new_move.id,
                        'views': [[False, 'form']],
                        'target': 'current',
                    }

            except Exception: pass
            return {'answer': result_text, 'response': result_text}

        except Exception as e:
            _logger.exception("AI Error")
            return {'response': f"System Error: {e}"}