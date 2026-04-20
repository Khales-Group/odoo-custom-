# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║           KHALES AI - CLEAN AGENT ENGINE v3.0                   ║
║           Odoo 19 | Gemini 2.5 Flash | Data-Provider Pattern    ║
╠══════════════════════════════════════════════════════════════════╣
║  Architecture:                                                   ║
║  Pass 1 → JSON router (intent + lang + context)                 ║
║  Pass 2 → Tools return RAW DATA, Gemini formats naturally       ║
║  Pass 3 → Gemini writes the reply in user's language            ║
║  No _t() dictionary. No hardcoded Arabic strings.               ║
╚══════════════════════════════════════════════════════════════════╝
"""

import base64
import json
import logging
import re
from difflib import SequenceMatcher

from markupsafe import Markup

from odoo import fields, http, models
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.addons.ai.controllers.main import AIController

_logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ══════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════

AGENT_PERSONA = "🤖 [Khales AI]"

READABLE_MODELS = {
    'res.partner':            ['name', 'email', 'phone', 'vat', 'is_company', 'street', 'city'],
    'crm.lead':               ['name', 'partner_name', 'email_from', 'phone', 'stage_id', 'description'],
    'account.move':           ['name', 'partner_id', 'amount_total', 'state', 'move_type', 'invoice_date'],
    'purchase.order':         ['name', 'partner_id', 'amount_total', 'state', 'date_order'],
    'purchase.order.line':    ['name', 'order_id', 'partner_id', 'product_id', 'price_unit', 'product_qty'],
    'sale.order':             ['name', 'partner_id', 'amount_total', 'state', 'date_order'],
    'project.task':           ['name', 'project_id', 'user_ids', 'stage_id', 'date_deadline'],
    'hr.employee':            ['name', 'job_title', 'department_id', 'work_email'],
    'product.product':        ['name', 'list_price', 'qty_available', 'categ_id'],
    'stock.picking':          ['name', 'partner_id', 'state', 'scheduled_date', 'picking_type_id'],
    'account.bank.statement': ['name', 'date', 'balance_start', 'balance_end_real', 'journal_id'],
}

SYSTEM_INSTRUCTION = f"""{AGENT_PERSONA} is an elite ERP assistant and business consultant built into Odoo 19.

## IDENTITY
- Start EVERY reply with "{AGENT_PERSONA}: "
- Reply in the SAME language the user used (detected automatically)
- Be concise, direct, and professional

## TOOL SELECTION

### ai_dynamic_read — search/find/list internal Odoo data
Trigger: "find", "search", "show", "list", "ابحث", "دور", "اعرض"
- For vendor/supplier search: search BOTH English AND Arabic keywords
- For product suppliers: use model='purchase.order.line' to find past orders

### ai_analytics — financial reports and KPIs
- 'project_financial' + project_name → full financial status of one project
- 'profit_by_category' → margins by product category
- 'revenue_by_partner' → revenue by customer
- 'top_products' → best selling products
- 'expense_breakdown' → expense analysis
- 'invoice_summary' → invoice overview
- 'project_cost' → project costs
- 'sales_pipeline' → CRM pipeline

### CONTEXT RULE — most important:
If user says "financial report" / "finical report" / "تقرير مالي" after mentioning a person/project:
→ report_type='project_financial', extract project_name from conversation history
If user says "yes this is it" / "this one" / "تبعو" after identifying a record:
→ use that record in the next action

### ai_create_rfq — create purchase order / طلب تسعير
Triggers: "طلب تسعير", "RFQ", "خلينا نجهز", "send quote", "order from"
→ Call DIRECTLY, no pre-search needed. Tool handles vendor lookup automatically.
→ NEVER ask "هل تريد إنشاء RFQ؟" — just do it when asked.
→ After user picks a vendor from a list you showed → call ai_create_rfq immediately.

### ai_create_invoice / ai_create_lead / ai_create_bank_stmt
Only when explicitly commanded.

### ai_update_records — bulk update existing records
Triggers: "set account", "update transactions", "change account for partner X"

### ai_ask_user — clarify with options
Use when genuinely unclear. Offer 2-3 concrete paths. NEVER to refuse.
After showing options, if user picks a NUMBER → interpret as the choice, ask for missing info if needed.

## WEB SEARCH (Google Grounding)
Used automatically for external info: supplier prices, company contacts, market data.
Always search in UAE/Dubai context unless user specifies otherwise.
NEVER say "I cannot search the internet" — just use grounding.

## EXPERT BEHAVIOR
NEVER say "I cannot do X". Instead offer options or do it.
If asked for cheapest supplier → search internally AND online, compare both.
Always move the conversation FORWARD.
"""


# ══════════════════════════════════════════════════════════════════
#  MODEL EXTENSION
# ══════════════════════════════════════════════════════════════════

class AiAgentSource(models.Model):
    _inherit = 'ai.agent.source'
    type = fields.Selection([
        ('file', 'File'), ('url', 'URL'), ('manual', 'Manual Text'),
    ], string='Source Type', required=True, default='file')


# ══════════════════════════════════════════════════════════════════
#  TOOL DEFINITIONS
# ══════════════════════════════════════════════════════════════════

def _build_tools() -> types.Tool:

    ai_dynamic_read = types.FunctionDeclaration(
        name="ai_dynamic_read",
        description=(
            "Search Odoo records. Use for find/search/list requests. "
            "For supplier/vendor searches: search BOTH English and Arabic keywords. "
            "To find vendors by product: use model='purchase.order.line'."
        ),
        parameters=types.Schema(type=types.Type.OBJECT, properties={
            "model_name": types.Schema(type=types.Type.STRING,
                description="Odoo model: res.partner, crm.lead, account.move, purchase.order, "
                            "purchase.order.line, sale.order, project.task, product.product"),
            "keyword":    types.Schema(type=types.Type.STRING, description="Search keyword"),
            "filters":    types.Schema(type=types.Type.STRING, description="Extra Odoo domain as JSON"),
            "limit":      types.Schema(type=types.Type.INTEGER, description="Max results (default 10)"),
        }, required=["model_name"])
    )

    ai_analytics = types.FunctionDeclaration(
        name="ai_analytics",
        description=(
            "Run financial analytics. Use for reports, margins, project status, KPIs. "
            "report_type options: profit_by_category, revenue_by_partner, top_products, "
            "expense_breakdown, invoice_summary, project_cost, project_financial, sales_pipeline. "
            "Use project_financial + project_name when user asks about a specific person/project."
        ),
        parameters=types.Schema(type=types.Type.OBJECT, properties={
            "report_type":   types.Schema(type=types.Type.STRING),
            "project_name":  types.Schema(type=types.Type.STRING,
                description="For project_financial: name/keyword to find project. "
                            "Extract from conversation history if not in current message."),
            "date_from":     types.Schema(type=types.Type.STRING, description="YYYY-MM-DD"),
            "date_to":       types.Schema(type=types.Type.STRING, description="YYYY-MM-DD"),
            "limit":         types.Schema(type=types.Type.INTEGER),
        }, required=["report_type"])
    )

    ai_create_lead = types.FunctionDeclaration(
        name="ai_create_lead",
        description="Create CRM lead. Only when explicitly commanded.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={
            "name":             types.Schema(type=types.Type.STRING),
            "partner_name":     types.Schema(type=types.Type.STRING),
            "email_from":       types.Schema(type=types.Type.STRING),
            "phone":            types.Schema(type=types.Type.STRING),
            "description":      types.Schema(type=types.Type.STRING),
            "expected_revenue": types.Schema(type=types.Type.NUMBER),
        }, required=["name"])
    )

    ai_create_invoice = types.FunctionDeclaration(
        name="ai_create_invoice",
        description="Create customer invoice (out_invoice) or vendor bill (in_invoice).",
        parameters=types.Schema(type=types.Type.OBJECT, properties={
            "move_type":    types.Schema(type=types.Type.STRING, description="out_invoice or in_invoice"),
            "partner_name": types.Schema(type=types.Type.STRING),
            "partner_vat":  types.Schema(type=types.Type.STRING),
            "invoice_date": types.Schema(type=types.Type.STRING),
            "lines": types.Schema(type=types.Type.ARRAY, items=types.Schema(
                type=types.Type.OBJECT, properties={
                    "description": types.Schema(type=types.Type.STRING),
                    "quantity":    types.Schema(type=types.Type.NUMBER),
                    "price_unit":  types.Schema(type=types.Type.NUMBER),
                })),
        }, required=["move_type", "partner_name", "lines"])
    )

    ai_create_bank_stmt = types.FunctionDeclaration(
        name="ai_create_bank_stmt",
        description="Create accounting bank statement.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={
            "reference":        types.Schema(type=types.Type.STRING),
            "date":             types.Schema(type=types.Type.STRING),
            "starting_balance": types.Schema(type=types.Type.NUMBER),
            "ending_balance":   types.Schema(type=types.Type.NUMBER),
            "lines": types.Schema(type=types.Type.ARRAY, items=types.Schema(
                type=types.Type.OBJECT, properties={
                    "date":   types.Schema(type=types.Type.STRING),
                    "label":  types.Schema(type=types.Type.STRING),
                    "amount": types.Schema(type=types.Type.NUMBER,
                        description="POSITIVE=credit, NEGATIVE=debit"),
                })),
        }, required=["reference", "date", "starting_balance", "ending_balance", "lines"])
    )

    ai_create_rfq = types.FunctionDeclaration(
        name="ai_create_rfq",
        description=(
            "Create RFQ/Purchase Order. "
            "Triggers: طلب تسعير, RFQ, خلينا نجهز, send quote, order from vendor. "
            "Call DIRECTLY — handles vendor creation automatically. "
            "If no email: searches internet automatically."
        ),
        parameters=types.Schema(type=types.Type.OBJECT, properties={
            "vendor_name":  types.Schema(type=types.Type.STRING),
            "vendor_email": types.Schema(type=types.Type.STRING),
            "vendor_phone": types.Schema(type=types.Type.STRING),
            "notes":        types.Schema(type=types.Type.STRING),
            "products": types.Schema(type=types.Type.ARRAY, items=types.Schema(
                type=types.Type.OBJECT, properties={
                    "name":     types.Schema(type=types.Type.STRING),
                    "quantity": types.Schema(type=types.Type.NUMBER),
                    "price":    types.Schema(type=types.Type.NUMBER),
                })),
        }, required=["vendor_name", "products"])
    )

    ai_update_records = types.FunctionDeclaration(
        name="ai_update_records",
        description=(
            "Bulk update existing Odoo records. "
            "Use for: 'set account for partner X', 'update transactions', 'change account on bank lines'."
        ),
        parameters=types.Schema(type=types.Type.OBJECT, properties={
            "operation":    types.Schema(type=types.Type.STRING,
                description="set_bank_statement_account | set_invoice_account"),
            "partner_name": types.Schema(type=types.Type.STRING),
            "account_code": types.Schema(type=types.Type.STRING),
            "account_name": types.Schema(type=types.Type.STRING),
        }, required=["operation"])
    )

    ai_ask_user = types.FunctionDeclaration(
        name="ai_ask_user",
        description=(
            "Ask user to clarify or choose between options. "
            "Use when genuinely unclear — offer concrete paths. NEVER to refuse. "
            "If user picked a number from your previous options: ask for missing info."
        ),
        parameters=types.Schema(type=types.Type.OBJECT, properties={
            "question": types.Schema(type=types.Type.STRING),
            "options":  types.Schema(type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="2-4 options. Leave empty if asking for free text."),
            "context":  types.Schema(type=types.Type.STRING),
        }, required=["question"])
    )

    return types.Tool(function_declarations=[
        ai_dynamic_read, ai_analytics, ai_create_lead, ai_create_invoice,
        ai_create_bank_stmt, ai_create_rfq, ai_update_records, ai_ask_user,
    ])


# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════

def _to_html(text: str) -> Markup:
    text = re.sub(r'\*\*(.*?)\*\*', r'<b style="color:#017E84">\1</b>', text)
    text = re.sub(r'^### (.+)$', r'<h4 style="margin:8px 0">\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$',  r'<h3 style="margin:8px 0">\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^\* (.+)$',  r'<li>\1</li>', text, flags=re.MULTILINE)
    text = re.sub(r'^- (.+)$',   r'<li>\1</li>', text, flags=re.MULTILINE)
    text = text.replace('\n', '<br/>')
    return Markup(f"<div style='line-height:1.8;font-size:14px;direction:auto'>{text}</div>")


def _word_fuzzy_score(keyword: str, project_name: str) -> float:
    """Word-level fuzzy matching — handles typos like 'dharei' vs 'dhaheri'"""
    skip = {'project', 'client', 'matar', 'ahmed', 'ahmad', 'saeed', 'salem',
            'ali', 'omar', 'rashed', 'abdulla', 'khaled', 'mohamed', 'mohammed',
            'opportunity', 'and', 'the'}
    kw_l  = keyword.lower()
    pn_l  = project_name.lower()
    kw_words = [w for w in kw_l.split() if len(w) > 2 and w not in skip] or \
               [w for w in kw_l.split() if len(w) > 2]
    pn_words = [w for w in re.split(r'[\s\-|:]+', pn_l) if len(w) > 2]
    total = 0.0
    for kw_word in kw_words:
        best = max((SequenceMatcher(None, kw_word, pw).ratio() for pw in pn_words), default=0)
        if best > 0.75:   total += 4 * best
        elif best > 0.6:  total += 2 * best
    num = re.search(r'\d{4,5}', kw_l)
    if num and num.group() in pn_l:
        total += 10
    return total


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
            return {'error': 'google-genai not installed'}

        # ── 1. Parse input ────────────────────────────────────────
        prompt, mail_message_id, chat_history, attachments = self._parse_input(kwargs)

        # ── 2. Get API key ────────────────────────────────────────
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            self._post_message("⛔ Gemini API key not configured.", mail_message_id)
            return {}

        try:
            client = genai.Client(api_key=api_key)

            # ── PASS 1: JSON Router (intent + language) ───────────
            last_user_msg = ""
            for line in reversed(chat_history.splitlines()):
                if line.startswith('User:'):
                    last_user_msg = line[5:].strip()
                    break

            # Use Odoo's known user language as hint
            odoo_lang = request.env.context.get('lang', 'en_US')
            lang_hint  = 'ar' if odoo_lang.startswith('ar') else 'en'

            router_prompt = (
                f"Analyze this user message in an ERP chat. "
                f"Odoo UI language hint: {lang_hint}.\n\n"
                f"Conversation context (last 3 exchanges):\n{chr(10).join(chat_history.splitlines()[-6:])}\n\n"
                f"Latest message: {last_user_msg}\n\n"
                "Return ONLY valid JSON with:\n"
                '{"intent": "ODOO_ACTION|ODOO_READ|WEB_SEARCH|CHAT", '
                '"lang": "ar|en", '
                '"summary": "one line of what user wants"}\n\n'
                "ODOO_ACTION: create/update/delete records, RFQ, invoice, lead\n"
                "ODOO_READ: search/find/analyze/report internal data, financial status\n"
                "WEB_SEARCH: external internet info (prices, suppliers, news)\n"
                "CHAT: greetings, unrelated questions\n\n"
                "IMPORTANT: 'financial report' after mentioning a person → ODOO_READ\n"
                "IMPORTANT: 'طلب تسعير' / 'RFQ' / 'خلينا نجهز' → ODOO_ACTION"
            )

            router_resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[router_prompt],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )

            try:
                meta   = json.loads(router_resp.text or '{}')
                intent = meta.get('intent', 'CHAT').upper()
                lang   = meta.get('lang', lang_hint)
            except Exception:
                intent = 'CHAT'
                lang   = lang_hint

            _logger.info(f"KH_AI v3: intent={intent} lang={lang} summary={meta.get('summary','')}")

            # ── PASS 2: Execute ───────────────────────────────────
            gemini_contents = self._build_contents(chat_history, attachments)

            if intent in ('ODOO_ACTION', 'ODOO_READ'):
                config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.3,
                    tools=[_build_tools()],
                )
            else:
                config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.4,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=gemini_contents,
                config=config,
            )

        except Exception as e:
            _logger.exception("KH_AI v3: API error")
            self._post_message(f"⛔ Gemini error:\n{e}", mail_message_id)
            return {}

        # ── PASS 3: Route response ────────────────────────────────
        if response.function_calls:
            func        = response.function_calls[0]
            tool_result = self._handle_tool_call(func, mail_message_id, lang)

            # If it's an Odoo UI action → return directly
            if isinstance(tool_result, dict) and tool_result.get('type') == 'ir.actions.act_window':
                return tool_result

            # If tool returned DATA → feed back to Gemini for natural language reply
            if isinstance(tool_result, dict) and 'data' in tool_result:
                try:
                    second_resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=gemini_contents + [
                            types.Part.from_function_response(
                                name=func.name,
                                response=tool_result,
                            )
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.3,
                            tools=[_build_tools()],
                        ),
                    )
                    text = getattr(second_resp, 'text', '') or ''
                    if not text.startswith(AGENT_PERSONA):
                        text = f"{AGENT_PERSONA}: {text}"
                    self._post_message(text, mail_message_id)
                except Exception as e:
                    _logger.exception("KH_AI v3: Pass 3 error")
                    # Fallback: format data ourselves
                    self._post_data_fallback(tool_result, func.name, mail_message_id, lang)
                return {}

            return tool_result or {}

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
        prompt = ""
        mail_message_id = kwargs.get('mail_message_id')
        chat_history = ""
        attachments = request.env['ir.attachment'].sudo()

        if mail_message_id:
            msg = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if msg.exists():
                prompt = html2plaintext(msg.body) if msg.body else ""
                attachments = msg.attachment_ids
                if msg.model == 'discuss.channel':
                    history_msgs = request.env['mail.message'].sudo().search(
                        [('model', '=', 'discuss.channel'), ('res_id', '=', msg.res_id)],
                        order='id desc', limit=10
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
                    [int(i) for i in att_ids if str(i).isdigit()])
            chat_history = f"User: {prompt}"

        return prompt, mail_message_id, chat_history, attachments

    # ─────────────────────────────────────────────────────────────
    # CONTENT BUILDER
    # ─────────────────────────────────────────────────────────────
    def _build_contents(self, chat_history: str, attachments) -> list:
        contents = [f"--- CONVERSATION ---\n{chat_history}\n--- END ---"]
        for att in attachments:
            try:
                raw = att.raw or (base64.b64decode(att.datas) if att.datas else b'')
                if raw:
                    contents.append(types.Part.from_bytes(
                        data=raw, mime_type=att.mimetype or 'application/octet-stream'))
            except Exception:
                pass
        return contents

    # ─────────────────────────────────────────────────────────────
    # MESSAGE POSTER
    # ─────────────────────────────────────────────────────────────
    def _post_message(self, text: str, mail_message_id):
        if not mail_message_id:
            return
        try:
            msg_record = request.env['mail.message'].sudo().browse(int(mail_message_id))
            if not msg_record.exists() or msg_record.model != 'discuss.channel':
                return
            channel    = request.env['discuss.channel'].sudo().browse(msg_record.res_id)
            ai_agent   = request.env['ai.agent'].sudo().search([('partner_id', '!=', False)], limit=1)
            author_id  = ai_agent.partner_id.id if ai_agent else request.env.user.partner_id.id
            channel.message_post(body=_to_html(text), author_id=author_id, message_type='comment')
        except Exception:
            _logger.exception("KH_AI v3: failed to post message")

    # ─────────────────────────────────────────────────────────────
    # TOOL DISPATCHER
    # ─────────────────────────────────────────────────────────────
    def _handle_tool_call(self, func, mail_message_id, lang='en'):
        name = func.name
        args = func.args
        _logger.info(f"KH_AI v3: tool={name} lang={lang}")

        try:
            if name == "ai_dynamic_read":     return self._tool_dynamic_read(args, mail_message_id, lang)
            elif name == "ai_analytics":      return self._tool_analytics(args, mail_message_id, lang)
            elif name == "ai_create_lead":    return self._tool_create_lead(args, mail_message_id)
            elif name == "ai_create_invoice": return self._tool_create_invoice(args, mail_message_id)
            elif name == "ai_create_bank_stmt": return self._tool_create_bank_stmt(args, mail_message_id)
            elif name == "ai_create_rfq":     return self._tool_create_rfq(args, mail_message_id, lang)
            elif name == "ai_update_records": return self._tool_update_records(args, mail_message_id)
            elif name == "ai_ask_user":       return self._tool_ask_user(args, mail_message_id)
            else:
                self._post_message(f"{AGENT_PERSONA}: Unknown tool: {name}", mail_message_id)
                return {}
        except AccessError:
            self._post_message(f"{AGENT_PERSONA}: ⛔ Permission denied.", mail_message_id)
            return {}
        except UserError as e:
            self._post_message(f"{AGENT_PERSONA}: ⚠️ {e}", mail_message_id)
            return {}
        except Exception as e:
            _logger.exception(f"KH_AI v3: tool {name} failed")
            try: request.env.cr.rollback()
            except Exception: pass
            self._post_message(f"{AGENT_PERSONA}: ⛔ Error in {name}:\n{e}", mail_message_id)
            return {}

    # ─────────────────────────────────────────────────────────────
    # FALLBACK DATA FORMATTER (when Pass 3 fails)
    # ─────────────────────────────────────────────────────────────
    def _post_data_fallback(self, tool_result: dict, tool_name: str, mail_message_id, lang: str):
        data  = tool_result.get('data', tool_result)
        count = tool_result.get('count', '')
        lines = [f"{AGENT_PERSONA}: 🔍 {count} result(s) from `{tool_name}`:\n"]
        if isinstance(data, list):
            for r in data[:15]:
                if isinstance(r, dict):
                    name = r.get('name') or r.get('display_name') or str(r.get('id', ''))
                    lines.append(f"- **{name}**")
        self._post_message("\n".join(lines), mail_message_id)

    # ══════════════════════════════════════════════════════════════
    #  TOOL: DYNAMIC READ  → returns data dict for Pass 3
    # ══════════════════════════════════════════════════════════════
    def _tool_dynamic_read(self, args, mail_message_id, lang='en'):
        env        = request.env
        model_name = args.get('model_name', '').strip()
        keyword    = args.get('keyword', '').strip()
        filters    = args.get('filters', '').strip()
        limit      = min(int(args.get('limit', 10)), 50)

        if model_name not in READABLE_MODELS:
            self._post_message(f"{AGENT_PERSONA}: ⛔ Model '{model_name}' not allowed.", mail_message_id)
            return {}

        allowed_fields = READABLE_MODELS[model_name]
        domain = []
        if keyword:
            domain.append(('name', 'ilike', keyword))
        if filters:
            try:
                domain.extend(json.loads(filters))
            except Exception:
                pass

        records = env[model_name].search_read(domain, fields=allowed_fields, limit=limit)

        # Return data for Gemini to format naturally
        return {
            'data':       records,
            'count':      len(records),
            'model':      model_name,
            'keyword':    keyword,
            'no_results': len(records) == 0,
        }

    # ══════════════════════════════════════════════════════════════
    #  TOOL: ANALYTICS  → returns data dict for Pass 3
    # ══════════════════════════════════════════════════════════════
    def _tool_analytics(self, args, mail_message_id, lang='en'):
        env        = request.env
        report     = args.get('report_type', '')
        date_from  = args.get('date_from') or str(fields.Date.today().replace(month=1, day=1))
        date_to    = args.get('date_to')   or str(fields.Date.today())
        limit      = min(int(args.get('limit', 10)), 50)

        try:
            if report == 'profit_by_category':
                env.cr.execute("""
                    SELECT
                        COALESCE(pc.complete_name, 'Unknown') AS category,
                        SUM(aml.quantity * aml.price_unit)     AS revenue,
                        SUM(aml.quantity * pp.standard_price)  AS cost
                    FROM account_move_line aml
                    JOIN account_move am     ON am.id  = aml.move_id
                    JOIN product_product pp  ON pp.id  = aml.product_id
                    JOIN product_template pt ON pt.id  = pp.product_tmpl_id
                    JOIN product_category pc ON pc.id  = pt.categ_id
                    WHERE am.move_type = 'out_invoice' AND am.state = 'posted'
                      AND am.invoice_date BETWEEN %s AND %s AND am.company_id = %s
                      AND aml.product_id IS NOT NULL
                    GROUP BY pc.complete_name ORDER BY revenue DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()
                data = [{'category': r['category'],
                         'revenue': float(r['revenue'] or 0),
                         'cost': float(r['cost'] or 0),
                         'profit': float(r['revenue'] or 0) - float(r['cost'] or 0),
                         'margin_pct': round((float(r['revenue'] or 0) - float(r['cost'] or 0)) /
                                             float(r['revenue']) * 100, 1) if r['revenue'] else 0}
                        for r in rows]
                return {'report': report, 'period': f"{date_from} → {date_to}", 'data': data, 'count': len(data)}

            elif report == 'revenue_by_partner':
                env.cr.execute("""
                    SELECT rp.name AS partner, COUNT(am.id) AS invoices,
                           SUM(am.amount_untaxed) AS revenue, SUM(am.amount_tax) AS tax
                    FROM account_move am JOIN res_partner rp ON rp.id = am.partner_id
                    WHERE am.move_type='out_invoice' AND am.state='posted'
                      AND am.invoice_date BETWEEN %s AND %s AND am.company_id=%s
                    GROUP BY rp.name ORDER BY revenue DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()
                return {'report': report, 'period': f"{date_from} → {date_to}",
                        'data': [{'partner': r['partner'], 'invoices': r['invoices'],
                                  'revenue': float(r['revenue'] or 0), 'tax': float(r['tax'] or 0)}
                                 for r in rows], 'count': len(rows)}

            elif report == 'top_products':
                env.cr.execute("""
                    SELECT COALESCE(pt.name->>'en_US', pt.name::text) AS product,
                           SUM(aml.quantity) AS qty, SUM(aml.quantity * aml.price_unit) AS revenue
                    FROM account_move_line aml
                    JOIN account_move am     ON am.id = aml.move_id
                    JOIN product_product pp  ON pp.id = aml.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE am.move_type='out_invoice' AND am.state='posted'
                      AND am.invoice_date BETWEEN %s AND %s AND aml.product_id IS NOT NULL
                      AND am.company_id=%s
                    GROUP BY pt.name ORDER BY revenue DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()
                return {'report': report, 'period': f"{date_from} → {date_to}",
                        'data': [{'product': r['product'], 'qty_sold': float(r['qty'] or 0),
                                  'revenue': float(r['revenue'] or 0)} for r in rows],
                        'count': len(rows)}

            elif report == 'expense_breakdown':
                env.cr.execute("""
                    SELECT COALESCE(aa.name->>'en_US', aa.name::text) AS account,
                           SUM(aml.debit - aml.credit) AS amount
                    FROM account_move_line aml
                    JOIN account_account aa ON aa.id = aml.account_id
                    JOIN account_move am     ON am.id = aml.move_id
                    WHERE aa.account_type IN ('expense','expense_depreciation','expense_direct_cost')
                      AND am.state='posted' AND am.date BETWEEN %s AND %s AND am.company_id=%s
                    GROUP BY aa.name ORDER BY amount DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()
                total = sum(float(r['amount'] or 0) for r in rows)
                return {'report': report, 'period': f"{date_from} → {date_to}", 'total': total,
                        'data': [{'account': r['account'], 'amount': float(r['amount'] or 0),
                                  'pct': round(float(r['amount'] or 0) / total * 100, 1) if total else 0}
                                 for r in rows], 'count': len(rows)}

            elif report == 'invoice_summary':
                env.cr.execute("""
                    SELECT move_type, state, COUNT(*) AS cnt, SUM(amount_total) AS total
                    FROM account_move
                    WHERE move_type IN ('out_invoice','in_invoice','out_refund','in_refund')
                      AND invoice_date BETWEEN %s AND %s AND company_id=%s
                    GROUP BY move_type, state ORDER BY move_type, state
                """, (date_from, date_to, env.company.id))
                rows = env.cr.dictfetchall()
                return {'report': report, 'period': f"{date_from} → {date_to}",
                        'data': [{'type': r['move_type'], 'state': r['state'],
                                  'count': r['cnt'], 'total': float(r['total'] or 0)}
                                 for r in rows], 'count': len(rows)}

            elif report == 'project_cost':
                # Via tasks/timesheets
                env.cr.execute("""
                    SELECT COALESCE(pp.name->>'en_US', pp.name::text) AS project,
                           SUM(aal.amount) AS cost, SUM(aal.unit_amount) AS hours,
                           COUNT(DISTINCT aal.employee_id) AS team
                    FROM account_analytic_line aal
                    JOIN project_task pt2  ON pt2.id = aal.task_id
                    JOIN project_project pp ON pp.id = pt2.project_id
                    WHERE aal.date BETWEEN %s AND %s AND pp.company_id=%s AND aal.task_id IS NOT NULL
                    GROUP BY pp.name ORDER BY cost DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()
                if not rows:
                    projects = env['project.project'].search_read(
                        [('company_id', '=', env.company.id)],
                        fields=['name', 'allocated_hours'], limit=limit)
                    return {'report': report, 'data': projects, 'count': len(projects),
                            'note': 'No analytic data — showing project list with allocated hours'}
                return {'report': report, 'period': f"{date_from} → {date_to}",
                        'data': [{'project': r['project'], 'cost': float(r['cost'] or 0),
                                  'hours': float(r['hours'] or 0), 'team': int(r['team'] or 0)}
                                 for r in rows], 'count': len(rows)}

            elif report == 'sales_pipeline':
                env.cr.execute("""
                    SELECT cs.name AS stage, COUNT(cl.id) AS cnt,
                           SUM(cl.expected_revenue) AS expected, AVG(cl.probability) AS prob
                    FROM crm_lead cl JOIN crm_stage cs ON cs.id = cl.stage_id
                    WHERE cl.type='opportunity' AND cl.active=true AND cl.company_id=%s
                    GROUP BY cs.name, cs.sequence ORDER BY cs.sequence
                """, (env.company.id,))
                rows = env.cr.dictfetchall()
                return {'report': report,
                        'data': [{'stage': r['stage'], 'count': r['cnt'],
                                  'expected': float(r['expected'] or 0),
                                  'probability': round(float(r['prob'] or 0), 0)}
                                 for r in rows], 'count': len(rows)}

            elif report == 'project_financial':
                return self._project_financial_data(args, mail_message_id)

            else:
                available = ['profit_by_category', 'revenue_by_partner', 'top_products',
                             'expense_breakdown', 'invoice_summary', 'project_cost',
                             'project_financial', 'sales_pipeline']
                return {'error': f"Unknown report_type '{report}'", 'available': available}

        except Exception as e:
            _logger.exception("KH_AI v3: analytics error")
            try: request.env.cr.rollback()
            except Exception: pass
            return {'error': str(e), 'report': report}

    def _project_financial_data(self, args, mail_message_id):
        """Returns raw financial data for a project — Gemini formats it"""
        env = request.env
        project_keyword = (args.get('project_name') or '').strip()

        if not project_keyword:
            return {'error': 'project_name required', 'hint': 'Extract from conversation history'}

        # Fuzzy match all projects
        all_projects = env['project.project'].sudo().search_read(
            [], fields=['id', 'name', 'partner_id', 'date_start', 'date'], limit=500)

        ranked = sorted(all_projects, key=lambda p: _word_fuzzy_score(project_keyword, str(p.get('name') or '')), reverse=True)
        best_score = _word_fuzzy_score(project_keyword, str(ranked[0].get('name') or '')) if ranked else 0
        _logger.info(f"KH_AI project_financial: kw='{project_keyword}' best='{ranked[0]['name'] if ranked else None}' score={best_score:.2f}")

        if not ranked or best_score < 0.3:
            return {'error': f"No project found matching '{project_keyword}'",
                    'searched': project_keyword}

        proj = ranked[0]
        partner_id = proj['partner_id'][0] if proj.get('partner_id') else None
        partner_name = proj['partner_id'][1] if proj.get('partner_id') else 'Unknown'

        # Find all related partners by family name
        all_partner_ids = [partner_id] if partner_id else []
        family_name = ''
        if proj.get('name'):
            skip = {'project', 'client', 'matar', 'ahmed', 'ahmad', 'saeed', 'salem',
                    'ali', 'omar', 'rashed', 'abdulla', 'khaled', 'mohamed', 'mohammed'}
            eng_words = [w for w in re.findall(r'[A-Za-z]{5,}', str(proj['name']))
                         if w.lower() not in skip]
            if eng_words:
                family_name = max(eng_words, key=len)
                variants = [family_name]
                if family_name.lower().startswith('al') and len(family_name) > 4:
                    variants.append(family_name[2:])
                seen = set(all_partner_ids)
                for v in variants:
                    similar = env['res.partner'].sudo().search_read(
                        [('name', 'ilike', v)], fields=['id'], limit=20)
                    for p in similar:
                        if p['id'] not in seen:
                            all_partner_ids.append(p['id'])
                            seen.add(p['id'])

        # Customer invoices
        invoiced = paid = due = inv_count = 0.0
        if all_partner_ids:
            inv = env['account.move'].read_group(
                [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                 ('partner_id', 'in', all_partner_ids), ('company_id', '=', env.company.id)],
                fields=['amount_total:sum', 'amount_residual:sum', 'id:count'], groupby=[])
            if inv:
                invoiced   = float(inv[0].get('amount_total') or 0)
                due        = float(inv[0].get('amount_residual') or 0)
                paid       = invoiced - due
                inv_count  = int(inv[0].get('id') or 0)

        # Vendor bills
        bills = bill_count = 0.0
        if all_partner_ids:
            b = env['account.move'].read_group(
                [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                 ('partner_id', 'in', all_partner_ids), ('company_id', '=', env.company.id)],
                fields=['amount_total:sum', 'id:count'], groupby=[])
            if b:
                bills      = float(b[0].get('amount_total') or 0)
                bill_count = int(b[0].get('id') or 0)

        # Analytic costs
        analytic_lines = env['account.analytic.line'].search_read(
            [('project_id', '=', proj['id']), ('amount', '<', 0)], fields=['amount'])
        analytic_cost = abs(sum(float(l['amount']) for l in analytic_lines))

        total_cost = bills + analytic_cost
        profit     = invoiced - total_cost
        margin     = round(profit / invoiced * 100, 1) if invoiced else 0

        return {
            'report':       'project_financial',
            'project_name': proj['name'],
            'partner':      partner_name,
            'date_start':   str(proj.get('date_start') or '-'),
            'date_end':     str(proj.get('date') or '-'),
            'invoiced':     invoiced,
            'paid':         paid,
            'due':          due,
            'invoice_count': int(inv_count),
            'vendor_bills': bills,
            'bill_count':   int(bill_count),
            'analytic_cost': analytic_cost,
            'total_cost':   total_cost,
            'profit':       profit,
            'margin_pct':   margin,
            'currency':     env.company.currency_id.name or 'AED',
        }

    # ══════════════════════════════════════════════════════════════
    #  TOOL: CREATE LEAD
    # ══════════════════════════════════════════════════════════════
    def _tool_create_lead(self, args, mail_message_id):
        env     = request.env
        new_lead = env['crm.lead'].create({
            'name':             args.get('name', 'AI Lead'),
            'partner_name':     args.get('partner_name', ''),
            'email_from':       args.get('email_from', ''),
            'phone':            args.get('phone', ''),
            'description':      args.get('description', ''),
            'expected_revenue': float(args.get('expected_revenue', 0.0)),
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'crm.lead',
                'res_id': new_lead.id, 'views': [[False, 'form']], 'target': 'current'}

    # ══════════════════════════════════════════════════════════════
    #  TOOL: CREATE INVOICE
    # ══════════════════════════════════════════════════════════════
    def _tool_create_invoice(self, args, mail_message_id):
        env          = request.env
        move_type    = args.get('move_type', 'out_invoice')
        partner_name = args.get('partner_name', 'Unknown')
        partner      = env['res.partner'].search([('name', '=ilike', partner_name)], limit=1)
        if not partner:
            partner = env['res.partner'].create({'name': partner_name, 'vat': args.get('partner_vat', '')})

        acc_type = 'expense' if move_type == 'in_invoice' else 'income'
        account  = env['account.account'].search(
            [('account_type', '=', acc_type), ('company_ids', 'in', env.company.id)], limit=1)

        invoice_lines = [(0, 0, {
            'name':       l.get('description', 'Item'),
            'quantity':   float(l.get('quantity', 1.0)),
            'price_unit': float(l.get('price_unit', 0.0)),
            'account_id': account.id if account else False,
        }) for l in args.get('lines', [])] or \
        [(0, 0, {'name': 'Item', 'quantity': 1.0, 'price_unit': 0.0,
                 'account_id': account.id if account else False})]

        new_move = env['account.move'].create({
            'move_type':        move_type,
            'partner_id':       partner.id,
            'invoice_date':     args.get('invoice_date') or fields.Date.today(),
            'invoice_line_ids': invoice_lines,
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move',
                'res_id': new_move.id, 'views': [[False, 'form']], 'target': 'current'}

    # ══════════════════════════════════════════════════════════════
    #  TOOL: CREATE BANK STATEMENT
    # ══════════════════════════════════════════════════════════════
    def _tool_create_bank_stmt(self, args, mail_message_id):
        env     = request.env
        journal = env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', env.company.id)], limit=1)
        if not journal:
            self._post_message(f"{AGENT_PERSONA}: ⛔ No bank journal found.", mail_message_id)
            return {}

        stmt_date  = args.get('date') or str(fields.Date.today())
        stmt_lines = [(0, 0, {
            'date':        l.get('date', stmt_date),
            'payment_ref': l.get('label', 'Transaction'),
            'amount':      float(l.get('amount', 0.0)),
        }) for l in args.get('lines', [])]

        new_stmt = env['account.bank.statement'].create({
            'name':             args.get('reference', 'AI Bank Statement'),
            'date':             stmt_date,
            'balance_start':    float(args.get('starting_balance', 0.0)),
            'balance_end_real': float(args.get('ending_balance', 0.0)),
            'journal_id':       journal.id,
            'line_ids':         stmt_lines,
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'account.bank.statement',
                'res_id': new_stmt.id, 'views': [[False, 'form']], 'target': 'current'}

    # ══════════════════════════════════════════════════════════════
    #  TOOL: CREATE RFQ
    # ══════════════════════════════════════════════════════════════
    def _tool_create_rfq(self, args, mail_message_id, lang='en'):
        env          = request.env
        vendor_name  = args.get('vendor_name', '')
        vendor_email = args.get('vendor_email', '')
        vendor_phone = args.get('vendor_phone', '')
        products     = args.get('products', [])

        vendor = env['res.partner'].search([('name', '=ilike', vendor_name)], limit=1)
        if not vendor:
            vendor = env['res.partner'].search([('name', 'ilike', vendor_name)], limit=1)
        if not vendor:
            vendor = env['res.partner'].create({
                'name': vendor_name, 'is_company': True,
                'email': vendor_email, 'phone': vendor_phone,
            })
        else:
            updates = {}
            if vendor_email and not vendor.email: updates['email'] = vendor_email
            if vendor_phone and not vendor.phone: updates['phone'] = vendor_phone
            if updates: vendor.write(updates)

        final_email = vendor_email or vendor.email

        if not final_email:
            self._post_message(
                f"{AGENT_PERSONA}: 🔍 No email for **{vendor_name}** — searching online...",
                mail_message_id)
            try:
                api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
                _client = genai.Client(api_key=api_key)
                for search_prompt in [
                    f"Find official email of '{vendor_name}' company in UAE/Dubai. Return: EMAIL: x@x.com",
                    f"What is the contact email for '{vendor_name}' company? Website and email please.",
                ]:
                    resp = _client.models.generate_content(
                        model="gemini-2.5-flash", contents=[search_prompt],
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0.0))
                    result = getattr(resp, 'text', '') or ''
                    email_match = re.search(r'[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}', result)
                    if email_match:
                        final_email = email_match.group()
                        phone_match = re.search(r'[+\d][\d\s\-]{8,}', result)
                        if phone_match: vendor_phone = phone_match.group().strip()
                        vendor.write({'email': final_email, 'phone': vendor_phone or vendor.phone})
                        _logger.info(f"KH_AI RFQ: found email {final_email} for {vendor_name}")
                        break

                if not final_email:
                    self._post_message(
                        f"{AGENT_PERSONA}: ⚠️ Could not find email for **{vendor_name}**.\n"
                        f"Please add it manually: 'email for {vendor_name} is info@example.com'",
                        mail_message_id)
                    return {}
            except Exception:
                _logger.exception("KH_AI: email search failed")
                self._post_message(
                    f"{AGENT_PERSONA}: ⚠️ No email found for **{vendor_name}**. Please add manually.",
                    mail_message_id)
                return {}

        order_lines = []
        for p in products:
            prod_name = p.get('name', '')
            product   = env['product.product'].search([('name', '=ilike', prod_name)], limit=1)
            if not product:
                product = env['product.product'].create({'name': prod_name, 'type': 'consu'})
            line = {'product_id': product.id, 'name': product.name,
                    'product_qty': float(p.get('quantity', 1.0))}
            if p.get('price'): line['price_unit'] = float(p['price'])
            order_lines.append((0, 0, line))

        new_rfq = env['purchase.order'].create({
            'partner_id': vendor.id,
            'order_line': order_lines,
            'notes':      args.get('notes', ''),
        })
        self._post_message(
            f"{AGENT_PERSONA}: ✅ RFQ created for **{vendor.name}**\n"
            f"• Email: {final_email}\n• Products: {len(order_lines)}",
            mail_message_id)
        return {'type': 'ir.actions.act_window', 'res_model': 'purchase.order',
                'res_id': new_rfq.id, 'views': [[False, 'form']], 'target': 'current'}

    # ══════════════════════════════════════════════════════════════
    #  TOOL: UPDATE RECORDS
    # ══════════════════════════════════════════════════════════════
    def _tool_update_records(self, args, mail_message_id):
        env          = request.env
        operation    = args.get('operation', '')
        partner_name = args.get('partner_name', '')
        account_code = args.get('account_code', '')
        account_name = args.get('account_name', '')

        if operation == 'set_bank_statement_account':
            account = None
            if account_code:
                account = env['account.account'].search([('code', '=', account_code)], limit=1)
            if not account and account_name:
                account = env['account.account'].search([('name', 'ilike', account_name)], limit=1)
            if not account:
                self._post_message(
                    f"{AGENT_PERSONA}: ⛔ Account not found: '{account_code or account_name}'",
                    mail_message_id)
                return {}

            partner = env['res.partner'].search([('name', 'ilike', partner_name)], limit=1) if partner_name else None
            domain  = [('statement_id', '!=', False)]
            if partner:
                domain.append(('partner_id', '=', partner.id))
            elif partner_name:
                domain.append(('payment_ref', 'ilike', partner_name))

            stmt_lines = env['account.bank.statement.line'].sudo().search(domain, limit=200)
            if not stmt_lines:
                self._post_message(
                    f"{AGENT_PERSONA}: 🔍 No bank statement lines found for '{partner_name}'.",
                    mail_message_id)
                return {}

            updated = errors = 0
            for line in stmt_lines:
                try:
                    move_lines = env['account.move.line'].sudo().search([
                        ('statement_line_id', '=', line.id),
                        ('account_id.account_type', 'not in', ['asset_cash', 'liability_current']),
                    ], limit=1)
                    if move_lines:
                        move_lines.sudo().write({'account_id': account.id})
                        updated += 1
                    elif hasattr(line, 'account_id'):
                        line.sudo().write({'account_id': account.id})
                        updated += 1
                    else:
                        errors += 1
                except Exception as e:
                    _logger.warning(f"KH_AI update line {line.id}: {e}")
                    errors += 1

            self._post_message(
                f"{AGENT_PERSONA}: ✅ Updated **{updated}** bank statement lines\n"
                f"• Account: **{account.code} - {account.name}**\n"
                f"• Partner: **{partner.name if partner else partner_name}**"
                + (f"\n• Failed: {errors}" if errors else ""),
                mail_message_id)
            return {}

        self._post_message(f"{AGENT_PERSONA}: ⚠️ Unknown operation: '{operation}'", mail_message_id)
        return {}

    # ══════════════════════════════════════════════════════════════
    #  TOOL: ASK USER
    # ══════════════════════════════════════════════════════════════
    def _tool_ask_user(self, args, mail_message_id):
        question = args.get('question', '')
        options  = args.get('options', [])
        context  = args.get('context', '')
        lines    = [f"{AGENT_PERSONA}: 🤔"]
        if context:
            lines.append(f"_{context}_\n")
        lines.append(f"**{question}**\n")
        for i, opt in enumerate(options, 1):
            lines.append(f"{i}️⃣ {opt}")
        self._post_message("\n".join(lines), mail_message_id)
        return {}