# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║           KHALES AI - HYBRID AGENT ENGINE v3.0                  ║
║           Odoo 19 | Gemini 2.5 Flash | Clean i18n Architecture   ║
╚══════════════════════════════════════════════════════════════════╝

المقاربة: Hybrid
  - القراءة  → Dynamic ORM  (AI يختار الموديل بحرية)
  - الكتابة  → Fixed Tools  (أدوات محددة وآمنة)
  - الأمان   → صلاحيات المستخدم الحقيقي (بدون sudo للكتابة)
  - اللغة    → Single Source of Truth (utils/lang.py + translations/*.po)
"""

import base64
import json
import logging
import re
from dataclasses import dataclass

from markupsafe import Markup

from odoo import fields, http, models
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.tools import html2plaintext

# ── Odoo AI base ────────────────────────────────────────────────
from odoo.addons.ai.controllers.main import AIController

# ── Our clean i18n utilities ────────────────────────────────────
from ..utils.lang import detect_from_history, Lang
from ..utils.i18n import translator, Translator
from ..utils.prompt import build_system_instruction, AGENT_PERSONA
from ..utils.renderer import render_table, margin_icon

_logger = logging.getLogger(__name__)

# ── Google GenAI ────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False
    _logger.warning("KH_AI: google-genai not installed. pip install google-genai")


# ══════════════════════════════════════════════════════════════════
#  MODEL EXTENSION
# ══════════════════════════════════════════════════════════════════
class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'
    type = fields.Selection([
        ('file', 'File'),
        ('url', 'URL'),
        ('manual', 'Manual Text'),
    ], string='Source Type', required=True, default='file')


# ══════════════════════════════════════════════════════════════════
#  READABLE MODELS WHITELIST
# ══════════════════════════════════════════════════════════════════
READABLE_MODELS = {
    'res.partner':            ['name', 'email', 'phone', 'vat', 'is_company', 'street', 'city'],
    'crm.lead':               ['name', 'partner_name', 'email_from', 'phone', 'stage_id', 'description'],
    'account.move':           ['name', 'partner_id', 'amount_total', 'state', 'move_type', 'invoice_date'],
    'purchase.order':         ['name', 'partner_id', 'amount_total', 'state', 'date_order'],
    'purchase.order.line':    ['name', 'order_id', 'partner_id', 'product_id', 'price_unit', 'product_qty', 'date_approve'],
    'sale.order':             ['name', 'partner_id', 'amount_total', 'state', 'date_order'],
    'project.task':           ['name', 'project_id', 'user_ids', 'stage_id', 'date_deadline'],
    'hr.employee':            ['name', 'job_title', 'department_id', 'work_email'],
    'product.product':        ['name', 'list_price', 'qty_available', 'categ_id'],
    'stock.picking':          ['name', 'partner_id', 'state', 'scheduled_date', 'picking_type_id'],
    'account.bank.statement': ['name', 'date', 'balance_start', 'balance_end_real', 'journal_id'],
}


# ══════════════════════════════════════════════════════════════════
#  REQUEST CONTEXT — carries lang + translator through the call stack
# ══════════════════════════════════════════════════════════════════
@dataclass
class RequestCtx:
    """
    Per-request context. Built once in _parse_input, passed to every tool.
    Replaces the scattered `lang=...` parameters from v2.0.
    """
    lang: Lang
    t: Translator
    mail_message_id: int
    chat_history: str
    attachments: object  # ir.attachment recordset

    @classmethod
    def build(cls, lang, mail_message_id, chat_history, attachments):
        return cls(
            lang=lang,
            t=translator(lang),
            mail_message_id=mail_message_id,
            chat_history=chat_history,
            attachments=attachments,
        )


# ══════════════════════════════════════════════════════════════════
#  TOOL DEFINITIONS
# ══════════════════════════════════════════════════════════════════
def _build_tools():
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
                        "Example: '[[\"state\", \"=\", \"draft\"]]'"
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
                "name":             types.Schema(type=types.Type.STRING),
                "partner_name":     types.Schema(type=types.Type.STRING),
                "email_from":       types.Schema(type=types.Type.STRING),
                "phone":            types.Schema(type=types.Type.STRING),
                "description":      types.Schema(type=types.Type.STRING),
                "expected_revenue": types.Schema(type=types.Type.NUMBER),
                "message_to_user":  types.Schema(type=types.Type.STRING),
            },
            required=["name", "message_to_user"]
        )
    )

    # ── CREATE INVOICE ────────────────────────────────────────────
    ai_create_invoice = types.FunctionDeclaration(
        name="ai_create_invoice",
        description="Create a customer invoice (out_invoice) or vendor bill (in_invoice).",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "move_type":    types.Schema(type=types.Type.STRING),
                "partner_name": types.Schema(type=types.Type.STRING),
                "partner_vat":  types.Schema(type=types.Type.STRING),
                "invoice_date": types.Schema(type=types.Type.STRING),
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
        description="Create an accounting bank statement.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "reference":        types.Schema(type=types.Type.STRING),
                "date":             types.Schema(type=types.Type.STRING),
                "starting_balance": types.Schema(type=types.Type.NUMBER),
                "ending_balance":   types.Schema(type=types.Type.NUMBER),
                "lines": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "date":   types.Schema(type=types.Type.STRING),
                            "label":  types.Schema(type=types.Type.STRING),
                            "amount": types.Schema(type=types.Type.NUMBER),
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
            "Create a Request for Quotation (RFQ/Purchase Order). "
            "Trigger on: طلب تسعير, RFQ, عرض طلب, خلينا نجهز/نبعث, send RFQ, create PO. "
            "Do NOT pre-check if vendor exists — this tool creates vendors automatically."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "vendor_name":  types.Schema(type=types.Type.STRING),
                "vendor_email": types.Schema(type=types.Type.STRING),
                "vendor_phone": types.Schema(type=types.Type.STRING),
                "notes":        types.Schema(type=types.Type.STRING),
                "products": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "name":     types.Schema(type=types.Type.STRING),
                            "quantity": types.Schema(type=types.Type.NUMBER),
                            "price":    types.Schema(type=types.Type.NUMBER),
                        }
                    )
                ),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["vendor_name", "products", "message_to_user"]
        )
    )

    # ── ANALYTICS ────────────────────────────────────────────────
    ai_analytics = types.FunctionDeclaration(
        name="ai_analytics",
        description="Run financial/business analytics on Odoo data.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "report_type": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "One of: 'profit_by_category', 'revenue_by_partner', "
                        "'project_cost', 'project_financial', 'timesheet_hours', "
                        "'top_products', 'expense_breakdown', 'invoice_summary', "
                        "'stock_valuation', 'sales_pipeline'"
                    )
                ),
                "date_from":    types.Schema(type=types.Type.STRING),
                "date_to":      types.Schema(type=types.Type.STRING),
                "limit":        types.Schema(type=types.Type.INTEGER),
                "project_name": types.Schema(
                    type=types.Type.STRING,
                    description="For project_financial: full name or keyword from history"
                ),
            },
            required=["report_type"]
        )
    )

    # ── ASK USER ─────────────────────────────────────────────────
    ai_ask_user = types.FunctionDeclaration(
        name="ai_ask_user",
        description="Ask user for clarification — present options, never refuse.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "question": types.Schema(type=types.Type.STRING),
                "options": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                ),
                "context": types.Schema(type=types.Type.STRING),
            },
            required=["question", "options"]
        )
    )

    # ── BULK UPDATE ──────────────────────────────────────────────
    ai_update_records = types.FunctionDeclaration(
        name="ai_update_records",
        description="Bulk update existing Odoo records (set account on bank statements, etc.)",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "operation": types.Schema(
                    type=types.Type.STRING,
                    description="'set_bank_statement_account' | 'set_invoice_account'"
                ),
                "partner_name":    types.Schema(type=types.Type.STRING),
                "account_code":    types.Schema(type=types.Type.STRING),
                "account_name":    types.Schema(type=types.Type.STRING),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["operation", "message_to_user"]
        )
    )

    return types.Tool(function_declarations=[
        ai_dynamic_read,
        ai_create_lead,
        ai_create_invoice,
        ai_create_bank_stmt,
        ai_create_rfq,
        ai_analytics,
        ai_ask_user,
        ai_update_records,
    ])


# ══════════════════════════════════════════════════════════════════
#  HTML FORMATTER
# ══════════════════════════════════════════════════════════════════
def _to_html(text):
    """تحويل نص عادي (مع markdown بسيط) إلى HTML آمن"""
    text = re.sub(r'\*\*(.*?)\*\*', r'<b style="color:#017E84">\1</b>', text)
    text = re.sub(r'^### (.+)$', r'<h4 style="margin:8px 0">\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$',  r'<h3 style="margin:8px 0">\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^\* (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    text = re.sub(r'^- (.+)$',  r'<li>\1</li>', text, flags=re.MULTILINE)
    text = text.replace('\n', '<br/>')
    return Markup(f"<div style='line-height:1.8;font-size:14px;direction:auto'>{text}</div>")


# ══════════════════════════════════════════════════════════════════
#  MAIN CONTROLLER
# ══════════════════════════════════════════════════════════════════
class AIControllerOverride(AIController):

    # ─────────────────────────────────────────────────────────────
    # ROUTE
    # ─────────────────────────────────────────────────────────────
    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('KH_AI v3.0 → request received')

        if not HAS_GENAI:
            return {'error': 'google-genai not installed on server'}

        # ── 1. Parse input + build context (lang detected ONCE here) ─
        ctx = self._parse_input(kwargs)

        # ── 2. Check API key ─────────────────────────────────────
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            self._post(ctx, ctx.t("Gemini API key not configured"), level='error')
            return {}

        # ── 3. Build Gemini contents ─────────────────────────────
        gemini_contents = self._build_contents(ctx)

        # ── 4. Two-pass router ───────────────────────────────────
        try:
            client = genai.Client(api_key=api_key)

            # Pass 1: Classify intent
            last_user_msg = ""
            for line in reversed(ctx.chat_history.splitlines()):
                if line.startswith("User:"):
                    last_user_msg = line[5:].strip()
                    break

            classifier_prompt = (
                "You are classifying a user message in a conversation about an ERP system.\n\n"
                "Classify into ONE category:\n"
                "- ODOO_ACTION  -> create/update/delete/send records in Odoo\n"
                "- ODOO_READ    -> search/find/list/analyze data, reports, financial status\n"
                "- WEB_SEARCH   -> external internet info only\n"
                "- CHAT         -> pure greetings with NO business intent\n\n"
                "ODOO_ACTION keywords: انشئ, اعمل, جهز, ابعث, ارسل, سجل, أضف, خلينا نجهز, "
                "خلينا نبعث, طلب تسعير, RFQ, عرض طلب, فاتورة, lead, create, send, make\n\n"
                "ODOO_READ keywords: دور, ابحث, اعرض, كم, شو وضع, تقرير, فواتير, موردين, عملاء\n\n"
                "IMPORTANT: pronouns (تبعو, تبعها, عليه, هذا) referring to earlier record → ODOO_READ\n\n"
                f"Conversation context:\n{ctx.chat_history[-600:]}\n\n"
                f"Latest user message: {last_user_msg}\n\n"
                "Reply with ONLY one word: ODOO_ACTION or ODOO_READ or WEB_SEARCH or CHAT"
            )

            classify_resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[classifier_prompt],
                config=types.GenerateContentConfig(temperature=0.0),
            )
            intent = (getattr(classify_resp, 'text', '') or '').strip().upper()
            _logger.info(f"KH_AI: intent -> {intent}")

            # Pass 2: Execute with correct tool set
            if intent in ('ODOO_ACTION', 'ODOO_READ'):
                config = types.GenerateContentConfig(
                    system_instruction=build_system_instruction(ctx.lang),
                    temperature=0.3,
                    tools=[_build_tools()],
                )
            else:
                config = types.GenerateContentConfig(
                    system_instruction=build_system_instruction(ctx.lang),
                    temperature=0.4,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=gemini_contents,
                config=config,
            )

        except Exception as e:
            _logger.exception("KH_AI: Gemini API error")
            self._post(ctx, f"{ctx.t('Gemini connection error')}:\n{e}", level='error')
            return {}

        # ── 5. Route response ────────────────────────────────────
        if response.function_calls:
            return self._handle_tool_call(response.function_calls[0], ctx)

        text = getattr(response, 'text', '') or ''
        if not text.startswith(AGENT_PERSONA):
            text = f"{AGENT_PERSONA}: {text}"
        self._post_raw(ctx, text)
        return {}

    # ─────────────────────────────────────────────────────────────
    # INPUT PARSER — the ONLY place language is detected
    # ─────────────────────────────────────────────────────────────
    def _parse_input(self, kwargs):
        mail_message_id = kwargs.get('mail_message_id')
        chat_history = ""
        attachments = request.env['ir.attachment'].sudo()

        if mail_message_id:
            msg = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if msg.exists():
                attachments = msg.attachment_ids

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

        # 🎯 LANGUAGE DETECTION — exactly once, from last user message
        lang = detect_from_history(chat_history)
        _logger.info("KH_AI: detected lang=%s", lang)

        return RequestCtx.build(lang, mail_message_id, chat_history, attachments)

    # ─────────────────────────────────────────────────────────────
    # CONTENT BUILDER
    # ─────────────────────────────────────────────────────────────
    def _build_contents(self, ctx):
        """بناء محتوى الطلب لـ Gemini (نص + ملفات)"""
        contents = [f"--- CONVERSATION ---\n{ctx.chat_history}\n--- END ---"]
        for att in ctx.attachments:
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
    # MESSAGE POSTERS
    # ─────────────────────────────────────────────────────────────
    def _post(self, ctx, text, level='info'):
        """
        Post a translated message to chat with auto persona + icon.

        Args:
            ctx: RequestCtx
            text: Body text (already translated via ctx.t)
            level: 'info' | 'error' | 'warning' | 'success'
        """
        icons = {'info': '', 'error': '⛔ ', 'warning': '⚠️ ', 'success': '✅ '}
        body = f"{AGENT_PERSONA}: {icons.get(level, '')}{text}"
        self._post_raw(ctx, body)

    def _post_raw(self, ctx, text):
        """Post exactly what's given (no icon/persona prefix added)."""
        if not ctx.mail_message_id:
            return
        try:
            msg_record = request.env['mail.message'].sudo().browse(int(ctx.mail_message_id))
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
    def _handle_tool_call(self, func, ctx):
        name = func.name
        args = func.args

        _logger.info(f"KH_AI: tool call → {name} | args: {args}")

        try:
            if name == "ai_dynamic_read":
                return self._tool_dynamic_read(args, ctx)
            elif name == "ai_create_lead":
                return self._tool_create_lead(args, ctx)
            elif name == "ai_create_invoice":
                return self._tool_create_invoice(args, ctx)
            elif name == "ai_create_bank_stmt":
                return self._tool_create_bank_stmt(args, ctx)
            elif name == "ai_create_rfq":
                return self._tool_create_rfq(args, ctx)
            elif name == "ai_analytics":
                return self._tool_analytics(args, ctx)
            elif name == "ai_ask_user":
                return self._tool_ask_user(args, ctx)
            elif name == "ai_update_records":
                return self._tool_update_records(args, ctx)
            else:
                self._post(ctx, ctx.t("Unknown tool: %(name)s", name=name), level='error')
                return {}

        except AccessError:
            self._post(ctx, ctx.t("Permission denied"), level='error')
            return {}
        except UserError as e:
            self._post(ctx, str(e), level='warning')
            return {}
        except Exception as e:
            _logger.exception(f"KH_AI: tool {name} failed")
            self._post(ctx, f"{ctx.t('Error')}:\n{e}", level='error')
            return {}

    # ══════════════════════════════════════════════════════════════
    #  TOOL IMPLEMENTATIONS
    # ══════════════════════════════════════════════════════════════

    # ── READ (Dynamic) ────────────────────────────────────────────
    def _tool_dynamic_read(self, args, ctx):
        model_name = args.get('model_name', '').strip()
        keyword    = args.get('keyword', '').strip()
        filters    = args.get('filters', '').strip()
        limit      = min(int(args.get('limit', 10)), 50)
        t = ctx.t

        if model_name not in READABLE_MODELS:
            self._post(ctx, t("Search in '%(model)s' is not allowed", model=model_name), level='error')
            return {}

        allowed_fields = READABLE_MODELS[model_name]

        domain = []
        if keyword:
            domain.append(('name', 'ilike', keyword))
        if filters:
            try:
                domain.extend(json.loads(filters))
            except json.JSONDecodeError:
                pass

        records = request.env[model_name].search_read(domain, fields=allowed_fields, limit=limit)

        if not records:
            self._post(ctx, t("No records found matching '%(keyword)s'", keyword=keyword or model_name))
            return {}

        # عرض خاص لبنود طلبات الشراء
        if model_name == 'purchase.order.line':
            lines = [f"🔍 {t('Found %(count)s record(s) in %(model)s', count=len(records), model=model_name)}\n"]
            seen_vendors = {}
            for r in records:
                ptnr = r.get('partner_id')
                pname = ptnr[1] if isinstance(ptnr, (list, tuple)) and len(ptnr) == 2 else str(ptnr or '-')
                prod = r.get('product_id')
                prodname = prod[1] if isinstance(prod, (list, tuple)) and len(prod) == 2 else str(prod or '-')
                qty = r.get('product_qty', 0)
                price = float(r.get('price_unit') or 0)
                seen_vendors.setdefault(pname, []).append(f"{prodname} × {qty} @ {price:,.2f}")
            for vendor, items in seen_vendors.items():
                lines.append(f"🏢 **{vendor}**")
                for item in items:
                    lines.append(f"   • {item}")
                lines.append("")
            self._post(ctx, "\n".join(lines))
            return {}

        # العرض الافتراضي
        lines = [f"🔍 {t('Found %(count)s record(s) in %(model)s', count=len(records), model=model_name)}\n"]
        for r in records:
            title = r.get('name') or r.get('display_name') or str(r.get('id'))
            details = []
            for fld in allowed_fields:
                if fld == 'name':
                    continue
                val = r.get(fld)
                if val:
                    if isinstance(val, (list, tuple)) and len(val) == 2:
                        val = val[1]
                    details.append(f"{fld}: {val}")
            detail_str = " | ".join(details[:4]) if details else ""
            lines.append(f"- **{title}**" + (f" — {detail_str}" if detail_str else ""))

        self._post(ctx, "\n".join(lines))
        return {}

    # ── CREATE LEAD ───────────────────────────────────────────────
    def _tool_create_lead(self, args, ctx):
        env = request.env

        new_lead = env['crm.lead'].create({
            'name':             args.get('name', 'AI Lead'),
            'partner_name':     args.get('partner_name', ''),
            'email_from':       args.get('email_from', ''),
            'phone':            args.get('phone', ''),
            'description':      args.get('description', ''),
            'expected_revenue': float(args.get('expected_revenue', 0.0)),
        })

        self._post(ctx, ctx.t("Lead created: %(name)s", name=new_lead.name), level='success')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'res_id': new_lead.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── CREATE INVOICE ────────────────────────────────────────────
    def _tool_create_invoice(self, args, ctx):
        env = request.env

        move_type    = args.get('move_type', 'out_invoice')
        partner_name = args.get('partner_name', 'Unknown')
        partner_vat  = args.get('partner_vat', '')
        invoice_date = args.get('invoice_date') or fields.Date.today()
        lines_data   = args.get('lines', [])

        partner = env['res.partner'].search([('name', '=ilike', partner_name)], limit=1)
        if not partner:
            partner = env['res.partner'].create({'name': partner_name, 'vat': partner_vat})
        elif partner_vat and not partner.vat:
            partner.write({'vat': partner_vat})

        acc_type = 'expense' if move_type == 'in_invoice' else 'income'
        account = env['account.account'].search(
            [('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)],
            limit=1
        )

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

        self._post(ctx, ctx.t("Invoice created: %(name)s", name=new_move.name), level='success')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': new_move.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── CREATE BANK STATEMENT ─────────────────────────────────────
    def _tool_create_bank_stmt(self, args, ctx):
        env = request.env

        journal = env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', env.company.id)],
            limit=1
        )
        if not journal:
            self._post(ctx, ctx.t("Error") + ": No bank journal found", level='error')
            return {}

        stmt_date  = args.get('date') or str(fields.Date.today())
        lines_data = args.get('lines', [])

        stmt_lines = [(0, 0, {
            'date':        ln.get('date', stmt_date),
            'payment_ref': ln.get('label', 'Transaction'),
            'amount':      float(ln.get('amount', 0.0)),
        }) for ln in lines_data]

        new_stmt = env['account.bank.statement'].create({
            'name':             args.get('reference', 'AI Bank Statement'),
            'date':             stmt_date,
            'balance_start':    float(args.get('starting_balance', 0.0)),
            'balance_end_real': float(args.get('ending_balance', 0.0)),
            'journal_id':       journal.id,
            'line_ids':         stmt_lines,
        })

        self._post(ctx, ctx.t("Bank statement created: %(name)s", name=new_stmt.name), level='success')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement',
            'res_id': new_stmt.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── CREATE RFQ ────────────────────────────────────────────────
    def _tool_create_rfq(self, args, ctx):
        env = request.env
        t = ctx.t

        vendor_name  = args.get('vendor_name', '')
        vendor_email = args.get('vendor_email', '')
        vendor_phone = args.get('vendor_phone', '')
        products     = args.get('products', [])
        notes        = args.get('notes', '')

        # إيجاد أو إنشاء المورد
        vendor = env['res.partner'].search([('name', '=ilike', vendor_name)], limit=1)
        if not vendor:
            vendor = env['res.partner'].search([('name', 'ilike', vendor_name)], limit=1)
        if not vendor:
            vendor = env['res.partner'].create({
                'name':       vendor_name,
                'is_company': True,
                'email':      vendor_email,
                'phone':      vendor_phone,
            })
        else:
            updates = {}
            if vendor_email and not vendor.email:
                updates['email'] = vendor_email
            if vendor_phone and not vendor.phone:
                updates['phone'] = vendor_phone
            if updates:
                vendor.write(updates)

        # التحقق من الإيميل
        final_email = vendor_email or vendor.email
        final_phone = vendor_phone or vendor.phone

        if not final_email:
            self._post(ctx,
                t("Vendor '%(name)s' has no email on file", name=vendor_name) + "\n" +
                t("Searching the web for contact info...")
            )
            # بحث تلقائي على الإيميل
            try:
                api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
                gclient = genai.Client(api_key=api_key)
                search_resp = gclient.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[f"Search the web for the official contact email and phone of '{vendor_name}'. Return ONLY: EMAIL: xxx@xxx.com | PHONE: +971xxxxxxx"],
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.0,
                    )
                )
                result = (getattr(search_resp, 'text', '') or '').strip()

                email_match = re.search(r'[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}', result)
                phone_match = re.search(r'[+\d][\d\s\-]{8,}', result)

                if email_match:
                    final_email = email_match.group()
                    if phone_match and not final_phone:
                        final_phone = phone_match.group().strip()
                    vendor.write({'email': final_email, 'phone': final_phone or vendor.phone})

                    self._post(ctx,
                        t("Found contact info for %(name)s", name=vendor_name) + "\n" +
                        f"• {t('Email')}: **{final_email}**\n" +
                        f"• {t('Phone')}: **{final_phone or t('Not available')}**\n" +
                        t("Creating the order..."),
                        level='success'
                    )
                else:
                    self._post(ctx, t("Could not find email for %(name)s", name=vendor_name), level='warning')
                    return {}
            except Exception:
                _logger.exception("KH_AI: web search for vendor email failed")
                self._post(ctx, t("Vendor '%(name)s' has no email on file", name=vendor_name), level='warning')
                return {}

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

        self._post(ctx, t("RFQ created: %(name)s", name=new_rfq.name), level='success')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': new_rfq.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── ASK USER ─────────────────────────────────────────────────
    def _tool_ask_user(self, args, ctx):
        question = args.get('question', '')
        options  = args.get('options', [])
        context  = args.get('context', '')

        lines = ["🤔"]
        if context:
            lines.append(f"_{context}_\n")
        lines.append(f"**{question}**\n")
        for i, opt in enumerate(options, 1):
            lines.append(f"{i}️⃣ {opt}")

        self._post(ctx, "\n".join(lines))
        return {}

    # ── BULK UPDATE ───────────────────────────────────────────────
    def _tool_update_records(self, args, ctx):
        env = request.env
        t = ctx.t

        operation    = args.get('operation', '')
        partner_name = args.get('partner_name', '')
        account_code = args.get('account_code', '')
        account_name = args.get('account_name', '')

        if operation == 'set_bank_statement_account':
            # إيجاد الحساب
            account = None
            if account_code:
                account = env['account.account'].search([('code', '=', account_code)], limit=1)
            if not account and account_name:
                account = env['account.account'].search([('name', 'ilike', account_name)], limit=1)
            if not account:
                self._post(ctx, f"{t('Error')}: account '{account_code or account_name}' not found", level='error')
                return {}

            # إيجاد الـ partner
            partner = None
            if partner_name:
                partner = env['res.partner'].search([('name', 'ilike', partner_name)], limit=1)

            domain = [('statement_id', '!=', False)]
            if partner:
                domain.append(('partner_id', '=', partner.id))
            elif partner_name:
                domain.append(('payment_ref', 'ilike', partner_name))

            stmt_lines = env['account.bank.statement.line'].sudo().search(domain, limit=200)

            if not stmt_lines:
                self._post(ctx, t("No records found matching '%(keyword)s'", keyword=partner_name))
                return {}

            updated = 0
            errors = 0
            for line in stmt_lines:
                try:
                    move_lines = env['account.move.line'].sudo().search([
                        ('statement_line_id', '=', line.id),
                        ('account_id.account_type', 'not in', ['asset_cash', 'liability_current']),
                    ], limit=1)

                    if move_lines:
                        move_lines.sudo().write({'account_id': account.id})
                        updated += 1
                    else:
                        if hasattr(line, 'account_id'):
                            line.sudo().write({'account_id': account.id})
                            updated += 1
                        else:
                            errors += 1
                except Exception:
                    errors += 1

            body = (
                f"**{t('Updated')}**\n"
                f"• {t('Account')}: **{account.code} - {account.name}**\n"
                f"• {t('Partner')}: **{partner.name if partner else partner_name}**\n"
                f"• {t('Lines Updated')}: **{updated}**"
            )
            if errors:
                body += f"\n• Errors: {errors}"

            self._post(ctx, body, level='success')
            return {}

        self._post(ctx, f"Operation '{operation}' not supported", level='warning')
        return {}

    # ══════════════════════════════════════════════════════════════
    #  ANALYTICS — with clean i18n pattern
    # ══════════════════════════════════════════════════════════════
    def _tool_analytics(self, args, ctx):
        env = request.env
        t = ctx.t

        report    = args.get('report_type', '')
        date_from = args.get('date_from') or fields.Date.today().replace(month=1, day=1).strftime('%Y-%m-%d')
        date_to   = args.get('date_to')   or str(fields.Date.today())
        limit     = min(int(args.get('limit', 10)), 50)

        try:
            # ── 1. Profit by Category ────────────────────────────
            if report == 'profit_by_category':
                env.cr.execute("""
                    SELECT pc.complete_name AS category,
                           SUM(aml.quantity * aml.price_unit)    AS revenue,
                           SUM(aml.quantity * pp.standard_price) AS cost
                    FROM account_move_line aml
                    JOIN account_move am      ON am.id = aml.move_id
                    JOIN product_product pp   ON pp.id = aml.product_id
                    JOIN product_template pt  ON pt.id = pp.product_tmpl_id
                    JOIN product_category pc  ON pc.id = pt.categ_id
                    WHERE am.move_type = 'out_invoice' AND am.state = 'posted'
                      AND am.invoice_date BETWEEN %s AND %s
                      AND aml.product_id IS NOT NULL AND am.company_id = %s
                    GROUP BY pc.complete_name
                    ORDER BY (SUM(aml.quantity * aml.price_unit)
                              - SUM(aml.quantity * pp.standard_price)) DESC
                    LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                raw_rows = env.cr.dictfetchall()

                if not raw_rows:
                    self._post(ctx, t("No records found matching '%(keyword)s'",
                                      keyword=f"{date_from} → {date_to}"))
                    return {}

                rows = []
                for r in raw_rows:
                    revenue = float(r['revenue'] or 0)
                    cost    = float(r['cost']    or 0)
                    profit  = revenue - cost
                    margin_pct = round(profit / revenue * 100, 1) if revenue else 0
                    rows.append({
                        'Category': r['category'],
                        'Revenue':  revenue,
                        'Cost':     cost,
                        'Profit':   profit,
                        'Margin %': f"{margin_icon(margin_pct)} {margin_pct}%",
                    })

                table = render_table(t, rows, columns=['Category', 'Revenue', 'Cost', 'Profit', 'Margin %'])
                self._post(ctx,
                    f"📊 **{t('Profit Margins')}**\n"
                    f"{t('Period')}: {date_from} → {date_to}\n\n{table}"
                )

            # ── 2. Revenue by Partner ────────────────────────────
            elif report == 'revenue_by_partner':
                env.cr.execute("""
                    SELECT rp.name                AS partner,
                           COUNT(am.id)           AS count,
                           SUM(am.amount_untaxed) AS revenue
                    FROM account_move am
                    JOIN res_partner rp ON rp.id = am.partner_id
                    WHERE am.move_type = 'out_invoice' AND am.state = 'posted'
                      AND am.invoice_date BETWEEN %s AND %s AND am.company_id = %s
                    GROUP BY rp.name ORDER BY revenue DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                raw_rows = env.cr.dictfetchall()

                rows = [{'Partner': r['partner'], 'Count': r['count'],
                         'Revenue': float(r['revenue'] or 0)} for r in raw_rows]

                table = render_table(t, rows, columns=['Partner', 'Count', 'Revenue'])
                self._post(ctx,
                    f"📊 **{t('Revenue')} — {t('Partner')}**\n"
                    f"{t('Period')}: {date_from} → {date_to}\n\n{table}"
                )

            # ── 3. Top Products ──────────────────────────────────
            elif report == 'top_products':
                env.cr.execute("""
                    SELECT COALESCE(pt.name->>'en_US', pt.name->>'ar_001', pt.name::text) AS product,
                           SUM(aml.quantity)                    AS qty,
                           SUM(aml.quantity * aml.price_unit)   AS revenue
                    FROM account_move_line aml
                    JOIN account_move am      ON am.id = aml.move_id
                    JOIN product_product pp   ON pp.id = aml.product_id
                    JOIN product_template pt  ON pt.id = pp.product_tmpl_id
                    WHERE am.move_type = 'out_invoice' AND am.state = 'posted'
                      AND am.invoice_date BETWEEN %s AND %s
                      AND aml.product_id IS NOT NULL AND am.company_id = %s
                    GROUP BY pt.name->>'en_US' ORDER BY revenue DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                raw_rows = env.cr.dictfetchall()

                rows = [{'Project': r['product'], 'Quantity': float(r['qty'] or 0),
                         'Revenue': float(r['revenue'] or 0)} for r in raw_rows]

                table = render_table(t, rows, columns=['Project', 'Quantity', 'Revenue'])
                self._post(ctx,
                    f"📊 **{t('Top Products')}**\n"
                    f"{t('Period')}: {date_from} → {date_to}\n\n{table}"
                )

            # ── 4. Expense Breakdown ─────────────────────────────
            elif report == 'expense_breakdown':
                env.cr.execute("""
                    SELECT COALESCE(aa.name->>'en_US', aa.name->>'ar_001', aa.name::text) AS account,
                           SUM(aml.debit - aml.credit) AS amount
                    FROM account_move_line aml
                    JOIN account_account aa ON aa.id = aml.account_id
                    JOIN account_move am     ON am.id = aml.move_id
                    WHERE aa.account_type IN ('expense', 'expense_depreciation', 'expense_direct_cost')
                      AND am.state = 'posted' AND am.date BETWEEN %s AND %s AND am.company_id = %s
                    GROUP BY aa.name->>'en_US' ORDER BY amount DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                raw_rows = env.cr.dictfetchall()

                rows = [{'Account': r['account'], 'Total': float(r['amount'] or 0)} for r in raw_rows]
                table = render_table(t, rows, columns=['Account', 'Total'])
                self._post(ctx,
                    f"📊 **{t('Expenses')}**\n"
                    f"{t('Period')}: {date_from} → {date_to}\n\n{table}"
                )

            # ── 5. Invoice Summary ───────────────────────────────
            elif report == 'invoice_summary':
                env.cr.execute("""
                    SELECT move_type, state, COUNT(*) AS count, SUM(amount_total) AS total
                    FROM account_move
                    WHERE move_type IN ('out_invoice', 'in_invoice', 'out_refund', 'in_refund')
                      AND invoice_date BETWEEN %s AND %s AND company_id = %s
                    GROUP BY move_type, state ORDER BY move_type, state
                """, (date_from, date_to, env.company.id))
                raw_rows = env.cr.dictfetchall()

                rows = [{'Stage': f"{r['move_type']} / {r['state']}",
                         'Count': r['count'],
                         'Total': float(r['total'] or 0)} for r in raw_rows]

                table = render_table(t, rows, columns=['Stage', 'Count', 'Total'])
                self._post(ctx,
                    f"📊 **{t('Customer Invoices')} / {t('Vendor Bills')}**\n"
                    f"{t('Period')}: {date_from} → {date_to}\n\n{table}"
                )

            # ── 6. Stock Valuation ───────────────────────────────
            elif report == 'stock_valuation':
                products = env['product.product'].search_read(
                    [('type', 'in', ['product', 'consu']), ('qty_available', '>', 0)],
                    fields=['name', 'qty_available', 'standard_price'],
                    limit=limit, order='qty_available desc',
                )
                rows = []
                total_val = 0
                for p in products:
                    qty  = float(p['qty_available'])
                    cost = float(p['standard_price'])
                    val  = qty * cost
                    total_val += val
                    rows.append({
                        'Project':     p['name'],
                        'Quantity':    qty,
                        'Unit Cost':   cost,
                        'Total Value': val,
                    })

                table = render_table(t, rows, columns=['Project', 'Quantity', 'Unit Cost', 'Total Value'])
                self._post(ctx,
                    f"📊 **{t('Total Stock')}**\n\n{table}\n\n"
                    f"**{t('Total Stock')}: {total_val:,.0f}**"
                )

            # ── 7. Sales Pipeline ────────────────────────────────
            elif report == 'sales_pipeline':
                env.cr.execute("""
                    SELECT cs.name AS stage, COUNT(cl.id) AS count,
                           SUM(cl.expected_revenue) AS expected,
                           AVG(cl.probability) AS prob
                    FROM crm_lead cl
                    JOIN crm_stage cs ON cs.id = cl.stage_id
                    WHERE cl.type = 'opportunity' AND cl.active = true AND cl.company_id = %s
                    GROUP BY cs.name, cs.sequence ORDER BY cs.sequence
                """, (env.company.id,))
                raw_rows = env.cr.dictfetchall()

                rows = []
                for r in raw_rows:
                    prob = round(float(r['prob'] or 0), 0)
                    icon = "🟢" if prob >= 70 else "🟡" if prob >= 40 else "🔴"
                    rows.append({
                        'Stage':            r['stage'],
                        'Count':            r['count'],
                        'Expected Revenue': float(r['expected'] or 0),
                        'Probability':      f"{icon} {prob}%",
                    })

                table = render_table(t, rows, columns=['Stage', 'Count', 'Expected Revenue', 'Probability'])
                self._post(ctx, f"📊 **Sales Pipeline**\n\n{table}")

            # ── 8. Project Cost ──────────────────────────────────
            elif report == 'project_cost':
                env.cr.execute("""
                    SELECT COALESCE(pp.name->>'en_US', pp.name->>'ar_001', pp.name::text) AS project,
                           SUM(aal.amount) AS cost,
                           SUM(aal.unit_amount) AS hours,
                           COUNT(DISTINCT aal.employee_id) AS team
                    FROM account_analytic_line aal
                    JOIN project_task pt2   ON pt2.id = aal.task_id
                    JOIN project_project pp ON pp.id = pt2.project_id
                    WHERE aal.date BETWEEN %s AND %s AND pp.company_id = %s
                    GROUP BY pp.name ORDER BY cost DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                raw_rows = env.cr.dictfetchall()

                rows = [{'Project': r['project'], 'Cost': float(r['cost'] or 0),
                         'Hours': float(r['hours'] or 0),
                         'Team Size': int(r['team'] or 0)} for r in raw_rows]

                table = render_table(t, rows, columns=['Project', 'Cost', 'Hours', 'Team Size'])
                self._post(ctx,
                    f"📊 **{t('Project Costs')}**\n"
                    f"{t('Period')}: {date_from} → {date_to}\n\n{table}"
                )

            # ── 9. Timesheet Hours ───────────────────────────────
            elif report == 'timesheet_hours':
                env.cr.execute("""
                    SELECT pp.name AS project, he.name AS employee,
                           SUM(aal.unit_amount) AS hours
                    FROM account_analytic_line aal
                    JOIN project_task pt2   ON pt2.id = aal.task_id
                    JOIN project_project pp ON pp.id = pt2.project_id
                    LEFT JOIN hr_employee he ON he.id = aal.employee_id
                    WHERE aal.date BETWEEN %s AND %s AND pp.company_id = %s
                    GROUP BY pp.name, he.name ORDER BY hours DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                raw_rows = env.cr.dictfetchall()

                rows = [{'Project': r['project'],
                         'Employee': r['employee'] or t('Not available'),
                         'Hours': float(r['hours'] or 0)} for r in raw_rows]

                table = render_table(t, rows, columns=['Project', 'Employee', 'Hours'])
                self._post(ctx,
                    f"📊 **{t('Hours')}**\n"
                    f"{t('Period')}: {date_from} → {date_to}\n\n{table}"
                )

            # ── 10. Project Financial Status ─────────────────────
            elif report == 'project_financial':
                self._report_project_financial(args, ctx)

            else:
                available = ['profit_by_category', 'revenue_by_partner', 'top_products',
                             'expense_breakdown', 'invoice_summary', 'stock_valuation',
                             'sales_pipeline', 'project_cost', 'project_financial',
                             'timesheet_hours']
                self._post(ctx,
                    t("Report type '%(type)s' is unknown", type=report) + "\n" +
                    t("Available types: %(types)s", types=', '.join(available)),
                    level='warning'
                )

        except Exception as e:
            _logger.exception("KH_AI: analytics error")
            try:
                env.cr.rollback()
            except Exception:
                pass
            self._post(ctx, f"{t('Error')}:\n{e}", level='error')

        return {}

    # ── Project Financial helper ─────────────────────────────────
    def _report_project_financial(self, args, ctx):
        """Dedicated method for the complex project_financial report."""
        from difflib import SequenceMatcher
        env = request.env
        t = ctx.t
        project_keyword = (args.get('project_name') or '').strip()

        if not project_keyword:
            self._post(ctx, t("Please specify the project name or number"), level='warning')
            return {}

        all_projects = env['project.project'].sudo().search_read(
            [], fields=['id', 'name', 'partner_id', 'date_start', 'date'], limit=500
        )

        kw = project_keyword.lower()
        skip_words = {'project', 'client', 'matar', 'ahmed', 'ahmad', 'saeed', 'salem',
                      'ali', 'omar', 'rashed', 'abdulla', 'khaled', 'mohamed', 'mohammed',
                      'opportunity', 'and', 'the'}

        def word_sim(a, b):
            return SequenceMatcher(None, a.lower(), b.lower()).ratio()

        def score(p):
            n  = str(p.get('name') or '').lower()
            pa = str(p['partner_id'][1] if p.get('partner_id') else '').lower()
            full = n + ' ' + pa
            kw_words = [w for w in kw.split() if len(w) > 2 and w not in skip_words]
            if not kw_words:
                kw_words = [w for w in kw.split() if len(w) > 2]
            pn_words = [w for w in re.split(r'[\s\-|:]+', full) if len(w) > 2]
            total = 0.0
            for kw_word in kw_words:
                best = max((word_sim(kw_word, pw) for pw in pn_words), default=0)
                if best > 0.75:
                    total += 4 * best
                elif best > 0.6:
                    total += 2 * best
            num = re.search(r'\d{4,5}', kw)
            if num and num.group() in n:
                total += 10
            return total

        ranked = sorted(all_projects, key=score, reverse=True)
        best = ranked[0] if ranked else None
        best_score = score(best) if best else 0

        if not best or best_score < 0.5:
            self._post(ctx, t("No project matching '%(keyword)s'", keyword=project_keyword), level='warning')
            return {}

        proj = best
        partner    = proj['partner_id'][1] if proj.get('partner_id') else '-'
        partner_id = proj['partner_id'][0] if proj.get('partner_id') else None

        # Find similar partners by family name
        combined = str(proj.get('name') or '') + ' ' + str(proj['partner_id'][1] if proj.get('partner_id') else '')
        eng_words = [w for w in re.findall(r'[A-Za-z]{5,}', combined) if w.lower() not in skip_words]
        family_name = max(eng_words, key=len) if eng_words else ''

        all_partner_ids = [partner_id] if partner_id else []
        if family_name:
            variants = [family_name]
            if family_name.lower().startswith('al') and len(family_name) > 4:
                variants.append(family_name[2:])
            seen_ids = set(all_partner_ids)
            for v in variants:
                similar = env['res.partner'].sudo().search_read(
                    [('name', 'ilike', v)], fields=['id'], limit=20
                )
                for p in similar:
                    if p['id'] not in seen_ids:
                        all_partner_ids.append(p['id'])
                        seen_ids.add(p['id'])
        all_partner_ids = list(set(all_partner_ids))

        # Customer invoices
        total_invoiced = total_paid = total_due = 0.0
        inv_count = 0
        if all_partner_ids:
            inv = env['account.move'].read_group(
                [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                 ('partner_id', 'in', all_partner_ids), ('company_id', '=', env.company.id)],
                fields=['amount_total:sum', 'amount_residual:sum', 'id:count'], groupby=[],
            )
            if inv:
                total_invoiced = float(inv[0].get('amount_total') or 0)
                total_due      = float(inv[0].get('amount_residual') or 0)
                total_paid     = total_invoiced - total_due
                inv_count      = int(inv[0].get('id') or 0)

        # Vendor bills
        total_bills = 0.0
        bill_count = 0
        if all_partner_ids:
            bills = env['account.move'].read_group(
                [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                 ('partner_id', 'in', all_partner_ids), ('company_id', '=', env.company.id)],
                fields=['amount_total:sum', 'id:count'], groupby=[],
            )
            if bills:
                total_bills = float(bills[0].get('amount_total') or 0)
                bill_count  = int(bills[0].get('id') or 0)

        # Analytic lines
        analytic_lines = env['account.analytic.line'].search_read(
            [('project_id', '=', proj['id']), ('amount', '<', 0)], fields=['amount'],
        )
        analytic_cost = abs(sum(float(l['amount']) for l in analytic_lines))

        total_cost = total_bills + analytic_cost
        profit     = total_invoiced - total_cost
        margin_pct = round(profit / total_invoiced * 100, 1) if total_invoiced else 0

        body = (
            f"📊 **{t('Project Financial Status')}**\n\n"
            f"**{proj['name']}**\n"
            f"{t('Client')}: {partner}\n"
            f"{t('Period')}: {proj.get('date_start') or '-'} → {proj.get('date') or '-'}\n\n"
            f"**{t('Customer Invoices')}** ({inv_count}):\n"
            f"  • {t('Total')}: **{total_invoiced:,.2f}**\n"
            f"  • {t('Paid')}: **{total_paid:,.2f}**\n"
            f"  • {t('Outstanding')}: **{total_due:,.2f}**\n\n"
            f"**{t('Expenses')}** ({bill_count} {t('Vendor Bills')} + {t('Analytic Costs')}):\n"
            f"  • {t('Vendor Bills')}: **{total_bills:,.2f}**\n"
            f"  • {t('Analytic Costs')}: **{analytic_cost:,.2f}**\n\n"
            f"**{t('Net Profit')}: {profit:,.2f} {margin_icon(margin_pct)} ({margin_pct}%)**"
        )
        self._post(ctx, body)
        return {}