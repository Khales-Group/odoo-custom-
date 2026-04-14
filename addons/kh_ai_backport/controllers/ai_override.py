# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║           KHALES AI - HYBRID AGENT ENGINE v2.0                  ║
║           Odoo 19 | Gemini 2.5 Flash | Clean Architecture        ║
╚══════════════════════════════════════════════════════════════════╝

المقاربة: Hybrid
  - القراءة  → Dynamic ORM  (AI يختار الموديل بحرية)
  - الكتابة  → Fixed Tools  (أدوات محددة وآمنة)
  - الأمان   → صلاحيات المستخدم الحقيقي (بدون sudo للكتابة)
  - البحث    → Gemini Grounding (مدمج، بدون API خارجي)
"""

import base64
import json
import logging
import re

from markupsafe import Markup

from odoo import fields, http, models
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.tools import html2plaintext

# ── Odoo AI base ──────────────────────────────────────────────────
from odoo.addons.ai.controllers.main import AIController

_logger = logging.getLogger(__name__)

# ── Google GenAI ──────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False
    _logger.warning("KH_AI: google-genai not installed. pip install google-genai")


# ══════════════════════════════════════════════════════════════════
#  MODEL EXTENSION (unchanged from original)
# ══════════════════════════════════════════════════════════════════
class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'
    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text'),
    ], string='Source Type', required=True, default='file')


# ══════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════

# الموديلات المسموح للـ AI يقرأ منها ديناميكياً
READABLE_MODELS = {
    'res.partner':       ['name', 'email', 'phone', 'vat', 'is_company', 'street', 'city'],
    'crm.lead':          ['name', 'partner_name', 'email_from', 'phone', 'stage_id', 'description'],
    'account.move':      ['name', 'partner_id', 'amount_total', 'state', 'move_type', 'invoice_date'],
    'purchase.order':    ['name', 'partner_id', 'amount_total', 'state', 'date_order'],
    'sale.order':        ['name', 'partner_id', 'amount_total', 'state', 'date_order'],
    'project.task':      ['name', 'project_id', 'user_ids', 'stage_id', 'date_deadline'],
    'hr.employee':       ['name', 'job_title', 'department_id', 'work_email'],
    'product.product':   ['name', 'list_price', 'qty_available', 'categ_id'],
    'stock.picking':     ['name', 'partner_id', 'state', 'scheduled_date', 'picking_type_id'],
    'account.bank.statement': ['name', 'date', 'balance_start', 'balance_end_real', 'journal_id'],
}

AGENT_PERSONA = "🤖 [Khales AI]"

SYSTEM_INSTRUCTION = f"""You are '{AGENT_PERSONA}', an elite ERP assistant and business consultant built into Odoo 19.

## IDENTITY RULES
- Start EVERY reply with "{AGENT_PERSONA}: "
- Be concise, professional, and helpful
- Support Arabic and English equally

## TOOL SELECTION RULES

### READ Tool (ai_dynamic_read):
Use when user asks to "find", "search", "show", "list", "ابحث", "دور", "اعرض", "كم عدد"
- You choose the model_name from your knowledge of Odoo models
- You can filter by any field

### WRITE Tools (Fixed):
Only use when user EXPLICITLY commands creation/modification:
- ai_create_lead        → "أنشئ lead", "create lead"
- ai_create_invoice     → "أنشئ فاتورة", "create invoice/bill"
- ai_create_bank_stmt   → "أنشئ كشف بنكي", "bank statement"
- ai_create_rfq         → "أنشئ RFQ", "اطلب من مورد"

### SEARCH + CREATE Pattern:
If user asks to create RFQ for a NEW vendor:
1. First call ai_dynamic_read on res.partner to check if vendor exists
2. Then call ai_create_rfq with the result

### Google Search (Grounding):
For external info (market prices, supplier contacts, news) — 
answer directly using your grounding capability, no tool needed.

## SAFETY
- Never invent data
- Never guess at financial amounts
- Ask for clarification if the command is ambiguous
"""


# ══════════════════════════════════════════════════════════════════
#  TOOL DEFINITIONS
# ══════════════════════════════════════════════════════════════════

def _build_tools() -> types.Tool:
    """بناء كل أدوات الـ AI في مكان واحد"""

    # ── READ (Dynamic) ────────────────────────────────────────────
    ai_dynamic_read = types.FunctionDeclaration(
        name="ai_dynamic_read",
        description=(
            "Search/read any Odoo record dynamically. "
            "Use for find/search/list/show requests. "
            "You choose model_name and filters."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "model_name": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Odoo technical model name. Examples: "
                        "'res.partner', 'crm.lead', 'account.move', "
                        "'purchase.order', 'sale.order', 'project.task', "
                        "'hr.employee', 'product.product', 'stock.picking'"
                    )
                ),
                "keyword": types.Schema(
                    type=types.Type.STRING,
                    description="Text to search in 'name' field (optional)"
                ),
                "filters": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Additional Odoo domain as JSON string. "
                        "Example: '[[\"state\", \"=\", \"draft\"]]' "
                        "Leave empty if no extra filter needed."
                    )
                ),
                "limit": types.Schema(
                    type=types.Type.INTEGER,
                    description="Max records to return (default 10, max 50)"
                ),
            },
            required=["model_name"]
        )
    )

    # ── CREATE LEAD ───────────────────────────────────────────────
    ai_create_lead = types.FunctionDeclaration(
        name="ai_create_lead",
        description="Create a CRM Lead/Opportunity. Only when explicitly commanded.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "name":            types.Schema(type=types.Type.STRING, description="Lead title/subject"),
                "partner_name":    types.Schema(type=types.Type.STRING, description="Customer name"),
                "email_from":      types.Schema(type=types.Type.STRING),
                "phone":           types.Schema(type=types.Type.STRING),
                "description":     types.Schema(type=types.Type.STRING),
                "expected_revenue":types.Schema(type=types.Type.NUMBER),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["name", "message_to_user"]
        )
    )

    # ── CREATE INVOICE ────────────────────────────────────────────
    ai_create_invoice = types.FunctionDeclaration(
        name="ai_create_invoice",
        description=(
            "Create a customer invoice (out_invoice) or vendor bill (in_invoice). "
            "Only when explicitly commanded."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "move_type": types.Schema(
                    type=types.Type.STRING,
                    description="'out_invoice' for customer invoice, 'in_invoice' for vendor bill"
                ),
                "partner_name":    types.Schema(type=types.Type.STRING),
                "partner_vat":     types.Schema(type=types.Type.STRING, description="Tax Registration Number (TRN)"),
                "invoice_date":    types.Schema(type=types.Type.STRING, description="Date YYYY-MM-DD"),
                "lines": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "description": types.Schema(type=types.Type.STRING),
                            "quantity":    types.Schema(type=types.Type.NUMBER),
                            "price_unit":  types.Schema(type=types.Type.NUMBER),
                        }
                    )
                ),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["move_type", "partner_name", "lines", "message_to_user"]
        )
    )

    # ── CREATE BANK STATEMENT ─────────────────────────────────────
    ai_create_bank_stmt = types.FunctionDeclaration(
        name="ai_create_bank_stmt",
        description=(
            "Create an accounting bank statement. "
            "Odoo 17+ uses account.bank.statement with line_ids. "
            "Only when explicitly commanded."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "reference":        types.Schema(type=types.Type.STRING),
                "date":             types.Schema(type=types.Type.STRING, description="YYYY-MM-DD"),
                "starting_balance": types.Schema(type=types.Type.NUMBER),
                "ending_balance":   types.Schema(type=types.Type.NUMBER),
                "lines": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "date":   types.Schema(type=types.Type.STRING),
                            "label":  types.Schema(type=types.Type.STRING),
                            "amount": types.Schema(
                                type=types.Type.NUMBER,
                                description="POSITIVE for credit/deposit, NEGATIVE for debit/withdrawal"
                            ),
                        }
                    )
                ),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["reference", "date", "starting_balance", "ending_balance", "lines", "message_to_user"]
        )
    )

    # ── CREATE RFQ ────────────────────────────────────────────────
    ai_create_rfq = types.FunctionDeclaration(
        name="ai_create_rfq",
        description=(
            "Create a Request for Quotation (Purchase Order). "
            "Only when explicitly commanded. "
            "Check if vendor exists first using ai_dynamic_read."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "vendor_name":  types.Schema(type=types.Type.STRING),
                "vendor_email": types.Schema(type=types.Type.STRING),
                "vendor_phone": types.Schema(type=types.Type.STRING),
                "notes":        types.Schema(type=types.Type.STRING, description="Internal notes/BOQ description"),
                "products": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "name":     types.Schema(type=types.Type.STRING),
                            "quantity": types.Schema(type=types.Type.NUMBER),
                            "price":    types.Schema(type=types.Type.NUMBER, description="Unit price (0 if unknown)"),
                        }
                    )
                ),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["vendor_name", "products", "message_to_user"]
        )
    )

    return types.Tool(function_declarations=[
        ai_dynamic_read,
        ai_create_lead,
        ai_create_invoice,
        ai_create_bank_stmt,
        ai_create_rfq,
    ])


# ══════════════════════════════════════════════════════════════════
#  HELPER: HTML Formatter
# ══════════════════════════════════════════════════════════════════

def _to_html(text: str) -> Markup:
    """تحويل نص عادي (مع markdown بسيط) إلى HTML آمن"""
    # Bold **text**
    text = re.sub(r'\*\*(.*?)\*\*', r'<b style="color:#017E84">\1</b>', text)
    # Headers ### text
    text = re.sub(r'^### (.+)$', r'<h4 style="margin:8px 0">\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$',  r'<h3 style="margin:8px 0">\1</h3>', text, flags=re.MULTILINE)
    # Bullet lists
    text = re.sub(r'^\* (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    text = re.sub(r'^- (.+)$',  r'<li>\1</li>', text, flags=re.MULTILINE)
    # Newlines
    text = text.replace('\n', '<br/>')
    return Markup(f"<div style='line-height:1.8;font-size:14px;direction:auto'>{text}</div>")


# ══════════════════════════════════════════════════════════════════
#  MAIN CONTROLLER
# ══════════════════════════════════════════════════════════════════

class KhalesAIController(AIController):

    # ─────────────────────────────────────────────────────────────
    # ROUTE
    # ─────────────────────────────────────────────────────────────
    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('KH_AI v2.0 → request received')

        if not HAS_GENAI:
            return {'error': 'google-genai not installed on server'}

        # ── 1. Parse Input ────────────────────────────────────────
        prompt, mail_message_id, chat_history, attachments = self._parse_input(kwargs)

        # ── 2. Build Gemini contents ──────────────────────────────
        gemini_contents = self._build_contents(chat_history, attachments)

        # ── 3. Call Gemini ────────────────────────────────────────
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            self._post_message("⛔ لم يتم تكوين مفتاح Gemini API في إعدادات النظام.", mail_message_id)
            return {}

        try:
            client = genai.Client(api_key=api_key)

            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.3,
                tools=[
                    _build_tools(),
                    types.Tool(google_search=types.GoogleSearch()),  # Gemini Grounding مجاني
                ],
            )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=gemini_contents,
                config=config,
            )

        except Exception as e:
            _logger.exception("KH_AI: Gemini API error")
            self._post_message(f"⛔ خطأ في الاتصال بـ Gemini:\n{e}", mail_message_id)
            return {}

        # ── 4. Route response ─────────────────────────────────────
        if response.function_calls:
            return self._handle_tool_call(response.function_calls[0], mail_message_id)
        else:
            text = getattr(response, 'text', '') or ''
            if not text.startswith(AGENT_PERSONA):
                text = f"{AGENT_PERSONA}: {text}"
            self._post_message(text, mail_message_id)
            return {}

    # ─────────────────────────────────────────────────────────────
    # INPUT PARSER
    # ─────────────────────────────────────────────────────────────
    def _parse_input(self, kwargs):
        """استخراج الـ prompt والتاريخ والمرفقات من الطلب"""
        prompt = ""
        mail_message_id = kwargs.get('mail_message_id')
        chat_history = ""
        attachments = request.env['ir.attachment'].sudo()

        if mail_message_id:
            msg = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if msg.exists():
                prompt = html2plaintext(msg.body) if msg.body else ""
                attachments = msg.attachment_ids

                # بناء تاريخ المحادثة (آخر 8 رسائل)
                if msg.model == 'discuss.channel':
                    history_msgs = request.env['mail.message'].sudo().search(
                        [('model', '=', 'discuss.channel'), ('res_id', '=', msg.res_id)],
                        order='id desc', limit=8
                    )
                    lines = []
                    for h in reversed(history_msgs):
                        role = "User" if h.author_id.id == request.env.user.partner_id.id else "Assistant"
                        body = html2plaintext(h.body) if h.body else ""
                        if body:
                            lines.append(f"{role}: {body}")
                        if h.attachment_ids:
                            attachments |= h.attachment_ids
                    chat_history = "\n".join(lines)
        else:
            raw = kwargs.get('prompt') or kwargs.get('question') or kwargs.get('text') or ''
            prompt = html2plaintext(raw) if '<' in raw else raw
            att_ids = kwargs.get('attachments') or kwargs.get('attachment_ids') or []
            if att_ids:
                attachments = request.env['ir.attachment'].sudo().browse(
                    [int(i) for i in att_ids if str(i).isdigit()]
                )
            chat_history = f"User: {prompt}"

        return prompt, mail_message_id, chat_history, attachments

    # ─────────────────────────────────────────────────────────────
    # CONTENT BUILDER
    # ─────────────────────────────────────────────────────────────
    def _build_contents(self, chat_history: str, attachments) -> list:
        """بناء محتوى الطلب لـ Gemini (نص + ملفات)"""
        contents = [f"--- CONVERSATION ---\n{chat_history}\n--- END ---"]
        for att in attachments:
            try:
                raw = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if raw:
                    contents.append(
                        types.Part.from_bytes(data=raw, mime_type=att.mimetype or 'application/octet-stream')
                    )
            except Exception:
                pass
        return contents

    # ─────────────────────────────────────────────────────────────
    # MESSAGE POSTER
    # ─────────────────────────────────────────────────────────────
    def _post_message(self, text: str, mail_message_id):
        """نشر رسالة في قناة المحادثة"""
        if not mail_message_id:
            return
        try:
            msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if not msg_record.exists() or msg_record.model != 'discuss.channel':
                return

            channel = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
            ai_agent = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
            author_id = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id

            channel.message_post(
                body=_to_html(text),
                author_id=author_id,
                message_type='comment',
            )
        except Exception:
            _logger.exception("KH_AI: failed to post message")

    # ─────────────────────────────────────────────────────────────
    # TOOL DISPATCHER
    # ─────────────────────────────────────────────────────────────
    def _handle_tool_call(self, func, mail_message_id):
        """تنفيذ الأداة المناسبة وإرجاع النتيجة"""
        name = func.name
        args = func.args

        _logger.info(f"KH_AI: tool call → {name} | args: {args}")

        try:
            if name == "ai_dynamic_read":
                return self._tool_dynamic_read(args, mail_message_id)
            elif name == "ai_create_lead":
                return self._tool_create_lead(args, mail_message_id)
            elif name == "ai_create_invoice":
                return self._tool_create_invoice(args, mail_message_id)
            elif name == "ai_create_bank_stmt":
                return self._tool_create_bank_stmt(args, mail_message_id)
            elif name == "ai_create_rfq":
                return self._tool_create_rfq(args, mail_message_id)
            else:
                self._post_message(f"⛔ أداة غير معروفة: {name}", mail_message_id)
                return {}

        except AccessError:
            self._post_message(
                f"{AGENT_PERSONA}: ⛔ ليس لديك صلاحية لتنفيذ هذه العملية.",
                mail_message_id
            )
            return {}
        except UserError as e:
            self._post_message(f"{AGENT_PERSONA}: ⚠️ {e}", mail_message_id)
            return {}
        except Exception as e:
            _logger.exception(f"KH_AI: tool {name} failed")
            self._post_message(f"{AGENT_PERSONA}: ⛔ خطأ في تنفيذ الأداة:\n{e}", mail_message_id)
            return {}

    # ══════════════════════════════════════════════════════════════
    #  TOOL IMPLEMENTATIONS
    # ══════════════════════════════════════════════════════════════

    # ── READ (Dynamic) ────────────────────────────────────────────
    def _tool_dynamic_read(self, args, mail_message_id):
        model_name = args.get('model_name', '').strip()
        keyword    = args.get('keyword', '').strip()
        filters    = args.get('filters', '').strip()
        limit      = min(int(args.get('limit', 10)), 50)

        # أمان: التحقق من أن الموديل في قائمة المسموح
        if model_name not in READABLE_MODELS:
            self._post_message(
                f"{AGENT_PERSONA}: ⛔ البحث في '{model_name}' غير مسموح به.",
                mail_message_id
            )
            return {}

        allowed_fields = READABLE_MODELS[model_name]

        # بناء الـ domain
        domain = []
        if keyword:
            domain.append(('name', 'ilike', keyword))
        if filters:
            try:
                extra = json.loads(filters)
                domain.extend(extra)
            except json.JSONDecodeError:
                pass  # نتجاهل الـ filter الغلط

        # القراءة بصلاحيات المستخدم الحقيقي (بدون sudo)
        env = request.env
        records = env[model_name].search_read(domain, fields=allowed_fields, limit=limit)

        if not records:
            self._post_message(
                f"{AGENT_PERSONA}: 🔍 لم أجد أي سجلات مطابقة في '{model_name}'"
                + (f" للكلمة '{keyword}'" if keyword else "") + ".",
                mail_message_id
            )
            return {}

        # بناء الرد
        lines = [f"{AGENT_PERSONA}: 🔍 وجدت **{len(records)}** سجل في {model_name}:\n"]
        for r in records:
            # عرض أهم حقل (name أو display_name)
            title = r.get('name') or r.get('display_name') or str(r.get('id'))
            # عرض باقي الحقول
            details = []
            for f in allowed_fields:
                if f == 'name':
                    continue
                val = r.get(f)
                if val:
                    # معالجة Many2one (tuple)
                    if isinstance(val, (list, tuple)) and len(val) == 2:
                        val = val[1]
                    details.append(f"{f}: {val}")
            detail_str = " | ".join(details[:4]) if details else ""
            lines.append(f"- **{title}**" + (f" — {detail_str}" if detail_str else ""))

        self._post_message("\n".join(lines), mail_message_id)
        return {}

    # ── CREATE LEAD ───────────────────────────────────────────────
    def _tool_create_lead(self, args, mail_message_id):
        env = request.env  # صلاحيات المستخدم الحقيقي

        new_lead = env['crm.lead'].create({
            'name':             args.get('name', 'AI Lead'),
            'partner_name':     args.get('partner_name', ''),
            'email_from':       args.get('email_from', ''),
            'phone':            args.get('phone', ''),
            'description':      args.get('description', ''),
            'expected_revenue': float(args.get('expected_revenue', 0.0)),
        })

        msg = args.get('message_to_user', f"تم إنشاء Lead: {new_lead.name}")
        self._post_message(f"{AGENT_PERSONA}: ✅ {msg}", mail_message_id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'res_id': new_lead.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── CREATE INVOICE ────────────────────────────────────────────
    def _tool_create_invoice(self, args, mail_message_id):
        env = request.env  # صلاحيات المستخدم الحقيقي

        move_type    = args.get('move_type', 'out_invoice')
        partner_name = args.get('partner_name', 'Unknown')
        partner_vat  = args.get('partner_vat', '')
        invoice_date = args.get('invoice_date') or fields.Date.today()
        lines_data   = args.get('lines', [])

        # إيجاد أو إنشاء الشريك
        partner = env['res.partner'].search([('name', '=ilike', partner_name)], limit=1)
        if not partner:
            partner = env['res.partner'].create({'name': partner_name, 'vat': partner_vat})
        elif partner_vat and not partner.vat:
            partner.write({'vat': partner_vat})

        # الحساب المناسب
        acc_type = 'expense' if move_type == 'in_invoice' else 'income'
        account = env['account.account'].search(
            [('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)],
            limit=1
        )

        # بناء سطور الفاتورة
        invoice_lines = []
        for ln in lines_data:
            invoice_lines.append((0, 0, {
                'name':       ln.get('description', 'Item'),
                'quantity':   float(ln.get('quantity', 1.0)),
                'price_unit': float(ln.get('price_unit', 0.0)),
                'account_id': account.id if account else False,
            }))

        if not invoice_lines:
            invoice_lines.append((0, 0, {
                'name': 'Item', 'quantity': 1.0, 'price_unit': 0.0,
                'account_id': account.id if account else False,
            }))

        new_move = env['account.move'].create({
            'move_type':        move_type,
            'partner_id':       partner.id,
            'invoice_date':     invoice_date,
            'invoice_line_ids': invoice_lines,
        })

        msg = args.get('message_to_user', f"تم إنشاء {new_move.name}")
        self._post_message(f"{AGENT_PERSONA}: ✅ {msg}", mail_message_id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': new_move.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── CREATE BANK STATEMENT ─────────────────────────────────────
    def _tool_create_bank_stmt(self, args, mail_message_id):
        env = request.env  # صلاحيات المستخدم الحقيقي

        journal = env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', env.company.id)],
            limit=1
        )
        if not journal:
            self._post_message(
                f"{AGENT_PERSONA}: ⛔ لم أجد دفتر يومية بنكي (Bank Journal) في النظام.",
                mail_message_id
            )
            return {}

        stmt_date  = args.get('date') or str(fields.Date.today())
        lines_data = args.get('lines', [])

        stmt_lines = [(0, 0, {
            'date':        ln.get('date', stmt_date),
            'payment_ref': ln.get('label', 'Transaction'),
            'amount':      float(ln.get('amount', 0.0)),
        }) for ln in lines_data]

        # Odoo 17+ API للـ bank statement
        new_stmt = env['account.bank.statement'].create({
            'name':             args.get('reference', 'AI Bank Statement'),
            'date':             stmt_date,
            'balance_start':    float(args.get('starting_balance', 0.0)),
            'balance_end_real': float(args.get('ending_balance', 0.0)),
            'journal_id':       journal.id,
            'line_ids':         stmt_lines,
        })

        msg = args.get('message_to_user', f"تم إنشاء كشف بنكي: {new_stmt.name}")
        self._post_message(f"{AGENT_PERSONA}: ✅ {msg}", mail_message_id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement',
            'res_id': new_stmt.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── CREATE RFQ ────────────────────────────────────────────────
    def _tool_create_rfq(self, args, mail_message_id):
        env = request.env  # صلاحيات المستخدم الحقيقي

        vendor_name  = args.get('vendor_name', '')
        vendor_email = args.get('vendor_email', '')
        vendor_phone = args.get('vendor_phone', '')
        products     = args.get('products', [])
        notes        = args.get('notes', '')

        # إيجاد أو إنشاء المورد
        vendor = env['res.partner'].search([('name', '=ilike', vendor_name)], limit=1)
        if not vendor:
            vendor = env['res.partner'].create({
                'name':       vendor_name,
                'is_company': True,
                'email':      vendor_email,
                'phone':      vendor_phone,
            })
        else:
            updates = {}
            if vendor_email and not vendor.email: updates['email'] = vendor_email
            if vendor_phone and not vendor.phone: updates['phone'] = vendor_phone
            if updates:
                vendor.write(updates)

        # بناء سطور الطلب
        order_lines = []
        for p in products:
            prod_name = p.get('name', '')
            product = env['product.product'].search([('name', '=ilike', prod_name)], limit=1)
            if not product:
                product = env['product.product'].create({'name': prod_name, 'type': 'consu'})

            line_vals = {
                'product_id':  product.id,
                'name':        product.name,
                'product_qty': float(p.get('quantity', 1.0)),
            }
            price = float(p.get('price', 0.0))
            if price:
                line_vals['price_unit'] = price

            order_lines.append((0, 0, line_vals))

        rfq_vals = {
            'partner_id': vendor.id,
            'order_line': order_lines,
        }
        if notes:
            rfq_vals['notes'] = notes

        new_rfq = env['purchase.order'].create(rfq_vals)

        msg = args.get('message_to_user', f"تم إنشاء RFQ: {new_rfq.name}")
        self._post_message(f"{AGENT_PERSONA}: ✅ {msg}", mail_message_id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': new_rfq.id,
            'views': [[False, 'form']],
            'target': 'current',
        }