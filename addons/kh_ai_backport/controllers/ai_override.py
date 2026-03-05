# -*- coding: utf-8 -*-
from odoo import http, models, fields, api
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
import base64
import logging
import json
import re

_logger = logging.getLogger(__name__)

# --- [1] إصلاح خطأ الـ AssertionError في الـ Production ---
# أحياناً موديول أودو الأساسي بيفقد تعريفات الـ Selection في حقل الـ type
class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'

    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text')
    ], string='Source Type', required=True, default='file')

# --- [2] الكنترولر المعدل والنهائي ---
class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== KH_AI: FULL PRODUCTION STABLE MODE =====')
        
        # إعداد الرد الافتراضي لمنع الردود الفارغة (5-byte error)
        final_msg = "أهلاً بك، لم أستطع معالجة الطلب حالياً. هل يمكنك إعادة المحاولة؟"
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        try:
            # 1. تجميع البيانات والمرفقات من الشات
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

            has_files = len(attachments) > 0

            # 2. إعداد البرومبت بناءً على وجود ملفات
            if has_files:
                # نمط التدقيق المحاسبي العميق
                system_prompt = """You are a senior auditor for Khales Group. 
                STRICT RULES:
                1. If Khales Group or Al Masar is the receiver: create a Vendor Bill (in_invoice).
                2. If Khales Group is the sender: create a Customer Invoice (out_invoice).
                3. Extract ALL table lines (Description, Qty, Price).
                4. Extract VAT amount and Supplier TRN.
                5. Return ONLY a valid JSON object.
                JSON: {"action": "create_move", "move_type": "in_invoice", "partner_name": "X", "trn": "123", "vat": 5.0, "lines": [{"desc": "A", "qty": 1, "price": 10}]}"""
            else:
                # نمط الدردشة الطبيعية (Conversational)
                system_prompt = "You are a helpful AI assistant for Nezar at Khales Group. Speak naturally and friendly. Don't mention JSON."

            # 3. الاتصال بـ Gemini API
            from google import genai
            from google.genai import types
            api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
            
            if not api_key:
                _logger.error("Gemini API Key is missing!")
                return {'answer': "برجاء ضبط مفتاح الـ API في الإعدادات أولاً.", 'response': "API Key Missing"}

            client = genai.Client(api_key=api_key)
            contents = [f"{system_prompt}\n\nUser Message: {prompt}"]
            
            for att in attachments:
                file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if file_bytes:
                    contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

            response = client.models.generate_content(model="gemini-2.5-flash", contents=contents)
            final_msg = getattr(response, "text", str(response)).strip()

            # 4. محاولة معالجة الـ JSON لإنشاء الفاتورة
            if has_files and "{" in final_msg:
                try:
                    clean_json = re.sub(r'```json|```', '', final_msg).strip()
                    data = json.loads(clean_json)
                    
                    if data.get('action') == 'create_move':
                        env = request.env
                        move_type = data.get('move_type', 'in_invoice')
                        
                        # جلب/إنشاء الطرف الآخر
                        partner = env['res.partner'].sudo().search([('name', '=ilike', data.get('partner_name'))], limit=1)
                        if not partner:
                            partner = env['res.partner'].sudo().create({
                                'name': data.get('partner_name'),
                                'vat': data.get('trn')
                            })
                        
                        # تحديد نوع الحساب بناءً على نوع الحركة
                        acc_type = 'expense' if move_type == 'in_invoice' else 'income'
                        account = env['account.account'].sudo().search([
                            ('account_type', '=', acc_type), 
                            ('company_ids', 'in', env.company.id)
                        ], limit=1)
                        
                        invoice_lines = []
                        # إضافة بنود الجدول
                        for l in data.get('lines', []):
                            invoice_lines.append((0, 0, {
                                'name': l.get('desc', 'AI Extracted'),
                                'quantity': float(l.get('qty', 1)),
                                'price_unit': float(l.get('price', 0)),
                                'account_id': account.id if account else False
                            }))
                        
                        # إضافة سطر الضريبة (VAT) لضمان مطابقة الإجمالي
                        if data.get('vat', 0) > 0:
                            invoice_lines.append((0, 0, {
                                'name': 'VAT (AI Extracted)',
                                'quantity': 1.0,
                                'price_unit': float(data.get('vat')),
                                'account_id': account.id if account else False
                            }))

                        # إنشاء السجل في أودو
                        new_move = env['account.move'].sudo().create({
                            'move_type': move_type,
                            'partner_id': partner.id,
                            'invoice_line_ids': invoice_lines,
                            'ref': f"AI-REF-{data.get('trn', 'N/A')}"
                        })

                        # إرسال تنبيه رسمي فوق في الشاشة (Sticky Notification)
                        friendly_name = "Vendor Bill" if move_type == 'in_invoice' else "Customer Invoice"
                        env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {
                            'title': 'AI SUCCESS',
                            'message': f'Created {friendly_name} for {partner.name}',
                            'type': 'success', 'sticky': True,
                        })

                        # 🚀 إرجاع الأكشن لفتح الفاتورة فوراً في المتصفح
                        return {
                            'type': 'ir.actions.act_window',
                            'res_model': 'account.move',
                            'res_id': new_move.id,
                            'views': [[False, 'form']],
                            'target': 'current',
                            'answer': f"✅ تم إنشاء {friendly_name} بنجاح.",
                            'response': f"جاري التحويل للفاتورة #{new_move.id}..."
                        }
                except Exception as je:
                    _logger.error(f"JSON Parsing failed: {je}")

            # الرد النهائي في حال الدردشة العادية أو فشل الـ JSON
            return {'answer': final_msg, 'response': final_msg, 'status': 'success'}

        except Exception as e:
            _logger.exception("CRITICAL AI CONTROLLER ERROR")
            return {'answer': f"System Error: {str(e)}", 'response': "Check Odoo Logs"}