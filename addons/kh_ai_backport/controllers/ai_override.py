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

VENDOR SEARCH RULES:
- User asks "موردين الألمنيوم" or "suppliers of aluminum":
  → Search BOTH Arabic and English: call ai_dynamic_read TWICE:
    1. model='purchase.order.line', keyword='aluminum' (English product name)
    2. model='purchase.order.line', keyword='ألمنيوم' (Arabic product name)
  → This finds vendors who have supplied this product before, regardless of their company name
- User asks "موردين" by company name → model='res.partner', keyword='...'
- NEVER search only in Arabic OR only in English — always try both

### ANALYTICS Tool (ai_analytics):
Use when user asks for reports, margins, trends, KPIs, breakdowns, or project status:
- "profit margins by category"          → report_type='profit_by_category'
- "top selling products"                → report_type='top_products'
- "revenue by customer"                 → report_type='revenue_by_partner'
- "expense breakdown"                   → report_type='expense_breakdown'
- "invoice summary"                     → report_type='invoice_summary'
- "stock valuation"                     → report_type='stock_valuation'
- "sales pipeline"                      → report_type='sales_pipeline'
- "which project costs most"            → report_type='project_cost'
- "show financial status of project X"  → report_type='project_financial', project_name='X'

IMPORTANT: "خلينا نجهز عرض طلب/RFQ لـ X" → ai_create_rfq with vendor_name='X' IMMEDIATELY
Do NOT use ai_dynamic_read before creating RFQ. The tool handles vendor lookup automatically.
- "شو وضع مشروع X ماليا"               → report_type='project_financial', project_name='X'
- "شو مصاريف مشروع X"                  → report_type='project_financial', project_name='X'
- "شو الوضع المالي تبعو/تبعها/عليه"   → SCAN HISTORY for project name, report_type='project_financial'
- "كم فلوس صرفنا على مشروع X"          → report_type='project_financial', project_name='X'

CRITICAL CONTEXT RULE: The user often refers to a project mentioned EARLIER in the conversation
using words like: تبعو, تبعها, عليه, عنه, هذا المشروع, it, this project.
In this case you MUST scan the conversation history, find the project name or number,
and pass it as project_name. NEVER return empty project_name.
Example: User said "Project: 00033 - Ahmed Matar Aldhaheri" then asks "شو الوضع المالي تبعو"
→ extract "00033" from history and pass project_name='00033'.
ALWAYS use this tool for ANY financial/project question. NEVER say "I cannot calculate".

### WRITE Tools (Fixed):
Only use when user EXPLICITLY commands creation/modification:
- ai_create_lead        → "أنشئ lead", "create lead"
- ai_create_invoice     → "أنشئ فاتورة", "create invoice/bill"
- ai_create_bank_stmt   → "أنشئ كشف بنكي", "bank statement"
- ai_create_rfq         → "أنشئ RFQ", "اطلب من مورد"

### CREATE RFQ Pattern:
If user asks to create/send RFQ or طلب تسعير for a vendor:
→ Call ai_create_rfq DIRECTLY. Do NOT search first.
→ The tool handles finding/creating the vendor automatically.
→ Pass vendor_name exactly as mentioned by the user.
→ If you found vendor contact info from web search earlier in the conversation, pass it too.
→ NEVER say "vendor not found" — the tool creates new vendors automatically.
→ The tool will auto-search the internet for email if missing.

### Google Search (Grounding):
For external info (market prices, supplier contacts, news) — 
answer directly using your grounding capability, no tool needed.

## EXPERT SYSTEM BEHAVIOR — NEVER SAY "I CANNOT"
You are an expert ERP consultant. When a request seems outside your tools, NEVER refuse.
Instead, offer concrete options:

Example 1 — User: "دور على أرخص موردين للألمنيوم في دبي"
WRONG: "لا أستطيع البحث عن الأسعار الخارجية"
RIGHT: Use ai_ask_user to offer: 1) بحث داخل النظام  2) بحث على الإنترنت  3) الاثنين

Example 2 — User picks a NUMBER like "2" after you showed options:
CRITICAL: The number is a CHOICE, not data. Look at the previous options you offered.
If option 2 was "إنشاء طلب تسعير" → use ai_ask_user to ask: "ما اسم المورد الذي تريد إرسال الطلب إليه؟"
NEVER interpret a number as a vendor name or product name.

Example 3 — User: "جهزلي تقرير المبيعات"
Don't ask which report. Just run invoice_summary and say "هذا ملخص المبيعات، تريد تفاصيل أكثر؟"

Example 4 — User picks option for RFQ but no vendor name mentioned:
→ use ai_ask_user: "ما اسم المورد؟" before calling ai_create_rfq

RULE: Always move the conversation FORWARD. Numbers are choices, not values.

## SAFETY
- Never invent financial data
- Never guess at financial amounts  
- Ask for clarification ONLY when genuinely ambiguous — offer options, not dead ends
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
            "Create a Request for Quotation (RFQ/Purchase Order). "
            "Trigger phrases: خلينا نجهز عرض طلب, خلينا نبعث طلب, طلب تسعير, RFQ, "
            "ابعث طلب لـ, جهز طلب, اطلب من مورد, send RFQ, create PO. "
            "ALWAYS use this when user wants to request a quote from ANY vendor. "
            "Do NOT pre-check if vendor exists — this tool creates vendors automatically. "
            "Email will be auto-searched online if missing from system."
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


    # ── ANALYTICS ────────────────────────────────────────────────
    ai_analytics = types.FunctionDeclaration(
        name="ai_analytics",
        description=(
            "Run financial/business analytics on Odoo data. "
            "Use for: profit margins, revenue by category, sales trends, "
            "top customers, stock valuation, expense breakdown, KPIs. "
            "This tool does the heavy SQL-level grouping and calculation."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "report_type": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Type of report. One of: "
                        "'profit_by_category', 'revenue_by_partner', 'project_cost', 'project_financial', 'timesheet_hours', "
                        "'top_products', 'expense_breakdown', "
                        "'invoice_summary', 'stock_valuation', "
                        "'sales_pipeline'"
                    )
                ),
                "date_from": types.Schema(
                    type=types.Type.STRING,
                    description="Start date YYYY-MM-DD (optional, defaults to start of current year)"
                ),
                "date_to": types.Schema(
                    type=types.Type.STRING,
                    description="End date YYYY-MM-DD (optional, defaults to today)"
                ),
                "limit": types.Schema(
                    type=types.Type.INTEGER,
                    description="Max rows to return (default 10)"
                ),
                "project_name": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "For report_type='project_financial': the FULL project name or any keyword. "
                        "CRITICAL: Check the entire conversation history for project context. "
                        "If user said 'شو الوضع المالي تبعو' after mentioning a project, "
                        "extract the project name/number from previous messages. "
                        "Pass the COMPLETE project name as mentioned — e.g. "
                        "'Project: 00033 - Ahmed Matar Aldhaheri | احمد الظاهري' or just '00033'. "
                        "NEVER pass an empty string. ALWAYS extract from context if not in current message."
                    )
                ),
            },
            required=["report_type"]
        )
    )

    # ── ASK USER (Clarification with options) ────────────────────
    ai_ask_user = types.FunctionDeclaration(
        name="ai_ask_user",
        description=(
            "Use when you need to clarify HOW to help — present options, or ask for missing info. "
            "Use cases: "
            "1) User needs to choose between paths (internal vs internet search) "
            "2) User picked a numbered option but you need more info (e.g. vendor name for RFQ) "
            "3) Ambiguous request needing clarification "
            "NEVER use to refuse. Always move forward."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "question": types.Schema(
                    type=types.Type.STRING,
                    description="The clarifying question to ask"
                ),
                "options": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                    description="2-4 concrete options OR leave empty if asking for free-text input like vendor name"
                ),
                "context": types.Schema(
                    type=types.Type.STRING,
                    description="Brief explanation of what you understood from the request"
                ),
            },
            required=["question", "options"]
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

class AIControllerOverride(AIController):

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

            # ══════════════════════════════════════════════════════
            # TWO-PASS ROUTER
            # Gemini لا يسمح بدمج google_search مع function_declarations
            # في نفس الطلب. الحل: Pass 1 يصنّف النية، Pass 2 ينفّذ.
            # ══════════════════════════════════════════════════════

            # ── Pass 1: Classify intent (بدون أدوات) ─────────────
            last_user_msg = ""
            for line in reversed(chat_history.splitlines()):
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
                "IMPORTANT: If user says 'خلينا نجهز/نبعث/نعمل X' → ODOO_ACTION\n"
                "IMPORTANT: pronouns (تبعو, تبعها, عليه, هذا) referring to earlier record → ODOO_READ\n\n"
                f"Conversation context:\n{chat_history[-600:]}\n\n"
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

            # ── Pass 2: Execute with correct tool set ─────────────
            if intent in ('ODOO_ACTION', 'ODOO_READ'):
                # Function Calling — بدون google_search
                config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.3,
                    tools=[_build_tools()],
                )
            else:
                # Google Search Grounding — بدون function_declarations
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
            elif name == "ai_analytics":
                return self._tool_analytics(args, mail_message_id)
            elif name == "ai_ask_user":
                return self._tool_ask_user(args, mail_message_id)
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
        if records:
            # عرض خاص لبنود طلبات الشراء
            if model_name == 'purchase.order.line':
                reply_lines = [f"{AGENT_PERSONA}: 🔍 وجدت **{len(records)}** بند شراء يحتوي على '{keyword}':\n"]
                seen_vendors = {}
                for r in records:
                    ptnr = r.get('partner_id')
                    pname = ptnr[1] if isinstance(ptnr,(list,tuple)) and len(ptnr)==2 else str(ptnr or '-')
                    prod = r.get('product_id')
                    prodname = prod[1] if isinstance(prod,(list,tuple)) and len(prod)==2 else str(prod or '-')
                    qty = r.get('product_qty', 0)
                    price = float(r.get('price_unit') or 0)
                    seen_vendors.setdefault(pname, []).append(f"{prodname} × {qty} @ {price:,.2f}")
                for vendor, items in seen_vendors.items():
                    reply_lines.append(f"🏢 **{vendor}**")
                    for item in items:
                        reply_lines.append(f"   • {item}")
                    reply_lines.append("")
                self._post_message("\n".join(reply_lines), mail_message_id)
            else:
                reply_lines = [f"{AGENT_PERSONA}: 🔍 وجدت **{len(records)}** سجل في {model_name}:"]
                for r in records:
                    title = r.get('name') or r.get('display_name') or str(r.get('id'))
                    details = []
                    for fld in allowed_fields:
                        if fld == 'name': continue
                        val = r.get(fld)
                        if val:
                            if isinstance(val, (list, tuple)) and len(val) == 2:
                                val = val[1]
                            details.append(f"{fld}: {val}")
                    detail_str = " | ".join(details[:4]) if details else ""
                    reply_lines.append(f"- **{title}**" + (f" — {detail_str}" if detail_str else ""))
                self._post_message("\n".join(reply_lines), mail_message_id)
        else:
            no_result = f"{AGENT_PERSONA}: 🔍 لم أجد في النظام ما يطابق '{keyword}'."
            if model_name == 'res.partner' and keyword:
                no_result += (f"\n💡 جرب البحث في طلبات الشراء القديمة عن المنتج '{keyword}'")
            self._post_message(no_result, mail_message_id)
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
        # بحث مرن — جزئي أو كامل
        vendor = env['res.partner'].search([('name', '=ilike', vendor_name)], limit=1)
        if not vendor:
            # جرب بحث جزئي
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
            if vendor_email and not vendor.email: updates['email'] = vendor_email
            if vendor_phone and not vendor.phone: updates['phone'] = vendor_phone
            if updates:
                vendor.write(updates)

        # ── تحقق من الإيميل — إلزامي لإرسال الـ RFQ ──────────────
        final_email = vendor_email or vendor.email
        final_phone = vendor_phone or vendor.phone

        if not final_email:
            # ابحث في الإنترنت عن بيانات التواصل
            self._post_message(
                f"{AGENT_PERSONA}: 🔍 المورد **{vendor_name}** ليس لديه إيميل في النظام.\n"
                f"جاري البحث في الإنترنت عن بيانات التواصل...",
                mail_message_id
            )
            # محاولة الحصول على الإيميل عبر Gemini web search
            try:
                from google.genai import types as _types
                _api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
                _gclient = genai.Client(api_key=_api_key)
                # محاولة أولى: بحث مباشر بالاسم
                _search_resp = _gclient.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[f"Search the web for the official contact email and phone of '{vendor_name}'. Return ONLY: EMAIL: xxx@xxx.com | PHONE: +971xxxxxxx"],
                    config=_types.GenerateContentConfig(
                        tools=[_types.Tool(google_search=_types.GoogleSearch())],
                        temperature=0.0,
                    )
                )
                _result = (getattr(_search_resp, 'text', '') or '').strip()

                # محاولة ثانية لو NOT_FOUND: بحث بصيغة مختلفة
                if 'NOT_FOUND' in _result or '@' not in _result:
                    _search_resp2 = _gclient.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[f"What is the official website and email of '{vendor_name}' company? Search online and return the email address."],
                        config=_types.GenerateContentConfig(
                            tools=[_types.Tool(google_search=_types.GoogleSearch())],
                            temperature=0.0,
                        )
                    )
                    _result2 = (getattr(_search_resp2, 'text', '') or '').strip()
                    if '@' in _result2:
                        _result = _result2
                    _logger.info(f"KH_AI email retry result: {_result2[:100]}")
                _logger.info(f"KH_AI RFQ web search result for '{vendor_name}': {_result[:150]}")

                # استخرج الإيميل من النتيجة
                import re as _re3
                _email_match = _re3.search(r'[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}', _result)
                _phone_match = _re3.search(r'[+\d][\d\s\-]{8,}', _result)

                if _email_match:
                    final_email = _email_match.group()
                    if _phone_match and not final_phone:
                        final_phone = _phone_match.group().strip()
                    vendor.write({'email': final_email, 'phone': final_phone or vendor.phone})
                    self._post_message(
                        f"{AGENT_PERSONA}: ✅ وجدت بيانات {vendor_name}:\n"
                        f"• الإيميل: **{final_email}**\n"
                        f"• الهاتف: **{final_phone or 'غير متوفر'}**\n"
                        f"جاري إنشاء الطلب...",
                        mail_message_id
                    )
                    # ✅ أكمل تلقائياً بدون سؤال
                else:
                    self._post_message(
                        f"{AGENT_PERSONA}: ⚠️ لم أتمكن من إيجاد إيميل لـ **{vendor_name}**.\n"
                        f"يرجى إرسال الإيميل مباشرة: 'إيميل {vendor_name} هو info@example.com ثم أعد الطلب'",
                        mail_message_id
                    )
                    return {}
            except Exception as _e:
                _logger.exception("KH_AI: web search for vendor email failed")
                self._post_message(
                    f"{AGENT_PERSONA}: ⚠️ المورد **{vendor_name}** ليس لديه إيميل.\n"
                    f"يرجى إضافة الإيميل للمورد في النظام أولاً.",
                    mail_message_id
                )
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

        msg = args.get('message_to_user', f"تم إنشاء RFQ: {new_rfq.name}")
        self._post_message(f"{AGENT_PERSONA}: ✅ {msg}", mail_message_id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': new_rfq.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── ANALYTICS ────────────────────────────────────────────────
    def _tool_analytics(self, args, mail_message_id):
        """تحليلات مالية وتجارية مباشرة من Odoo ORM"""
        env       = request.env
        report    = args.get('report_type', '')
        date_from = args.get('date_from') or fields.Date.today().replace(month=1, day=1).strftime('%Y-%m-%d')
        date_to   = args.get('date_to')   or str(fields.Date.today())
        limit     = min(int(args.get('limit', 10)), 50)

        try:
            rows  = []
            title = report.replace('_', ' ').title()

            # ── 1. Profit Margin by Product Category ─────────────
            if report == 'profit_by_category':
                title = "هوامش الربح حسب فئة المنتج"
                # نجمع من سطور الفواتير المؤكدة
                env.cr.execute("""
                    SELECT
                        pc.complete_name                        AS category,
                        SUM(aml.quantity * aml.price_unit)      AS revenue,
                        SUM(aml.quantity * pp.standard_price)   AS cost,
                        SUM(aml.quantity * aml.price_unit)
                          - SUM(aml.quantity * pp.standard_price) AS profit
                    FROM account_move_line aml
                    JOIN account_move am      ON am.id  = aml.move_id
                    JOIN product_product pp   ON pp.id  = aml.product_id
                    JOIN product_template pt  ON pt.id  = pp.product_tmpl_id
                    JOIN product_category pc  ON pc.id  = pt.categ_id
                    WHERE am.move_type = 'out_invoice'
                      AND am.state     = 'posted'
                      AND am.invoice_date BETWEEN %s AND %s
                      AND aml.product_id IS NOT NULL
                      AND am.company_id = %s
                    GROUP BY pc.complete_name
                    ORDER BY profit DESC
                    LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                if not rows:
                    self._post_message(
                        f"{AGENT_PERSONA}: 📊 لا توجد بيانات فواتير مؤكدة في الفترة {date_from} → {date_to}",
                        mail_message_id
                    )
                    return {}

                lines = [
                    f"{AGENT_PERSONA}: 📊 **{title}**",
                    f"الفترة: {date_from} → {date_to}\n",
                    "| الفئة | الإيراد | التكلفة | الربح | هامش % |",
                    "|-------|---------|---------|-------|--------|",
                ]
                for r in rows:
                    rev    = float(r['revenue'] or 0)
                    cost   = float(r['cost']    or 0)
                    profit = float(r['profit']  or 0)
                    margin = round((profit / rev * 100), 1) if rev else 0
                    margin_icon = "🟢" if margin >= 20 else "🟡" if margin >= 10 else "🔴"
                    lines.append(
                        f"| {r['category']} | {rev:,.0f} | {cost:,.0f} | {profit:,.0f} | {margin_icon} {margin}% |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            # ── 2. Revenue by Partner (Top Customers) ─────────────
            elif report == 'revenue_by_partner':
                title = "الإيراد حسب العميل"
                env.cr.execute("""
                    SELECT
                        rp.name                                 AS partner,
                        COUNT(am.id)                            AS invoice_count,
                        SUM(am.amount_untaxed)                  AS revenue,
                        SUM(am.amount_tax)                      AS tax
                    FROM account_move am
                    JOIN res_partner rp ON rp.id = am.partner_id
                    WHERE am.move_type = 'out_invoice'
                      AND am.state     = 'posted'
                      AND am.invoice_date BETWEEN %s AND %s
                      AND am.company_id = %s
                    GROUP BY rp.name
                    ORDER BY revenue DESC
                    LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                lines = [
                    f"{AGENT_PERSONA}: 📊 **{title}**",
                    f"الفترة: {date_from} → {date_to}\n",
                    "| العميل | عدد الفواتير | الإيراد (بدون ضريبة) | الضريبة |",
                    "|--------|-------------|----------------------|---------|",
                ]
                for r in rows:
                    lines.append(
                        f"| {r['partner']} | {r['invoice_count']} | {float(r['revenue'] or 0):,.0f} | {float(r['tax'] or 0):,.0f} |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            # ── 3. Top Products by Revenue ─────────────────────────
            elif report == 'top_products':
                title = "أفضل المنتجات مبيعاً"
                env.cr.execute("""
                    SELECT
                        COALESCE(pt.name->>'en_US', pt.name->>'ar_001', pt.name::text) AS product,
                        SUM(aml.quantity)                       AS qty_sold,
                        SUM(aml.quantity * aml.price_unit)      AS revenue
                    FROM account_move_line aml
                    JOIN account_move am      ON am.id  = aml.move_id
                    JOIN product_product pp   ON pp.id  = aml.product_id
                    JOIN product_template pt  ON pt.id  = pp.product_tmpl_id
                    WHERE am.move_type = 'out_invoice'
                      AND am.state     = 'posted'
                      AND am.invoice_date BETWEEN %s AND %s
                      AND aml.product_id IS NOT NULL
                      AND am.company_id = %s
                    GROUP BY pt.name->>'en_US'
                    ORDER BY revenue DESC
                    LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                lines = [
                    f"{AGENT_PERSONA}: 📊 **{title}**",
                    f"الفترة: {date_from} → {date_to}\n",
                    "| # | المنتج | الكمية | الإيراد |",
                    "|---|--------|--------|---------|",
                ]
                for i, r in enumerate(rows, 1):
                    lines.append(
                        f"| {i} | {r['product']} | {float(r['qty_sold'] or 0):,.1f} | {float(r['revenue'] or 0):,.0f} |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            # ── 4. Expense Breakdown ───────────────────────────────
            elif report == 'expense_breakdown':
                title = "تحليل المصروفات"
                env.cr.execute("""
                    SELECT
                        COALESCE(aa.name->>'en_US', aa.name->>'ar_001', aa.name::text) AS account,
                        SUM(aml.debit - aml.credit)             AS amount
                    FROM account_move_line aml
                    JOIN account_account aa ON aa.id = aml.account_id
                    JOIN account_move am     ON am.id = aml.move_id
                    WHERE aa.account_type IN ('expense', 'expense_depreciation', 'expense_direct_cost')
                      AND am.state = 'posted'
                      AND am.date BETWEEN %s AND %s
                      AND am.company_id = %s
                    GROUP BY aa.name->>'en_US'
                    ORDER BY amount DESC
                    LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                total = sum(float(r['amount'] or 0) for r in rows)
                lines = [
                    f"{AGENT_PERSONA}: 📊 **{title}**",
                    f"الفترة: {date_from} → {date_to}\n",
                    "| الحساب | المبلغ | النسبة % |",
                    "|--------|--------|----------|",
                ]
                for r in rows:
                    amt  = float(r['amount'] or 0)
                    pct  = round(amt / total * 100, 1) if total else 0
                    lines.append(f"| {r['account']} | {amt:,.0f} | {pct}% |")
                lines.append(f"| **الإجمالي** | **{total:,.0f}** | **100%** |")
                self._post_message("\n".join(lines), mail_message_id)

            # ── 5. Invoice Summary ─────────────────────────────────
            elif report == 'invoice_summary':
                title = "ملخص الفواتير"
                env.cr.execute("""
                    SELECT
                        move_type,
                        state,
                        COUNT(*)            AS count,
                        SUM(amount_total)   AS total
                    FROM account_move
                    WHERE move_type IN ('out_invoice', 'in_invoice', 'out_refund', 'in_refund')
                      AND invoice_date BETWEEN %s AND %s
                      AND company_id = %s
                    GROUP BY move_type, state
                    ORDER BY move_type, state
                """, (date_from, date_to, env.company.id))
                rows = env.cr.dictfetchall()

                type_labels = {
                    'out_invoice': 'فاتورة عميل', 'in_invoice': 'فاتورة مورد',
                    'out_refund': 'إشعار دائن', 'in_refund': 'إشعار مدين',
                }
                state_labels = {'draft': 'مسودة', 'posted': 'مؤكدة', 'cancel': 'ملغاة'}
                lines = [
                    f"{AGENT_PERSONA}: 📊 **{title}**",
                    f"الفترة: {date_from} → {date_to}\n",
                    "| النوع | الحالة | العدد | الإجمالي |",
                    "|------|--------|-------|---------|",
                ]
                for r in rows:
                    lines.append(
                        f"| {type_labels.get(r['move_type'], r['move_type'])} "
                        f"| {state_labels.get(r['state'], r['state'])} "
                        f"| {r['count']} | {float(r['total'] or 0):,.0f} |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            # ── 6. Stock Valuation ─────────────────────────────────
            elif report == 'stock_valuation':
                title = "تقييم المخزون"
                products = env['product.product'].search_read(
                    [('type', 'in', ['product', 'consu']), ('qty_available', '>', 0)],
                    fields=['name', 'qty_available', 'standard_price', 'categ_id'],
                    limit=limit,
                    order='qty_available desc',
                )
                lines = [
                    f"{AGENT_PERSONA}: 📊 **{title}**\n",
                    "| المنتج | الكمية | سعر التكلفة | القيمة الإجمالية |",
                    "|--------|--------|-------------|-----------------|",
                ]
                total_val = 0
                for p in products:
                    qty  = float(p['qty_available'])
                    cost = float(p['standard_price'])
                    val  = qty * cost
                    total_val += val
                    cat  = p['categ_id'][1] if p.get('categ_id') else '-'
                    lines.append(f"| {p['name']} ({cat}) | {qty:,.1f} | {cost:,.2f} | {val:,.0f} |")
                lines.append(f"| **إجمالي المخزون** | — | — | **{total_val:,.0f}** |")
                self._post_message("\n".join(lines), mail_message_id)

            # ── 7. Sales Pipeline ──────────────────────────────────
            elif report == 'sales_pipeline':
                title = "خط أنابيب المبيعات (CRM)"
                env.cr.execute("""
                    SELECT
                        cs.name                                 AS stage,
                        COUNT(cl.id)                            AS count,
                        SUM(cl.expected_revenue)                AS expected,
                        AVG(cl.probability)                     AS avg_prob
                    FROM crm_lead cl
                    JOIN crm_stage cs ON cs.id = cl.stage_id
                    WHERE cl.type = 'opportunity'
                      AND cl.active = true
                      AND cl.company_id = %s
                    GROUP BY cs.name, cs.sequence
                    ORDER BY cs.sequence
                """, (env.company.id,))
                rows = env.cr.dictfetchall()

                lines = [
                    f"{AGENT_PERSONA}: 📊 **{title}**\n",
                    "| المرحلة | العدد | الإيراد المتوقع | احتمالية الإغلاق |",
                    "|---------|-------|----------------|-----------------|",
                ]
                for r in rows:
                    prob = round(float(r['avg_prob'] or 0), 0)
                    prob_icon = "🟢" if prob >= 70 else "🟡" if prob >= 40 else "🔴"
                    lines.append(
                        f"| {r['stage']} | {r['count']} "
                        f"| {float(r['expected'] or 0):,.0f} "
                        f"| {prob_icon} {prob}% |"
                    )
                self._post_message("\n".join(lines), mail_message_id)


            # ── 8. Project Cost Analysis ──────────────────────────
            elif report == 'project_cost':
                title = "تكاليف المشاريع"
                # Detect analytic link: try task-based first (Odoo 17+), then analytic account
                # Odoo 17+: project names stored as JSONB translated fields
                # Filter only projects starting with 'PROJECT:' per business convention
                env.cr.execute("""
                    SELECT
                        COALESCE(
                            pp.name->>'en_US',
                            pp.name->>'ar_001',
                            pp.name::text
                        )                                           AS project,
                        SUM(aal.amount)                             AS total_cost,
                        SUM(aal.unit_amount)                        AS total_hours,
                        COUNT(DISTINCT aal.employee_id)             AS team_size
                    FROM account_analytic_line aal
                    JOIN project_task pt2   ON pt2.id  = aal.task_id
                    JOIN project_project pp ON pp.id   = pt2.project_id
                    WHERE aal.date BETWEEN %s AND %s
                      AND pp.company_id = %s
                      AND aal.task_id IS NOT NULL
                    GROUP BY pp.name
                    ORDER BY total_cost DESC
                    LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                # Fallback: direct project_id on analytic line
                if not rows:
                    env.cr.execute("""
                        SELECT
                            COALESCE(
                                pp.name->>'en_US',
                                pp.name->>'ar_001',
                                pp.name::text
                            )                                       AS project,
                            SUM(aal.amount)                         AS total_cost,
                            SUM(aal.unit_amount)                    AS total_hours,
                            COUNT(DISTINCT aal.employee_id)         AS team_size
                        FROM account_analytic_line aal
                        JOIN project_project pp ON pp.id = aal.project_id
                        WHERE aal.date BETWEEN %s AND %s
                          AND pp.company_id = %s
                          AND aal.project_id IS NOT NULL
                        GROUP BY pp.name
                        ORDER BY total_cost DESC
                        LIMIT %s
                    """, (date_from, date_to, env.company.id, limit))
                    rows = env.cr.dictfetchall()

                # Fallback 2: no analytic data — read projects directly filtered by name prefix
                if not rows:
                    projects_orm = env['project.project'].search_read(
                        [('company_id', '=', env.company.id)],
                        fields=['name', 'allocated_hours'],
                        limit=limit,
                    )
                    # Filter to PROJECT: prefix
                    projects_orm = [p for p in projects_orm if str(p['name']).lower().startswith('project:')]
                    rows = [{'project': p['name'], 'total_cost': 0, 'total_hours': p.get('allocated_hours') or 0, 'team_size': 0} for p in projects_orm]

                if not rows:
                    # Fallback: try without analytic account link
                    projects = env['project.project'].search_read(
                        [('company_id', '=', env.company.id)],
                        fields=['name', 'allocated_hours', 'date_start', 'date'],
                        limit=limit,
                    )
                    lines = [
                        f"{AGENT_PERSONA}: 📊 **{title}** (لا توجد بيانات تحليلية مرتبطة)\n",
                        "| المشروع | ساعات مخصصة | تاريخ البدء | تاريخ الانتهاء |",
                        "|---------|------------|------------|----------------|",
                    ]
                    for p in projects:
                        lines.append(
                            f"| {p['name']} "
                            f"| {p.get('allocated_hours') or 0:,.0f} "
                            f"| {p.get('date_start') or '-'} "
                            f"| {p.get('date') or '-'} |"
                        )
                    self._post_message("\n".join(lines), mail_message_id)
                else:
                    def _clean_name(val):
                        """Clean JSONB name artifacts like {'en_US': 'X'}"""
                        import json as _json
                        if isinstance(val, dict):
                            return val.get('en_US') or val.get('ar_001') or next(iter(val.values()), str(val))
                        s = str(val)
                        if s.startswith('{') and ':' in s:
                            try:
                                d = _json.loads(s.replace("'", '"'))
                                return d.get('en_US') or next(iter(d.values()), s)
                            except Exception:
                                pass
                        return s

                    # Only show Project: prefixed projects (case-insensitive)
                    rows = [r for r in rows if _clean_name(r['project']).lower().startswith('project:')]

                    if not rows:
                        self._post_message(
                            f"{AGENT_PERSONA}: 🔍 لم أجد مشاريع تبدأ بـ 'Project:' أو لا توجد بيانات تحليلية مرتبطة بها.",
                            mail_message_id
                        )
                        return {}

                    lines = [
                        f"{AGENT_PERSONA}: 📊 **{title}**",
                        f"الفترة: {date_from} → {date_to}\n",
                        "| # | المشروع | التكلفة الإجمالية | الساعات | حجم الفريق |",
                        "|---|---------|-----------------|---------|-----------|",
                    ]
                    for i, r in enumerate(rows, 1):
                        cost  = float(r['total_cost']  or 0)
                        hours = float(r['total_hours'] or 0)
                        team  = int(r['team_size']     or 0)
                        name  = _clean_name(r['project'])
                        lines.append(f"| {i} | {name} | {cost:,.0f} | {hours:,.1f} h | {team} |")
                    self._post_message("\n".join(lines), mail_message_id)

            # ── 9. Timesheet Hours by Project/Employee ─────────────
            elif report == 'timesheet_hours':
                title = "ساعات العمل (Timesheets)"
                env.cr.execute("""
                    SELECT
                        pp.name                         AS project,
                        he.name                         AS employee,
                        SUM(aal.unit_amount)            AS hours
                    FROM account_analytic_line aal
                    JOIN project_task pt2  ON pt2.id  = aal.task_id
                    JOIN project_project pp ON pp.id  = pt2.project_id
                    LEFT JOIN hr_employee he ON he.id = aal.employee_id
                    WHERE aal.date BETWEEN %s AND %s
                      AND pp.company_id = %s
                      AND aal.task_id IS NOT NULL
                    GROUP BY pp.name, he.name
                    ORDER BY hours DESC
                    LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                lines = [
                    f"{AGENT_PERSONA}: 📊 **{title}**",
                    f"الفترة: {date_from} → {date_to}\n",
                    "| المشروع | الموظف | الساعات |",
                    "|---------|--------|---------|",
                ]
                for r in rows:
                    lines.append(
                        f"| {r['project']} | {r['employee'] or 'غير محدد'} | {float(r['hours'] or 0):,.1f} h |"
                    )
                self._post_message("\n".join(lines), mail_message_id)


            # ── 10. Project Financial Status ─────────────────────────────────
            elif report == 'project_financial':
                project_keyword = (args.get('project_name') or '').strip()

                if not project_keyword:
                    self._post_message(
                        f"{AGENT_PERSONA}: ⚠️ يرجى تحديد اسم المشروع أو رقمه.",
                        mail_message_id
                    )
                    return {}

                # جيب كل المشاريع بدون أي filter — ثم طابق بـ Python
                _all = env['project.project'].sudo().search_read(
                    [], fields=['id', 'name', 'partner_id', 'date_start', 'date'], limit=500
                )

                from difflib import SequenceMatcher as _SM
                import re as _re

                _kw = project_keyword.lower()

                def _score(p):
                    _n = str(p.get('name') or '').lower()
                    _pa = str(p['partner_id'][1] if p.get('partner_id') else '').lower()
                    _full = _n + ' ' + _pa
                    # نقاط الكلمات
                    _hits = sum(1 for w in _kw.split() if len(w) > 1 and w in _full)
                    # بونس الرقم
                    _num = _re.search(r'\d{4,5}', _kw)
                    _nb  = 10 if _num and _num.group() in _n else 0
                    # fuzzy
                    _fz  = _SM(None, _kw, _n).ratio()
                    return _hits * 3 + _nb + _fz

                _ranked = sorted(_all, key=_score, reverse=True)
                _best   = _ranked[0] if _ranked else None
                _best_score = _score(_best) if _best else 0

                _logger.info(f"KH_AI project_financial: kw='{project_keyword}' best='{_best['name'] if _best else None}' score={_best_score:.2f}")

                if not _best or _best_score < 0.5:
                    self._post_message(
                        f"{AGENT_PERSONA}: 🔍 لم أجد مشروعاً يطابق '{project_keyword}'.",
                        mail_message_id
                    )
                    return {}

                projects = [_best]

                report_lines = [f"{AGENT_PERSONA}: 📊 **الوضع المالي للمشروع**\n"]
                for proj in projects:
                    partner    = proj['partner_id'][1] if proj.get('partner_id') else 'غير محدد'
                    partner_id = proj['partner_id'][0] if proj.get('partner_id') else None

                    # ── البحث عن كل partners المطابقة باسم العميل ──────────────
                    # المشكلة: المشروع partner_id = "Ahmad Matar AlDhaheri"
                    # بس الفواتير باسم = "Client : Ahmed Matar Ahmed Al Dhaheri"
                    # الحل: نبحث بأطول كلمة مميزة من الاسم في كل الـ partners

                    import re as _re2

                    # استخرج اسم العائلة (أطول كلمة إنجليزية > 5 أحرف)
                    _proj_name_full = str(proj.get('name') or '')
                    _partner_name   = str(proj['partner_id'][1] if proj.get('partner_id') else '')
                    _combined_name  = _proj_name_full + ' ' + _partner_name

                    _skip = {'project', 'client', 'matar', 'ahmed', 'ahmad', 'saeed',
                             'salem', 'ali', 'omar', 'rashed', 'abdulla', 'khaled',
                             'mohamed', 'mohammed', 'opportunity'}
                    _eng_words = [w for w in _re2.findall(r'[A-Za-z]{5,}', _combined_name)
                                  if w.lower() not in _skip]
                    _family_name = max(_eng_words, key=len) if _eng_words else ''

                    # جيب كل partners تحتوي على اسم العائلة
                    all_partner_ids = []
                    if partner_id:
                        all_partner_ids.append(partner_id)

                    if _family_name:
                        # جرب الاسم كامل + بدون Al prefix (Aldhaheri → Dhaheri)
                        _search_variants = [_family_name]
                        if _family_name.lower().startswith('al') and len(_family_name) > 4:
                            _search_variants.append(_family_name[2:])  # Aldhaheri → dhaheri

                        _seen_ids = set(all_partner_ids)
                        for _variant in _search_variants:
                            _similar = env['res.partner'].sudo().search_read(
                                [('name', 'ilike', _variant)],
                                fields=['id', 'name'], limit=20
                            )
                            for p in _similar:
                                if p['id'] not in _seen_ids:
                                    all_partner_ids.append(p['id'])
                                    _seen_ids.add(p['id'])
                        _logger.info(f"KH_AI: family='{_family_name}' variants={_search_variants} → {len(all_partner_ids)} partners total")

                    all_partner_ids = list(set(all_partner_ids))

                    # ── فواتير العملاء ──────────────────────────────────────────
                    total_invoiced = total_paid = total_due = 0.0
                    inv_count = 0
                    if all_partner_ids:
                        inv = env['account.move'].read_group(
                            [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                             ('partner_id', 'in', all_partner_ids),
                             ('company_id', '=', env.company.id)],
                            fields=['amount_total:sum', 'amount_residual:sum', 'id:count'],
                            groupby=[],
                        )
                        if inv:
                            total_invoiced = float(inv[0].get('amount_total') or 0)
                            total_due      = float(inv[0].get('amount_residual') or 0)
                            total_paid     = total_invoiced - total_due
                            inv_count      = int(inv[0].get('id') or 0)

                    # ── فواتير الموردين ─────────────────────────────────────────
                    total_bills = bill_due = 0.0
                    bill_count  = 0
                    if all_partner_ids:
                        bills = env['account.move'].read_group(
                            [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                             ('partner_id', 'in', all_partner_ids),
                             ('company_id', '=', env.company.id)],
                            fields=['amount_total:sum', 'amount_residual:sum', 'id:count'],
                            groupby=[],
                        )
                        if bills:
                            total_bills = float(bills[0].get('amount_total') or 0)
                            bill_due    = float(bills[0].get('amount_residual') or 0)
                            bill_count  = int(bills[0].get('id') or 0)

                    # ── حسابات تحليلية ─────────────────────────────────────────
                    analytic_lines = env['account.analytic.line'].search_read(
                        [('project_id', '=', proj['id']), ('amount', '<', 0)],
                        fields=['amount'],
                    )
                    analytic_cost = abs(sum(float(l['amount']) for l in analytic_lines))

                    total_cost  = total_bills + analytic_cost
                    profit      = total_invoiced - total_cost
                    margin_pct  = round(profit / total_invoiced * 100, 1) if total_invoiced else 0
                    margin_icon = '🟢' if margin_pct >= 30 else '🟡' if margin_pct >= 10 else '🔴'

                    report_lines += [
                        f"**{proj['name']}**",
                        f"👤 العميل: {partner}",
                        f"📅 الفترة: {proj.get('date_start') or '-'} → {proj.get('date') or '-'}",
                        "",
                        f"📤 **فواتير العميل ({inv_count}):**",
                        f"  • إجمالي:      **{total_invoiced:,.2f}**",
                        f"  • مدفوع:       **{total_paid:,.2f}**",
                        f"  • متبقي (دين): **{total_due:,.2f}**",
                        "",
                        f"📥 **مصاريف ({bill_count} فاتورة مورد + حسابات تحليلية):**",
                        f"  • فواتير موردين: **{total_bills:,.2f}**",
                        f"  • حسابات تحليلية: **{analytic_cost:,.2f}**",
                        "",
                        f"**📊 النتيجة:**",
                        f"  • صافي الربح: **{profit:,.2f}** {margin_icon} ({margin_pct}%)",
                        "─" * 45,
                    ]
                self._post_message("\n".join(report_lines), mail_message_id)


            else:
                available = [
                    'profit_by_category', 'revenue_by_partner', 'top_products',
                    'expense_breakdown', 'invoice_summary', 'stock_valuation',
                    'sales_pipeline', 'project_cost', 'project_financial', 'timesheet_hours'
                ]
                self._post_message(
                    f"{AGENT_PERSONA}: ⚠️ نوع التقرير '{report}' غير معروف.\n"
                    f"الأنواع المتاحة: {', '.join(available)}",
                    mail_message_id
                )

        except Exception as e:
            _logger.exception("KH_AI: analytics error")
            try:
                env.cr.rollback()  # CRITICAL: reset aborted transaction
            except Exception:
                pass
            self._post_message(
                f"{AGENT_PERSONA}: ⛔ خطأ في التحليل:\n{e}",
                mail_message_id
            )

        return {}

    # ── ASK USER ─────────────────────────────────────────────────
    def _tool_ask_user(self, args, mail_message_id):
        """عرض خيارات للمستخدم بدل رفض الطلب"""
        question = args.get('question', '')
        options  = args.get('options', [])
        context  = args.get('context', '')

        lines = [f"{AGENT_PERSONA}: 🤔"]
        if context:
            lines.append(f"_{context}_\n")
        lines.append(f"**{question}**\n")
        for i, opt in enumerate(options, 1):
            lines.append(f"{i}️⃣ {opt}")

        self._post_message("\n".join(lines), mail_message_id)
        return {}