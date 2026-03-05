# -*- coding: utf-8 -*-
from odoo import http, models, fields, api, _
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController
import base64
import logging
import json
import re
import io

_logger = logging.getLogger(__name__)

# محاولة استيراد المكتبات لضمان استقرار السيرفر
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

# --- [1] إصلاح مشكلة الـ Registry في الـ Production ---
class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'

    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text')
    ], string='Source Type', required=True, default='file')

class AiAgent(models.Model):
    _inherit = 'ai.agent'

    partner_id = fields.Many2one('res.partner', string="Partner")

    def _execute_query(self, query, history=None, attachment_ids=None, **kwargs):
        """ الاعتراض لضمان استخدام Gemini Vision في البحث والدردشة """
        _logger.info("===== [PROD] GEMINI OVERRIDE: EXECUTE QUERY =====")
        if not HAS_GENAI:
            return super()._execute_query(query, history=history, attachment_ids=attachment_ids, **kwargs)
        
        # استدعاء الكنترولر للحصول على رد موحد
        res = request.env['ai.controller.override'].generate_response(prompt=query, attachment_ids=attachment_ids)
        return res.get('answer') or res.get('response')

# --- [2] الكنترولر الذكي: يدعم الدردشة + استخراج الفواتير والبيلات ---
class AIControllerOverride(AIController):

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('===== KH_AI: ADVANCED HYBRID MODE (CHAT + AUDITOR) =====')
        
        final_msg = "عذراً، لم أستطع معالجة طلبك الآن. يرجى التأكد من المرفقات."
        prompt = ""
        attachments = request.env['ir.attachment'].sudo()

        try:
            # 1. تجميع البيانات والمرفقات
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

            # 2. إعداد البرومبت بناءً على الحالة
            if has_files:
                # نمط التدقيق المحاسبي (Auditor Mode)
                system_prompt = """You are a senior auditor for Khales Group. Analyze document visually:
                - Identify if it's a Vendor Bill (Khales is receiving) or Customer Invoice (Khales is sending).
                - Extract Partner Name, TRN, VAT Amount, and all Line Items.
                - Return ONLY JSON: {"action": "create_move", "move_type": "in_invoice" or "out_invoice", "partner_name": "X", "trn": "123", "vat": 5.0, "lines": [{"desc": "A", "qty": 1, "price": 10}]}"""
            else:
                # نمط الدردشة (Conversational Mode) - هذا سيحل مشكلة "مرحبا"
                system_prompt = "You are a helpful AI collaborator for Khales Group. Chat naturally and friendly."

            # 3. الاتصال بـ Gemini API
            api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
            if not api_key:
                return {'answer': "خطأ: API Key مفقود", 'response': "API Key Missing"}

            client = genai.Client(api_key=api_key)
            contents = [f"{system_prompt}\n\nUser: {prompt}"]
            
            for att in attachments:
                file_bytes = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if file_bytes:
                    contents.append(types.Part.from_bytes(data=file_bytes, mime_type=att.mimetype or 'application/pdf'))

            response = client.models.generate_content(model="gemini-2.5-flash", contents=contents)
            final_msg = getattr(response, "text", str(response)).strip()

            # 4. معالجة الـ JSON لإنشاء المستند
            if has_files and "{" in final_msg:
                try:
                    clean_json = re.sub(r'```json|```', '', final_msg).strip()
                    data = json.loads(clean_json)
                    
                    if data.get('action') == 'create_move':
                        env = request.env
                        m_type = data.get('move_type', 'in_invoice')
                        partner = env['res.partner'].sudo().search([('name', '=ilike', data.get('partner_name'))], limit=1)
                        if not partner:
                            partner = env['res.partner'].sudo().create({'name': data.get('partner_name'), 'vat': data.get('trn')})
                        
                        # اختيار الحساب: Expense للبيل و Income للفاتورة
                        acc_type = 'expense' if m_type == 'in_invoice' else 'income'
                        account = env['account.account'].sudo().search([('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)
                        
                        inv_lines = []
                        for l in data.get('lines', []):
                            inv_lines.append((0, 0, {'name': l.get('desc'), 'quantity': float(l.get('qty', 1)), 'price_unit': float(l.get('price', 0)), 'account_id': account.id}))
                        
                        if data.get('vat', 0) > 0:
                            inv_lines.append((0, 0, {'name': 'VAT (AI Extracted)', 'quantity': 1, 'price_unit': float(data.get('vat')), 'account_id': account.id}))

                        new_move = env['account.move'].sudo().create({'move_type': m_type, 'partner_id': partner.id, 'invoice_line_ids': inv_lines})

                        # إرسال تنبيه أخضر (Sticky Notification)
                        f_name = "Vendor Bill" if m_type == 'in_invoice' else "Customer Invoice"
                        env['bus.bus']._sendone(env.user.partner_id, 'simple_notification', {
                            'title': 'AI Success', 'message': f'Created {f_name} for {partner.name}', 'type': 'success', 'sticky': True,
                        })

                        return {
                            'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': new_move.id,
                            'views': [[False, 'form']], 'target': 'current',
                            'answer': f"✅ تم إنشاء {f_name} بنجاح.", 'response': "جاري التحويل..."
                        }
                except: pass

            return {'answer': final_msg, 'response': final_msg, 'status': 'success'}

        except Exception as e:
            _logger.exception("CRITICAL AI ERROR")
            return {'answer': f"Error: {str(e)}", 'response': f"System Error: {e}"}