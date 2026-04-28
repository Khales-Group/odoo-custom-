# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║           KHALES AI - HYBRID AGENT ENGINE v2.4                   ║
║           Odoo 19 | Gemini 2.5 Flash | UAE Edition 🇦🇪           ║
║                                                                   ║
║  Changes v2.4 (hotfix):                                          ║
║  ✅ Removed invalid taxes_id / supplier_taxes_id field writes    ║
║     (field names vary by Odoo version — rely on sudo instead)    ║
║  ✅ PO create: pure sudo + user_id reassignment for audit        ║
║                                                                   ║
║  Changes v2.3:                                                   ║
║  ✅ Robust response text extraction (handles grounding quirks)   ║
║  ✅ Graceful fallback on empty Gemini responses                  ║
║  ✅ Stronger classifier for 'uae suppliers' → WEB_SEARCH         ║
║                                                                   ║
║  Changes v2.2:                                                   ║
║  ✅ RFQ lines: bypass account.tax Record Rules via targeted sudo ║
║  ✅ Preserve user_id on RFQ for audit trail                      ║
║                                                                   ║
║  Changes v2.1:                                                   ║
║  ✅ Language Lock: dynamic system instruction per user language  ║
║  ✅ UAE Context: country + AED currency + UAE supplier priority  ║
╚══════════════════════════════════════════════════════════════════╝
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

from odoo.addons.ai.controllers.main import AIController

_logger = logging.getLogger(__name__)

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
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════

# 🇦🇪 UAE BUSINESS CONTEXT
COUNTRY_EN = "United Arab Emirates (UAE)"
COUNTRY_AR = "الإمارات العربية المتحدة"
CURRENCY = "AED"
CURRENCY_AR = "درهم"
PHONE_PREFIX = "+971"
UAE_EMIRATES = ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Fujairah", "Ras Al Khaimah", "Umm Al Quwain"]

AGENT_PERSONA = "🤖 [Khales AI]"

READABLE_MODELS = {
    'res.partner':            ['name', 'email', 'phone', 'vat', 'is_company', 'street', 'city', 'country_id'],
    'crm.lead':               ['name', 'partner_name', 'email_from', 'phone', 'stage_id', 'description'],
    'account.move':           ['name', 'partner_id', 'amount_total', 'state', 'move_type', 'invoice_date'],
    'purchase.order':         ['name', 'partner_id', 'amount_total', 'state', 'date_order'],
    'purchase.order.line':    ['name', 'order_id', 'partner_id', 'product_id', 'price_unit', 'product_qty', 'date_approve'],
    'sale.order':             ['name', 'partner_id', 'amount_total', 'state', 'date_order'],
    'project.task':           ['name', 'project_id', 'user_ids', 'stage_id', 'date_deadline'],
    'hr.employee':            ['name', 'job_title', 'department_id', 'work_email'],
    'product.product':        ['name', 'list_price', 'qty_available', 'categ_id'],
    'stock.picking':          ['name', 'partner_id', 'state', 'scheduled_date', 'picking_type_id'],
    'account.bank.statement':      ['name', 'date', 'balance_start', 'balance_end_real', 'journal_id'],
    'account.bank.statement.line': ['payment_ref', 'amount', 'partner_id', 'date', 'journal_id', 'statement_id', 'move_id'],
}

# Fields to use for keyword search per model (defaults to 'name')
KEYWORD_FIELDS = {
    'account.bank.statement.line': ['payment_ref', 'partner_id.name'],
    'account.bank.statement':      ['name'],
}


# ══════════════════════════════════════════════════════════════════
#  ROBUST PARTNER / BANK-LINE MATCHING (v2.5)
# ══════════════════════════════════════════════════════════════════

_PARTNER_NOISE = {
    'the', 'and', 'company', 'co', 'corp', 'corporation', 'ltd', 'llc',
    'inc', 'pjsc', 'pjs', 'pjsclu', 'group', 'holding', 'holdings',
    'international', 'general', 'trading', 'establishment', 'est',
    'in', 'of', 'for', 'a', 'an',
}


def _partner_keyword_variants(keyword: str) -> list:
    keyword = (keyword or '').strip()
    if not keyword:
        return []
    variants = [keyword]
    no_dots = re.sub(r'[.,]', '', keyword)
    no_dots = re.sub(r'\s+', ' ', no_dots).strip()
    if no_dots and no_dots not in variants:
        variants.append(no_dots)
    words = [w for w in re.findall(r'\w+', no_dots)
             if w.lower() not in _PARTNER_NOISE and len(w) > 2]
    if len(words) >= 3:
        v = ' '.join(words[:3])
        if v not in variants:
            variants.append(v)
    if len(words) >= 2:
        v = ' '.join(words[:2])
        if v not in variants:
            variants.append(v)
    return variants


def _find_partners_robust(env, keyword: str, limit: int = 50):
    Partner = env['res.partner'].sudo()
    if not keyword:
        return Partner.browse()
    for variant in _partner_keyword_variants(keyword):
        hits = Partner.search([('name', '=ilike', variant)], limit=limit)
        if hits:
            return hits
        hits = Partner.search([('name', 'ilike', variant)], limit=limit)
        if hits:
            return hits
    return Partner.browse()


def _find_bank_lines_for_partner(env, keyword: str):
    StLine = env['account.bank.statement.line'].sudo()
    AmlObj = env['account.move.line'].sudo()

    partners = _find_partners_robust(env, keyword)
    variants = _partner_keyword_variants(keyword)

    or_clauses = []
    if partners:
        or_clauses.append(('partner_id', 'in', partners.ids))
    for v in variants:
        or_clauses.append(('payment_ref', 'ilike', v))

    if not or_clauses:
        return StLine.browse(), partners

    domain = ['|'] * (len(or_clauses) - 1) + or_clauses
    lines = StLine.search(domain)

    if partners:
        amls = AmlObj.search([
            ('partner_id', 'in', partners.ids),
            ('move_id.statement_line_id', '!=', False),
        ])
        if amls:
            move_ids = amls.mapped('move_id').ids
            lines |= StLine.search([('move_id', 'in', move_ids)])

    return lines, partners


# ══════════════════════════════════════════════════════════════════
#  LANGUAGE DETECTION (IMPROVED — v2.1)
# ══════════════════════════════════════════════════════════════════

def _detect_lang(text: str) -> str:
    """
    Detect language with STRONG priority on the LAST user message.
    
    v2.1 fix: the previous version fell back to overall majority too easily,
    causing language flip-flops when users mixed Arabic/English across turns.
    Now we lock onto the last real message unless it's empty/numeric.
    """
    lines = text.splitlines()
    user_lines = [l[5:].strip() for l in lines if l.startswith('User:')]

    if not user_lines:
        return 'en'

    # 1. Try the last message first
    for msg in reversed(user_lines):
        # Skip messages that are just numbers/symbols (option selections)
        stripped = re.sub(r'[\d\s\.,\-]+', '', msg)
        if len(stripped) < 2:
            continue

        arabic_chars = sum(1 for c in msg if '\u0600' <= c <= '\u06FF')
        latin_chars = sum(1 for c in msg if c.isascii() and c.isalpha())

        # Clear signal: whichever script dominates wins
        if arabic_chars + latin_chars >= 2:
            return 'ar' if arabic_chars > latin_chars else 'en'

    # 2. Fallback: aggregate all user text
    all_user = ' '.join(user_lines)
    arabic_chars = sum(1 for c in all_user if '\u0600' <= c <= '\u06FF')
    latin_chars = sum(1 for c in all_user if c.isascii() and c.isalpha())
    return 'ar' if arabic_chars > latin_chars else 'en'


def _fmt_money(amount: float, lang: str = 'en') -> str:
    """Format amount with AED currency — UAE convention."""
    try:
        amt = float(amount or 0)
    except (TypeError, ValueError):
        return f"0.00 {CURRENCY}"
    if lang == 'ar':
        return f"{amt:,.2f} {CURRENCY_AR}"
    return f"{CURRENCY} {amt:,.2f}"


# ── Translation helper ────────────────────────────────────────────
def _t(key: str, lang: str) -> str:
    translations = {
        'client':          {'ar': '👤 العميل',           'en': '👤 Client'},
        'period':          {'ar': '📅 الفترة',            'en': '📅 Period'},
        'invoices':        {'ar': '📤 **فواتير العميل',   'en': '📤 **Customer Invoices'},
        'total':           {'ar': 'إجمالي',               'en': 'Total'},
        'paid':            {'ar': 'مدفوع',                'en': 'Paid'},
        'due':             {'ar': 'متبقي (دين)',           'en': 'Outstanding (Due)'},
        'expenses':        {'ar': '📥 **المصاريف',        'en': '📥 **Expenses'},
        'vendor_bills':    {'ar': 'فواتير موردين',         'en': 'Vendor Bills'},
        'analytic':        {'ar': 'حسابات تحليلية',       'en': 'Analytic Costs'},
        'result':          {'ar': '**📊 النتيجة:**',      'en': '**📊 Result:**'},
        'net_profit':      {'ar': 'صافي الربح',           'en': 'Net Profit'},
        'vendor_bill':     {'ar': 'فاتورة مورد',          'en': 'vendor bill'},
        'found':           {'ar': 'وجدت',                 'en': 'Found'},
        'not_found':       {'ar': 'لم أجد نتائج',          'en': 'No records found'},
        'financial_status':{'ar': 'الوضع المالي للمشروع', 'en': 'Project Financial Status'},
        'searching':       {'ar': '🔎 جاري البحث...',     'en': '🔎 Searching...'},
        'searching_web':   {'ar': '🌐 جاري البحث عبر الإنترنت عن موردين في الإمارات...', 'en': '🌐 Searching online for UAE suppliers...'},
        'creating':        {'ar': '⚙️ جاري إنشاء السجل...', 'en': '⚙️ Creating record...'},
        'updated':         {'ar': 'تم التحديث',           'en': 'Updated'},
        'error':           {'ar': 'خطأ',                  'en': 'Error'},
        'no_permission':   {'ar': 'ليس لديك صلاحية',      'en': 'Permission denied'},
        'records':         {'ar': 'سجل',                  'en': 'record(s)'},
        'project_cost':    {'ar': 'تكاليف المشاريع',      'en': 'Project Costs'},
        'top_products':    {'ar': 'أفضل المنتجات مبيعاً', 'en': 'Top Products'},
        'revenue':         {'ar': 'الإيراد',              'en': 'Revenue'},
        'cost':            {'ar': 'التكلفة',              'en': 'Cost'},
        'profit_margins':  {'ar': 'هوامش الربح',          'en': 'Profit Margins'},
        'category':        {'ar': 'الفئة',                'en': 'Category'},
        'margin':          {'ar': 'هامش %',               'en': 'Margin %'},
        'hours':           {'ar': 'الساعات',              'en': 'Hours'},
        'team_size':       {'ar': 'حجم الفريق',           'en': 'Team Size'},
        'period_label':    {'ar': 'الفترة',               'en': 'Period'},
        'invoice_vendor':  {'ar': 'فاتورة مورد',          'en': 'vendor bill'},
        'partner':         {'ar': 'الشريك',               'en': 'Partner'},
        'account':         {'ar': 'الحساب',               'en': 'Account'},
        'lines_updated':   {'ar': 'البنود المحدّثة',      'en': 'Lines Updated'},
        'vendor':          {'ar': 'المورد',               'en': 'Vendor'},
        'email':           {'ar': 'الإيميل',              'en': 'Email'},
        'phone':           {'ar': 'الهاتف',               'en': 'Phone'},
        'not_available':   {'ar': 'غير متوفر',            'en': 'Not available'},
        'done':            {'ar': 'تم بنجاح',             'en': 'Done'},
    }
    t = translations.get(key, {})
    return t.get(lang, t.get('en', key))


# ══════════════════════════════════════════════════════════════════
#  SYSTEM INSTRUCTION — DYNAMIC PER LANGUAGE (v2.1)
# ══════════════════════════════════════════════════════════════════

_BASE_SYSTEM_INSTRUCTION = f"""You are '{AGENT_PERSONA}', an elite ERP assistant and business consultant built into Odoo 19.

## IDENTITY
- Start EVERY reply with "{AGENT_PERSONA}: "
- Be concise, professional, and warm.
- You work for a company based in the **United Arab Emirates (UAE 🇦🇪)**.

## 🇦🇪 UAE BUSINESS CONTEXT (ALWAYS APPLY)
- **Country**: United Arab Emirates — الإمارات العربية المتحدة
- **Currency**: {CURRENCY} (UAE Dirham / درهم إماراتي) — format amounts as "AED 1,500.00" or "1,500.00 درهم"
- **Phone format**: {PHONE_PREFIX} XX XXX XXXX
- **VAT field** in Odoo = TRN (Tax Registration Number in UAE)
- **Emirates**: {', '.join(UAE_EMIRATES)}
- When the user asks about **suppliers, vendors, prices, or market info** outside the system:
  → ALWAYS prioritize UAE-based suppliers (Dubai, Abu Dhabi, Sharjah first).
  → Only include Saudi / Egyptian / Bahraini / other suppliers AFTER UAE options, and clearly label them as "(خارج الإمارات)" or "(outside UAE)".
  → When searching web for vendor contact info, add "UAE" or "Dubai" to the query.

## TOOL SELECTION

### READ (ai_dynamic_read):
Use for "find", "search", "show", "list", "ابحث", "دور", "اعرض", "كم عدد".
VENDOR SEARCH RULES:
- "موردين الألمنيوم" / "aluminum suppliers":
  → Call ai_dynamic_read TWICE:
    1. model='purchase.order.line', keyword='aluminum'
    2. model='purchase.order.line', keyword='ألمنيوم'
- "موردين" by company name → model='res.partner', keyword='...'

### ANALYTICS (ai_analytics):
- "profit margins by category"          → 'profit_by_category'
- "top selling products"                → 'top_products'
- "revenue by customer"                 → 'revenue_by_partner'
- "expense breakdown"                   → 'expense_breakdown'
- "invoice summary"                     → 'invoice_summary'
- "stock valuation"                     → 'stock_valuation'
- "sales pipeline"                      → 'sales_pipeline'
- "which project costs most"            → 'project_cost'
- "show financial status of project X"  → 'project_financial', project_name='X'
- "شو الوضع المالي تبعو/تبعها/عليه"   → SCAN HISTORY for name, 'project_financial'

CONTEXT RULE: The user often refers to a person/project mentioned EARLIER.
Trigger words: تبعو, تبعها, عليه, عنه, هذا المشروع, it, this project, yes this is it.
NEVER return empty project_name — scan history.

### WRITE (explicit commands only):
- ai_create_lead        → "أنشئ lead", "create lead"
- ai_create_invoice     → "أنشئ فاتورة", "create invoice/bill"
- ai_create_bank_stmt   → "أنشئ كشف بنكي", "bank statement"
- ai_create_rfq         → "أنشئ RFQ", "اطلب من مورد", "طلب تسعير"
- ai_update_records     → "set account X for all transactions of partner Y",
                          "categorize all <partner> bank lines as <account>",
                          "set account 6030 for Etisalat / Du / Emirates Telecom",
                          "حط الحساب 6030 لكل عمليات اتصالات",
                          "صنّف عمليات <مورد> على حساب <code>"
  → operation = 'set_bank_statement_account'
  → partner_name = the partner the user mentioned (PASS AS-IS, even long names)
  → account_code (preferred) OR account_name
  → Optional dry_run=true if the user asks to "preview" / "show me first" / "اعرضلي قبل ما تنفّذ"

CRITICAL: When the user combines a SEARCH ("find transactions for partner X")
followed by an ASSIGN ("set account 6030"), call ai_update_records DIRECTLY
with both partner_name and account_code in one shot — don't search first.
- ai_read_chatter       → "summarize project X", "what happened on task Y",
                          "show notes for project Z", "what's the status of X",
                          "لخّص مشروع X", "وش صار في مشروع Y", "ايش آخر أخبار المشروع"
  → model_name = 'project.project' (or 'project.task', 'sale.order', etc.)
  → record_name = the project/record name the user mentioned
  → Reads all chatter messages and returns an AI-written summary.
- ai_extract_references → "extract references", "fill reference column",
                          "set ref from label", "استخرج المراجع",
                          "املأ خانة المرجع من اللابل"
  → Pulls text after "|" in payment_ref and writes it to the ref field.
  → Optional statement_name filter (e.g. "KPM Statement 2022-12-31").

### RFQ Pattern:
If user asks to create/send RFQ → call ai_create_rfq DIRECTLY.
- Don't pre-search for vendor. The tool handles lookup + creation.
- Pass vendor_name as-is. Tool auto-searches UAE internet for email if missing.

### Google Search Grounding:
For external info — answer directly. ALWAYS add "UAE" / "Dubai" context to your search mentally.

## EXPERT BEHAVIOR — NEVER REFUSE
- Never say "I cannot". Offer options via ai_ask_user.
- Numbers (1, 2, 3) are CHOICES from prior options, not data.
- Always move forward.

## SAFETY
- Never invent financial data.
- Ask for clarification ONLY when genuinely ambiguous — offer options, not dead ends.
- When showing prices, ALWAYS include "AED" suffix.
"""


def _build_system_instruction(lang: str) -> str:
    """
    v2.1: inject an explicit LANGUAGE LOCK based on detected language.
    This is the critical fix — Gemini now has an unambiguous directive
    that overrides any dominant-language pull from the conversation history.
    """
    if lang == 'ar':
        lock = (
            "\n## 🔒 LANGUAGE LOCK — CRITICAL OVERRIDE\n"
            "The user's LATEST message is in **ARABIC**.\n"
            "You MUST reply ENTIRELY in Arabic (العربية الفصحى أو الإماراتي).\n"
            "All text, options, questions, status messages — Arabic only.\n"
            "Ignore any English in earlier messages when choosing your reply language.\n"
            "The ONLY exceptions are: product names, currency code 'AED', and technical identifiers.\n"
        )
    else:
        lock = (
            "\n## 🔒 LANGUAGE LOCK — CRITICAL OVERRIDE\n"
            "The user's LATEST message is in **ENGLISH**.\n"
            "You MUST reply ENTIRELY in English.\n"
            "All text, clarifying questions, numbered options, status updates — English only.\n"
            "Ignore any Arabic in earlier system messages or conversation history when choosing your reply language.\n"
            "Do NOT switch to Arabic mid-reply.\n"
        )
    return _BASE_SYSTEM_INSTRUCTION + lock


# ══════════════════════════════════════════════════════════════════
#  TOOL DEFINITIONS (unchanged interface)
# ══════════════════════════════════════════════════════════════════

def _build_tools() -> "types.Tool":

    ai_dynamic_read = types.FunctionDeclaration(
        name="ai_dynamic_read",
        description=(
            "Search/read any Odoo record dynamically. "
            "Use for find/search/list/show requests."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "model_name": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Odoo technical model name: 'res.partner', 'crm.lead', 'account.move', "
                        "'purchase.order', 'purchase.order.line', 'sale.order', 'project.task', "
                        "'hr.employee', 'product.product', 'stock.picking'"
                    )
                ),
                "keyword": types.Schema(type=types.Type.STRING, description="Text to search in 'name' field"),
                "filters": types.Schema(type=types.Type.STRING, description="Odoo domain as JSON string"),
                "limit": types.Schema(type=types.Type.INTEGER, description="Max records (default 10, max 50)"),
            },
            required=["model_name"]
        )
    )

    ai_create_lead = types.FunctionDeclaration(
        name="ai_create_lead",
        description="Create a CRM Lead/Opportunity. Only when explicitly commanded.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "name":            types.Schema(type=types.Type.STRING),
                "partner_name":    types.Schema(type=types.Type.STRING),
                "email_from":      types.Schema(type=types.Type.STRING),
                "phone":           types.Schema(type=types.Type.STRING, description="UAE format: +971 XX XXX XXXX"),
                "description":     types.Schema(type=types.Type.STRING),
                "expected_revenue":types.Schema(type=types.Type.NUMBER, description="Amount in AED"),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["name", "message_to_user"]
        )
    )

    ai_create_invoice = types.FunctionDeclaration(
        name="ai_create_invoice",
        description="Create customer invoice (out_invoice) or vendor bill (in_invoice). Amounts in AED.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "move_type":       types.Schema(type=types.Type.STRING, description="'out_invoice' or 'in_invoice'"),
                "partner_name":    types.Schema(type=types.Type.STRING),
                "partner_vat":     types.Schema(type=types.Type.STRING, description="UAE TRN (Tax Registration Number)"),
                "invoice_date":    types.Schema(type=types.Type.STRING, description="YYYY-MM-DD"),
                "lines": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "description": types.Schema(type=types.Type.STRING),
                            "quantity":    types.Schema(type=types.Type.NUMBER),
                            "price_unit":  types.Schema(type=types.Type.NUMBER, description="Unit price in AED"),
                        }
                    )
                ),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["move_type", "partner_name", "lines", "message_to_user"]
        )
    )

    ai_create_bank_stmt = types.FunctionDeclaration(
        name="ai_create_bank_stmt",
        description="Create accounting bank statement. All amounts in AED.",
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
                            "amount": types.Schema(type=types.Type.NUMBER, description="POSITIVE=credit, NEGATIVE=debit"),
                        }
                    )
                ),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["reference", "date", "starting_balance", "ending_balance", "lines", "message_to_user"]
        )
    )

    ai_create_rfq = types.FunctionDeclaration(
        name="ai_create_rfq",
        description=(
            "Create Request for Quotation (RFQ/Purchase Order) for a UAE-based or international vendor. "
            "Triggers: خلينا نجهز طلب تسعير, RFQ, send RFQ, create PO. "
            "Creates vendor automatically if missing. Auto-searches UAE internet for contact info."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "vendor_name":  types.Schema(type=types.Type.STRING),
                "vendor_email": types.Schema(type=types.Type.STRING),
                "vendor_phone": types.Schema(type=types.Type.STRING, description="UAE format preferred: +971..."),
                "notes":        types.Schema(type=types.Type.STRING),
                "products": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "name":     types.Schema(type=types.Type.STRING),
                            "quantity": types.Schema(type=types.Type.NUMBER),
                            "price":    types.Schema(type=types.Type.NUMBER, description="Unit price in AED (0 if unknown)"),
                        }
                    )
                ),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["vendor_name", "products", "message_to_user"]
        )
    )

    ai_analytics = types.FunctionDeclaration(
        name="ai_analytics",
        description="Financial/business analytics. All amounts displayed in AED.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "report_type": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "'profit_by_category', 'revenue_by_partner', 'project_cost', 'project_financial', "
                        "'timesheet_hours', 'top_products', 'expense_breakdown', 'invoice_summary', "
                        "'stock_valuation', 'sales_pipeline'"
                    )
                ),
                "date_from":    types.Schema(type=types.Type.STRING, description="YYYY-MM-DD"),
                "date_to":      types.Schema(type=types.Type.STRING, description="YYYY-MM-DD"),
                "limit":        types.Schema(type=types.Type.INTEGER),
                "project_name": types.Schema(type=types.Type.STRING, description="For project_financial — full name from history"),
            },
            required=["report_type"]
        )
    )

    ai_ask_user = types.FunctionDeclaration(
        name="ai_ask_user",
        description="Clarify HOW to help — present options or ask for missing info. NEVER use to refuse.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "question": types.Schema(type=types.Type.STRING),
                "options":  types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
                "context":  types.Schema(type=types.Type.STRING),
            },
            required=["question", "options"]
        )
    )

    ai_update_records = types.FunctionDeclaration(
        name="ai_update_records",
        description="Bulk update existing Odoo records (e.g., set account on bank statement lines).",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "operation":    types.Schema(type=types.Type.STRING,
                                description="'set_bank_statement_account' or 'set_invoice_account'"),
                "partner_name": types.Schema(type=types.Type.STRING),
                "account_code": types.Schema(type=types.Type.STRING),
                "account_name": types.Schema(type=types.Type.STRING),
                "dry_run":      types.Schema(type=types.Type.BOOLEAN,
                                description="If true, preview what would be updated without writing. Default false."),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["operation", "message_to_user"]
        )
    )

    ai_extract_references = types.FunctionDeclaration(
        name="ai_extract_references",
        description=(
            "Extract reference codes (ECS xxx, Cheque xxx, etc.) from bank statement line "
            "labels and write them to the 'ref' field. The reference is the text AFTER "
            "the '|' separator in the label. "
            "Triggers: 'extract references', 'fill reference column', 'set ref from label', "
            "'استخرج المراجع', 'املأ خانة المرجع', 'حدّث المرجع من اللابل'."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "statement_name": types.Schema(
                    type=types.Type.STRING,
                    description="Optional. Filter by bank statement name (e.g. 'KPM Statement 2022-12-31'). If omitted, processes all statements.",
                ),
                "overwrite": types.Schema(
                    type=types.Type.BOOLEAN,
                    description="If true, overwrite lines that already have a ref. Default false (only fill empty refs).",
                ),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["message_to_user"],
        ),
    )

    ai_read_chatter = types.FunctionDeclaration(
        name="ai_read_chatter",
        description=(
            "Read and summarize the chatter (messages, notes, emails) on an Odoo record. "
            "Use for: 'summarize project X', 'what happened on task Y', 'show me the notes for project Z', "
            "'لخّص مشروع X', 'وش صار في مشروع Y', 'ايش آخر أخبار المشروع'."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "model_name":   types.Schema(type=types.Type.STRING,
                                description="Odoo model, e.g. 'project.project', 'project.task', 'sale.order'"),
                "record_name":  types.Schema(type=types.Type.STRING,
                                description="Name or partial name of the record to look up"),
                "limit":        types.Schema(type=types.Type.INTEGER,
                                description="Max messages to fetch (default 40, max 100)"),
                "message_to_user": types.Schema(type=types.Type.STRING),
            },
            required=["model_name", "record_name", "message_to_user"]
        )
    )

    return types.Tool(function_declarations=[
        ai_dynamic_read, ai_create_lead, ai_create_invoice, ai_create_bank_stmt,
        ai_create_rfq, ai_analytics, ai_ask_user, ai_update_records,
        ai_extract_references, ai_read_chatter,
    ])


# ══════════════════════════════════════════════════════════════════
#  HTML FORMATTER
# ══════════════════════════════════════════════════════════════════

def _to_html(text: str) -> Markup:
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

    @http.route('/ai/generate_response', type='json', auth='user', csrf=False)
    def generate_response(self, **kwargs):
        _logger.info('KH_AI v2.4 → request received')

        if not HAS_GENAI:
            return {'error': 'google-genai not installed on server'}

        # 1. Parse Input
        prompt, mail_message_id, chat_history, attachments, lang = self._parse_input(kwargs)
        _logger.info(f"KH_AI v2.4: detected language = '{lang}'")

        # 2. Build Gemini contents
        gemini_contents = self._build_contents(chat_history, attachments)

        # 3. Call Gemini
        api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            msg = ("⛔ Gemini API key not configured." if lang == 'en'
                   else "⛔ لم يتم تكوين مفتاح Gemini API في إعدادات النظام.")
            self._post_message(msg, mail_message_id)
            return {}

        try:
            client = genai.Client(api_key=api_key)

            # ── Pass 1: Classify intent ───────────────────────────
            last_user_msg = ""
            for line in reversed(chat_history.splitlines()):
                if line.startswith("User:"):
                    last_user_msg = line[5:].strip()
                    break

            classifier_prompt = (
                "You are classifying a user message in a UAE-based ERP conversation.\n\n"
                "Categories:\n"
                "- ODOO_ACTION  -> create/update/delete/send records\n"
                "- ODOO_READ    -> search INTERNAL Odoo data (existing suppliers, invoices, reports)\n"
                "- WEB_SEARCH   -> external internet info (NEW suppliers, UAE market, online prices)\n"
                "- CHAT         -> pure greetings with NO business intent\n\n"
                "ODOO_ACTION keywords: انشئ, اعمل, جهز, ابعث, ارسل, أضف, خلينا نجهز, "
                "طلب تسعير, RFQ, فاتورة, lead, create, send\n"
                "ODOO_READ keywords: دور داخل النظام, اعرض الموجود, كم, شو وضع, تقرير, "
                "فواتير النظام, موردين النظام, عملاء النظام, find in system, show existing\n"
                "WEB_SEARCH triggers (ANY of these → WEB_SEARCH, do not second-guess):\n"
                "  • 'outside the system' / 'خارج النظام' / 'عبر الإنترنت' / 'online'\n"
                "  • 'search the internet' / 'search online' / 'ابحث على الإنترنت'\n"
                "  • 'UAE suppliers' / 'uae suppliers' / 'Dubai suppliers' / 'موردين الإمارات'\n"
                "  • 'other suppliers' / 'new suppliers' / 'موردين آخرين' / 'موردين جدد'\n"
                "  • 'find me a supplier' / 'recommend a vendor'\n"
                "  • any 'suppliers' request AFTER the assistant offered to search online\n\n"
                "CRITICAL: If the previous assistant message offered 'search for UAE suppliers online' "
                "and user replied with 'yes' / 'uae suppliers' / 'search' / 'ابحث' → WEB_SEARCH.\n"
                "IMPORTANT: pronouns (تبعو, تبعها, عليه, this, it) referring to earlier record → ODOO_READ\n\n"
                f"Conversation context:\n{chat_history[-800:]}\n\n"
                f"Latest user message: {last_user_msg}\n\n"
                "Reply with ONLY one word: ODOO_ACTION or ODOO_READ or WEB_SEARCH or CHAT"
            )

            classify_resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[classifier_prompt],
                config=types.GenerateContentConfig(temperature=0.0),
            )
            intent = (getattr(classify_resp, 'text', '') or '').strip().upper()
            _logger.info(f"KH_AI v2.4: intent='{intent}' | lang='{lang}'")

            # ── Pass 2: Execute with language-locked system prompt ──
            system_inst = _build_system_instruction(lang)

            if intent in ('ODOO_ACTION', 'ODOO_READ'):
                config = types.GenerateContentConfig(
                    system_instruction=system_inst,
                    temperature=0.3,
                    tools=[_build_tools()],
                )
            else:
                config = types.GenerateContentConfig(
                    system_instruction=system_inst,
                    temperature=0.4,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=gemini_contents,
                config=config,
            )

        except Exception as e:
            _logger.exception("KH_AI v2.4: Gemini API error")
            err = (f"⛔ Gemini connection error:\n{e}" if lang == 'en'
                   else f"⛔ خطأ في الاتصال بـ Gemini:\n{e}")
            self._post_message(err, mail_message_id)
            return {}

        # 4. Route response
        if response.function_calls:
            return self._handle_tool_call(response.function_calls[0], mail_message_id, lang)
        else:
            text = self._extract_response_text(response)
            if not text:
                # Log diagnostic info so we can see WHY the response was empty
                try:
                    cands = getattr(response, 'candidates', None) or []
                    fr = getattr(cands[0], 'finish_reason', None) if cands else None
                    sf = getattr(cands[0], 'safety_ratings', None) if cands else None
                    _logger.warning(
                        f"KH_AI v2.4: empty response. intent='{intent}' | "
                        f"finish_reason={fr} | safety={sf}"
                    )
                except Exception:
                    pass

                # Graceful fallback — don't show an empty bubble
                text = (
                    "I couldn't generate a response for that. "
                    "Could you try rephrasing with more specific keywords "
                    "(e.g. 'search online for UAE block suppliers in Dubai')?"
                    if lang == 'en'
                    else "لم أتمكن من توليد رد لهذا الطلب. "
                         "هل يمكنك إعادة الصياغة بكلمات أكثر تحديداً "
                         "(مثلاً: 'ابحث على الإنترنت عن موردين بلوك في دبي')؟"
                )
            if not text.startswith(AGENT_PERSONA):
                text = f"{AGENT_PERSONA}: {text}"
            self._post_message(text, mail_message_id)
            return {}

    # ─────────────────────────────────────────────────────────────
    # RESPONSE TEXT EXTRACTOR (v2.3)
    # ─────────────────────────────────────────────────────────────
    def _extract_response_text(self, response) -> str:
        """
        Robust text extraction from Gemini responses.

        With grounding (google_search) Gemini sometimes returns an empty
        `.text` even when `response.candidates[0].content.parts[*].text`
        contains the actual answer. Also covers multi-part responses.
        """
        # 1. Primary: the convenient .text accessor
        try:
            text = getattr(response, 'text', '') or ''
            if text and text.strip():
                return text.strip()
        except Exception:
            pass

        # 2. Fallback: walk candidates → content → parts
        try:
            for cand in (getattr(response, 'candidates', None) or []):
                content = getattr(cand, 'content', None)
                if content is None:
                    continue
                parts = getattr(content, 'parts', None) or []
                chunks = []
                for part in parts:
                    part_text = getattr(part, 'text', None)
                    if part_text:
                        chunks.append(part_text)
                if chunks:
                    return '\n'.join(chunks).strip()
        except Exception as _e:
            _logger.warning(f"KH_AI v2.4: fallback text extraction failed: {_e}")

        return ''

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

        lang = _detect_lang(chat_history)
        return prompt, mail_message_id, chat_history, attachments, lang

    # ─────────────────────────────────────────────────────────────
    # CONTENT BUILDER
    # ─────────────────────────────────────────────────────────────
    def _build_contents(self, chat_history: str, attachments) -> list:
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
            _logger.exception("KH_AI v2.4: failed to post message")

    # ─────────────────────────────────────────────────────────────
    # TOOL DISPATCHER
    # ─────────────────────────────────────────────────────────────
    def _handle_tool_call(self, func, mail_message_id, lang='ar'):
        name = func.name
        args = func.args
        _logger.info(f"KH_AI v2.4: tool={name} | lang={lang} | args={args}")

        try:
            if name == "ai_dynamic_read":
                return self._tool_dynamic_read(args, mail_message_id, lang)
            elif name == "ai_create_lead":
                return self._tool_create_lead(args, mail_message_id, lang)
            elif name == "ai_create_invoice":
                return self._tool_create_invoice(args, mail_message_id, lang)
            elif name == "ai_create_bank_stmt":
                return self._tool_create_bank_stmt(args, mail_message_id, lang)
            elif name == "ai_create_rfq":
                return self._tool_create_rfq(args, mail_message_id, lang)
            elif name == "ai_analytics":
                return self._tool_analytics(args, mail_message_id, lang)
            elif name == "ai_ask_user":
                return self._tool_ask_user(args, mail_message_id, lang)
            elif name == "ai_update_records":
                return self._tool_update_records(args, mail_message_id, lang)
            elif name == "ai_extract_references":
                return self._tool_extract_references(args, mail_message_id, lang)
            elif name == "ai_read_chatter":
                return self._tool_read_chatter(args, mail_message_id, lang)
            else:
                err = (f"⛔ Unknown tool: {name}" if lang == 'en'
                       else f"⛔ أداة غير معروفة: {name}")
                self._post_message(err, mail_message_id)
                return {}

        except AccessError:
            err = (f"{AGENT_PERSONA}: ⛔ Permission denied for this operation."
                   if lang == 'en'
                   else f"{AGENT_PERSONA}: ⛔ ليس لديك صلاحية لتنفيذ هذه العملية.")
            self._post_message(err, mail_message_id)
            return {}
        except UserError as e:
            self._post_message(f"{AGENT_PERSONA}: ⚠️ {e}", mail_message_id)
            return {}
        except Exception as e:
            _logger.exception(f"KH_AI v2.4: tool {name} failed")
            err = (f"{AGENT_PERSONA}: ⛔ Tool execution error:\n{e}" if lang == 'en'
                   else f"{AGENT_PERSONA}: ⛔ خطأ في تنفيذ الأداة:\n{e}")
            self._post_message(err, mail_message_id)
            return {}

    # ══════════════════════════════════════════════════════════════
    #  TOOL IMPLEMENTATIONS
    # ══════════════════════════════════════════════════════════════

    # ── READ (Dynamic) ────────────────────────────────────────────
    def _tool_dynamic_read(self, args, mail_message_id, lang='ar'):
        model_name = args.get('model_name', '').strip()
        keyword    = args.get('keyword', '').strip()
        filters    = args.get('filters', '').strip()
        limit      = min(int(args.get('limit', 10)), 50)

        if model_name not in READABLE_MODELS:
            err = (f"{AGENT_PERSONA}: ⛔ Search in '{model_name}' is not allowed."
                   if lang == 'en'
                   else f"{AGENT_PERSONA}: ⛔ البحث في '{model_name}' غير مسموح به.")
            self._post_message(err, mail_message_id)
            return {}

        allowed_fields = READABLE_MODELS[model_name]

        domain = []
        if keyword:
            kw_fields = KEYWORD_FIELDS.get(model_name, ['name'])
            if len(kw_fields) == 1:
                domain.append((kw_fields[0], 'ilike', keyword))
            else:
                # OR across multiple keyword fields
                or_clauses = ['|'] * (len(kw_fields) - 1)
                for f in kw_fields:
                    or_clauses.append((f, 'ilike', keyword))
                domain.extend(or_clauses)
        if filters:
            try:
                extra = json.loads(filters)
                domain.extend(extra)
            except json.JSONDecodeError:
                pass

        env = request.env

        # Special path: bank statement lines use the robust partner matcher
        if model_name == 'account.bank.statement.line' and keyword:
            bank_lines, matched_partners = _find_bank_lines_for_partner(env, keyword)
            if bank_lines:
                records = bank_lines[:limit].read(allowed_fields)
                if matched_partners:
                    pnames = ', '.join(matched_partners.mapped('name')[:3])
                    hint_header = (
                        f"{AGENT_PERSONA}: 🔍 Found **{len(bank_lines)}** bank line(s) "
                        f"for partner(s): _{pnames}_"
                        if lang == 'en'
                        else
                        f"{AGENT_PERSONA}: 🔍 وجدت **{len(bank_lines)}** بند بنكي "
                        f"للشريك: _{pnames}_"
                    )
                else:
                    hint_header = (
                        f"{AGENT_PERSONA}: 🔍 Found **{len(bank_lines)}** bank line(s) matching '{keyword}'"
                        if lang == 'en'
                        else f"{AGENT_PERSONA}: 🔍 وجدت **{len(bank_lines)}** بند بنكي يطابق '{keyword}'"
                    )
                body = [hint_header]
                for r in records:
                    partner_id = r.get('partner_id')
                    pname = partner_id[1] if isinstance(partner_id, (list, tuple)) and len(partner_id) == 2 else '—'
                    label = (r.get('payment_ref') or '')[:60]
                    amt   = float(r.get('amount') or 0)
                    body.append(f"- {r.get('date')} | {label} | _{pname}_ | **{_fmt_money(amt, lang)}**")
                cta = ("\n💬 Want me to set an account for all these? Tell me the account code or name."
                       if lang == 'en'
                       else "\n💬 تريد تعيين حساب لكل هذه البنود؟ أخبرني بكود أو اسم الحساب.")
                body.append(cta)
                self._post_message("\n".join(body), mail_message_id)
                return {}
            # fall through to standard search if helper also finds nothing

        records = env(su=True)[model_name].search_read(domain, fields=allowed_fields, limit=limit)

        if not records:
            no_results = (
                f"{AGENT_PERSONA}: 🔍 No records matching "
                + (f"'{keyword}' " if keyword else "")
                + f"found in {model_name}."
            ) if lang == 'en' else (
                f"{AGENT_PERSONA}: 🔍 {_t('not_found', lang)}"
                + (f" للكلمة '{keyword}'" if keyword else "")
                + f" في {model_name}."
            )
            if model_name == 'res.partner' and keyword:
                hint = ("\n💡 Try searching purchase order history for the product name."
                        if lang == 'en'
                        else "\n💡 جرب البحث في طلبات الشراء القديمة عن المنتج.")
                no_results += hint
            self._post_message(no_results, mail_message_id)
            return {}

        # Special formatting for purchase order lines (supplier catalog view)
        if model_name == 'purchase.order.line':
            if lang == 'en':
                header = f"{AGENT_PERSONA}: 🔍 Found **{len(records)}** purchase line(s) matching '{keyword}':\n"
            else:
                header = f"{AGENT_PERSONA}: 🔍 وجدت **{len(records)}** بند شراء يحتوي على '{keyword}':\n"
            reply_lines = [header]
            seen_vendors = {}
            for r in records:
                ptnr = r.get('partner_id')
                pname = ptnr[1] if isinstance(ptnr, (list, tuple)) and len(ptnr) == 2 else str(ptnr or '-')
                prod = r.get('product_id')
                prodname = prod[1] if isinstance(prod, (list, tuple)) and len(prod) == 2 else str(prod or '-')
                qty = r.get('product_qty', 0)
                price = float(r.get('price_unit') or 0)
                seen_vendors.setdefault(pname, []).append(
                    f"{prodname} × {qty} @ {price:,.2f} {CURRENCY}"
                )
            for vendor, items in seen_vendors.items():
                reply_lines.append(f"🏢 **{vendor}**")
                for item in items:
                    reply_lines.append(f"   • {item}")
                reply_lines.append("")
            # Friendly CTA
            cta = ("\n💬 Want me to create an RFQ for one of these vendors, or search for UAE suppliers online?"
                   if lang == 'en'
                   else "\n💬 تريد إنشاء طلب تسعير لأحد هؤلاء الموردين، أو البحث عن موردين آخرين في الإمارات؟")
            reply_lines.append(cta)
            self._post_message("\n".join(reply_lines), mail_message_id)
            return {}

        # Generic formatting
        if lang == 'en':
            header = f"{AGENT_PERSONA}: 🔍 Found **{len(records)}** record(s) in {model_name}:"
        else:
            header = f"{AGENT_PERSONA}: 🔍 {_t('found', lang)} **{len(records)}** {_t('records', lang)} في {model_name}:"
        reply_lines = [header]
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
            reply_lines.append(f"- **{title}**" + (f" — {detail_str}" if detail_str else ""))
        self._post_message("\n".join(reply_lines), mail_message_id)
        return {}

    # ── CREATE LEAD ───────────────────────────────────────────────
    def _tool_create_lead(self, args, mail_message_id, lang='ar'):
        env = request.env

        new_lead = env['crm.lead'].create({
            'name':             args.get('name', 'AI Lead'),
            'partner_name':     args.get('partner_name', ''),
            'email_from':       args.get('email_from', ''),
            'phone':            args.get('phone', ''),
            'description':      args.get('description', ''),
            'expected_revenue': float(args.get('expected_revenue', 0.0)),
        })

        default_msg = (f"Lead created: {new_lead.name}" if lang == 'en'
                       else f"تم إنشاء Lead: {new_lead.name}")
        msg = args.get('message_to_user', default_msg)
        self._post_message(f"{AGENT_PERSONA}: ✅ {msg}", mail_message_id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'res_id': new_lead.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── CREATE INVOICE ────────────────────────────────────────────
    def _tool_create_invoice(self, args, mail_message_id, lang='ar'):
        env = request.env

        move_type    = args.get('move_type', 'out_invoice')
        partner_name = args.get('partner_name', 'Unknown')
        partner_vat  = args.get('partner_vat', '')
        invoice_date = args.get('invoice_date') or fields.Date.today()
        lines_data   = args.get('lines', [])

        # Find/create partner — auto-assign UAE country if new
        partner = env['res.partner'].search([('name', '=ilike', partner_name)], limit=1)
        if not partner:
            uae = env['res.country'].search([('code', '=', 'AE')], limit=1)
            partner_vals = {'name': partner_name, 'vat': partner_vat}
            if uae:
                partner_vals['country_id'] = uae.id
            partner = env['res.partner'].create(partner_vals)
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

        default_msg = (f"{move_type.replace('_', ' ').title()} created: {new_move.name} — Total: {_fmt_money(new_move.amount_total, lang)}"
                       if lang == 'en'
                       else f"تم إنشاء {new_move.name} — الإجمالي: {_fmt_money(new_move.amount_total, lang)}")
        msg = args.get('message_to_user', default_msg)
        self._post_message(f"{AGENT_PERSONA}: ✅ {msg}", mail_message_id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': new_move.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── CREATE BANK STATEMENT ─────────────────────────────────────
    def _tool_create_bank_stmt(self, args, mail_message_id, lang='ar'):
        env = request.env

        journal = env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', env.company.id)],
            limit=1
        )
        if not journal:
            err = (f"{AGENT_PERSONA}: ⛔ No bank journal found in the system."
                   if lang == 'en'
                   else f"{AGENT_PERSONA}: ⛔ لم أجد دفتر يومية بنكي (Bank Journal) في النظام.")
            self._post_message(err, mail_message_id)
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

        default_msg = (f"Bank statement created: {new_stmt.name}"
                       if lang == 'en'
                       else f"تم إنشاء كشف بنكي: {new_stmt.name}")
        msg = args.get('message_to_user', default_msg)
        self._post_message(f"{AGENT_PERSONA}: ✅ {msg}", mail_message_id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement',
            'res_id': new_stmt.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── CREATE RFQ ────────────────────────────────────────────────
    def _tool_create_rfq(self, args, mail_message_id, lang='ar'):
        env = request.env

        vendor_name  = args.get('vendor_name', '')
        vendor_email = args.get('vendor_email', '')
        vendor_phone = args.get('vendor_phone', '')
        products     = args.get('products', [])
        notes        = args.get('notes', '')

        # Find or create vendor — default UAE country for new vendors
        vendor = env['res.partner'].search([('name', '=ilike', vendor_name)], limit=1)
        if not vendor:
            vendor = env['res.partner'].search([('name', 'ilike', vendor_name)], limit=1)
        if not vendor:
            uae = env['res.country'].search([('code', '=', 'AE')], limit=1)
            vendor_vals = {
                'name':       vendor_name,
                'is_company': True,
                'email':      vendor_email,
                'phone':      vendor_phone,
            }
            if uae:
                vendor_vals['country_id'] = uae.id
            vendor = env['res.partner'].create(vendor_vals)
        else:
            updates = {}
            if vendor_email and not vendor.email:
                updates['email'] = vendor_email
            if vendor_phone and not vendor.phone:
                updates['phone'] = vendor_phone
            if updates:
                vendor.write(updates)

        final_email = vendor_email or vendor.email
        final_phone = vendor_phone or vendor.phone

        # ── Email required — auto web search in UAE context ─────
        if not final_email:
            search_status = (
                f"{AGENT_PERSONA}: 🌐 Vendor **{vendor_name}** has no email on file.\n"
                f"Searching UAE business directories online..."
            ) if lang == 'en' else (
                f"{AGENT_PERSONA}: 🌐 المورد **{vendor_name}** ليس لديه إيميل في النظام.\n"
                f"جاري البحث في دليل الشركات الإماراتية..."
            )
            self._post_message(search_status, mail_message_id)

            try:
                from google.genai import types as _types
                _api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
                _gclient = genai.Client(api_key=_api_key)

                # UAE-focused search
                _search_query = (
                    f"Find the official contact email and phone number of '{vendor_name}' "
                    f"located in United Arab Emirates (UAE). "
                    f"Priority: Dubai, Abu Dhabi, Sharjah offices. "
                    f"Return ONLY in this format: EMAIL: xxx@xxx.com | PHONE: +971xxxxxxx"
                )
                _search_resp = _gclient.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[_search_query],
                    config=_types.GenerateContentConfig(
                        tools=[_types.Tool(google_search=_types.GoogleSearch())],
                        temperature=0.0,
                    )
                )
                _result = (getattr(_search_resp, 'text', '') or '').strip()

                # Retry with different phrasing if needed
                if 'NOT_FOUND' in _result or '@' not in _result:
                    _retry_query = (
                        f"What is the official website and UAE contact email of '{vendor_name}' company? "
                        f"Search UAE business directories and return the email."
                    )
                    _search_resp2 = _gclient.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[_retry_query],
                        config=_types.GenerateContentConfig(
                            tools=[_types.Tool(google_search=_types.GoogleSearch())],
                            temperature=0.0,
                        )
                    )
                    _result2 = (getattr(_search_resp2, 'text', '') or '').strip()
                    if '@' in _result2:
                        _result = _result2

                _logger.info(f"KH_AI v2.4 vendor search '{vendor_name}': {_result[:200]}")

                _email_match = re.search(r'[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}', _result)
                _phone_match = re.search(r'\+?\d[\d\s\-]{8,}', _result)

                if _email_match:
                    final_email = _email_match.group()
                    if _phone_match and not final_phone:
                        final_phone = _phone_match.group().strip()
                    vendor.write({'email': final_email, 'phone': final_phone or vendor.phone})

                    found_msg = (
                        f"{AGENT_PERSONA}: ✅ Found contact info for {vendor_name}:\n"
                        f"• {_t('email', lang)}: **{final_email}**\n"
                        f"• {_t('phone', lang)}: **{final_phone or _t('not_available', lang)}**\n"
                        f"Creating RFQ..."
                    ) if lang == 'en' else (
                        f"{AGENT_PERSONA}: ✅ وجدت بيانات {vendor_name}:\n"
                        f"• {_t('email', lang)}: **{final_email}**\n"
                        f"• {_t('phone', lang)}: **{final_phone or _t('not_available', lang)}**\n"
                        f"جاري إنشاء الطلب..."
                    )
                    self._post_message(found_msg, mail_message_id)
                else:
                    not_found_msg = (
                        f"{AGENT_PERSONA}: ⚠️ Could not find an email for **{vendor_name}** in UAE directories.\n"
                        f"Please provide it: 'The email of {vendor_name} is info@example.com' then retry."
                    ) if lang == 'en' else (
                        f"{AGENT_PERSONA}: ⚠️ لم أجد إيميلاً لـ **{vendor_name}** في دليل الإمارات.\n"
                        f"يرجى تزويدي به: 'إيميل {vendor_name} هو info@example.com' ثم أعد الطلب."
                    )
                    self._post_message(not_found_msg, mail_message_id)
                    return {}
            except Exception as _e:
                _logger.exception("KH_AI v2.4: web search for vendor email failed")
                fail_msg = (
                    f"{AGENT_PERSONA}: ⚠️ Vendor **{vendor_name}** has no email on file.\n"
                    f"Please add the vendor email in the system first."
                ) if lang == 'en' else (
                    f"{AGENT_PERSONA}: ⚠️ المورد **{vendor_name}** ليس لديه إيميل.\n"
                    f"يرجى إضافة الإيميل للمورد في النظام أولاً."
                )
                self._post_message(fail_msg, mail_message_id)
                return {}

        # ── Build order lines ─────────────────────────────────────
        # NOTE: Many Odoo installations have Record Rules on account.tax
        # that hide specific tax records from normal users. When creating
        # purchase.order.line the computed tax field reads account.tax →
        # AccessError.
        #
        # Fix strategy (v2.4): use sudo() for product search/create AND
        # for purchase.order.create. This bypasses Record Rules entirely
        # for these specific operations. We then reassign user_id to the
        # real user for a proper audit trail.
        # We do NOT touch tax fields directly because their field names
        # vary across Odoo versions/modules (taxes_id vs tax_ids vs custom).
        order_lines = []
        missing_products = []
        for p in products:
            prod_name = (p.get('name') or '').strip()
            if not prod_name:
                continue

            # Use sudo to bypass tax record rules during product read/create
            product = env['product.product'].sudo().search(
                [('name', '=ilike', prod_name)], limit=1
            )
            if not product:
                try:
                    product = env['product.product'].sudo().create({
                        'name':        prod_name,
                        'type':        'consu',
                        'purchase_ok': True,
                    })
                except Exception as _pe:
                    _logger.exception(f"KH_AI v2.4: product create failed: {prod_name}")
                    missing_products.append(prod_name)
                    continue

            line_vals = {
                'product_id':  product.id,
                'name':        product.name or prod_name,
                'product_qty': float(p.get('quantity', 1.0)),
            }
            price = float(p.get('price', 0.0))
            if price:
                line_vals['price_unit'] = price

            order_lines.append((0, 0, line_vals))

        # Safety: if all products failed to materialize, abort cleanly
        if not order_lines:
            err = (f"{AGENT_PERSONA}: ⛔ Could not prepare any product line for the RFQ.\n"
                   f"Problem products: {', '.join(missing_products) or 'unknown'}"
                   if lang == 'en'
                   else f"{AGENT_PERSONA}: ⛔ لم أتمكن من تحضير أي بند في الطلب.\n"
                        f"المنتجات التي فشلت: {', '.join(missing_products) or 'غير معروف'}")
            self._post_message(err, mail_message_id)
            return {}

        rfq_vals = {
            'partner_id': vendor.id,
            'order_line': order_lines,
        }
        if notes:
            rfq_vals['notes'] = notes

        # Create RFQ with sudo (bypasses account.tax record rules) then
        # reassign user_id to the real user so the audit trail is correct.
        try:
            new_rfq = env['purchase.order'].sudo().create(rfq_vals)
        except Exception as _poe:
            _logger.exception("KH_AI v2.4: purchase.order create failed")
            err = (f"{AGENT_PERSONA}: ⛔ Failed to create RFQ:\n{_poe}"
                   if lang == 'en'
                   else f"{AGENT_PERSONA}: ⛔ فشل إنشاء طلب التسعير:\n{_poe}")
            self._post_message(err, mail_message_id)
            return {}

        # Preserve audit trail with the real logged-in user
        try:
            new_rfq.sudo().write({'user_id': env.user.id})
        except Exception as _ue:
            _logger.warning(f"KH_AI v2.4: couldn't reassign user_id on RFQ: {_ue}")

        # ── Build rich success message with line summary ─────────
        line_summary = []
        for ln in new_rfq.order_line:
            line_summary.append(
                f"   • {ln.name} × {ln.product_qty:g}"
                + (f" @ {_fmt_money(ln.price_unit, lang)}" if ln.price_unit else "")
            )
        lines_block = "\n".join(line_summary) if line_summary else "—"

        if lang == 'en':
            default_msg = (
                f"RFQ created: **{new_rfq.name}**\n"
                f"🏢 Vendor: {vendor.name}\n"
                f"📧 Email: {final_email or 'N/A'}\n"
                f"📦 Items ({len(new_rfq.order_line)}):\n{lines_block}"
            )
        else:
            default_msg = (
                f"تم إنشاء طلب التسعير: **{new_rfq.name}**\n"
                f"🏢 المورد: {vendor.name}\n"
                f"📧 الإيميل: {final_email or 'غير متوفر'}\n"
                f"📦 البنود ({len(new_rfq.order_line)}):\n{lines_block}"
            )

        # If the LLM provided a custom message, prepend it; otherwise use the default
        llm_msg = args.get('message_to_user', '').strip()
        final_text = f"{llm_msg}\n\n{default_msg}" if llm_msg else default_msg
        self._post_message(f"{AGENT_PERSONA}: ✅ {final_text}", mail_message_id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': new_rfq.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── ANALYTICS ────────────────────────────────────────────────
    def _tool_analytics(self, args, mail_message_id, lang='ar'):
        env       = request.env
        report    = args.get('report_type', '')
        date_from = args.get('date_from') or fields.Date.today().replace(month=1, day=1).strftime('%Y-%m-%d')
        date_to   = args.get('date_to')   or str(fields.Date.today())
        limit     = min(int(args.get('limit', 10)), 50)

        # Period header (language-aware)
        period_header = (f"Period: {date_from} → {date_to}" if lang == 'en'
                         else f"الفترة: {date_from} → {date_to}")

        try:
            rows = []

            if report == 'profit_by_category':
                title = ("Profit Margins by Category" if lang == 'en'
                         else "هوامش الربح حسب فئة المنتج")
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
                    no_data = (f"{AGENT_PERSONA}: 📊 No confirmed invoices in period {date_from} → {date_to}"
                               if lang == 'en'
                               else f"{AGENT_PERSONA}: 📊 لا توجد بيانات فواتير مؤكدة في الفترة {date_from} → {date_to}")
                    self._post_message(no_data, mail_message_id)
                    return {}

                if lang == 'en':
                    lines = [
                        f"{AGENT_PERSONA}: 📊 **{title}**",
                        f"{period_header}\n",
                        "| Category | Revenue | Cost | Profit | Margin % |",
                        "|----------|---------|------|--------|----------|",
                    ]
                else:
                    lines = [
                        f"{AGENT_PERSONA}: 📊 **{title}**",
                        f"{period_header}\n",
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
                        f"| {r['category']} | {_fmt_money(rev, lang)} | {_fmt_money(cost, lang)} "
                        f"| {_fmt_money(profit, lang)} | {margin_icon} {margin}% |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            elif report == 'revenue_by_partner':
                title = ("Revenue by Customer" if lang == 'en' else "الإيراد حسب العميل")
                env.cr.execute("""
                    SELECT rp.name AS partner, COUNT(am.id) AS invoice_count,
                           SUM(am.amount_untaxed) AS revenue, SUM(am.amount_tax) AS tax
                    FROM account_move am
                    JOIN res_partner rp ON rp.id = am.partner_id
                    WHERE am.move_type = 'out_invoice' AND am.state = 'posted'
                      AND am.invoice_date BETWEEN %s AND %s AND am.company_id = %s
                    GROUP BY rp.name
                    ORDER BY revenue DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                if lang == 'en':
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| Customer | Invoices | Revenue (excl. VAT) | VAT |",
                             "|----------|----------|---------------------|-----|"]
                else:
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| العميل | عدد الفواتير | الإيراد (بدون VAT) | VAT |",
                             "|--------|-------------|-------------------|-----|"]
                for r in rows:
                    lines.append(
                        f"| {r['partner']} | {r['invoice_count']} "
                        f"| {_fmt_money(r['revenue'], lang)} | {_fmt_money(r['tax'], lang)} |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            elif report == 'top_products':
                title = ("Top Products by Revenue" if lang == 'en' else "أفضل المنتجات مبيعاً")
                env.cr.execute("""
                    SELECT COALESCE(pt.name->>'en_US', pt.name->>'ar_001', pt.name::text) AS product,
                           SUM(aml.quantity) AS qty_sold,
                           SUM(aml.quantity * aml.price_unit) AS revenue
                    FROM account_move_line aml
                    JOIN account_move am ON am.id = aml.move_id
                    JOIN product_product pp ON pp.id = aml.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE am.move_type = 'out_invoice' AND am.state = 'posted'
                      AND am.invoice_date BETWEEN %s AND %s AND aml.product_id IS NOT NULL
                      AND am.company_id = %s
                    GROUP BY pt.name->>'en_US'
                    ORDER BY revenue DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                if lang == 'en':
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| # | Product | Qty | Revenue |", "|---|---------|-----|---------|"]
                else:
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| # | المنتج | الكمية | الإيراد |", "|---|--------|--------|---------|"]
                for i, r in enumerate(rows, 1):
                    lines.append(
                        f"| {i} | {r['product']} | {float(r['qty_sold'] or 0):,.1f} "
                        f"| {_fmt_money(r['revenue'], lang)} |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            elif report == 'expense_breakdown':
                title = ("Expense Breakdown" if lang == 'en' else "تحليل المصروفات")
                env.cr.execute("""
                    SELECT COALESCE(aa.name->>'en_US', aa.name->>'ar_001', aa.name::text) AS account,
                           SUM(aml.debit - aml.credit) AS amount
                    FROM account_move_line aml
                    JOIN account_account aa ON aa.id = aml.account_id
                    JOIN account_move am ON am.id = aml.move_id
                    WHERE aa.account_type IN ('expense', 'expense_depreciation', 'expense_direct_cost')
                      AND am.state = 'posted' AND am.date BETWEEN %s AND %s
                      AND am.company_id = %s
                    GROUP BY aa.name->>'en_US'
                    ORDER BY amount DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                total = sum(float(r['amount'] or 0) for r in rows)
                if lang == 'en':
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| Account | Amount | % |", "|---------|--------|---|"]
                else:
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| الحساب | المبلغ | النسبة % |", "|--------|--------|----------|"]
                for r in rows:
                    amt  = float(r['amount'] or 0)
                    pct  = round(amt / total * 100, 1) if total else 0
                    lines.append(f"| {r['account']} | {_fmt_money(amt, lang)} | {pct}% |")
                total_label = "**Total**" if lang == 'en' else "**الإجمالي**"
                lines.append(f"| {total_label} | **{_fmt_money(total, lang)}** | **100%** |")
                self._post_message("\n".join(lines), mail_message_id)

            elif report == 'invoice_summary':
                title = ("Invoice Summary" if lang == 'en' else "ملخص الفواتير")
                env.cr.execute("""
                    SELECT move_type, state, COUNT(*) AS count, SUM(amount_total) AS total
                    FROM account_move
                    WHERE move_type IN ('out_invoice', 'in_invoice', 'out_refund', 'in_refund')
                      AND invoice_date BETWEEN %s AND %s AND company_id = %s
                    GROUP BY move_type, state ORDER BY move_type, state
                """, (date_from, date_to, env.company.id))
                rows = env.cr.dictfetchall()

                if lang == 'en':
                    type_labels = {'out_invoice': 'Customer Invoice', 'in_invoice': 'Vendor Bill',
                                   'out_refund': 'Customer Credit Note', 'in_refund': 'Vendor Credit Note'}
                    state_labels = {'draft': 'Draft', 'posted': 'Posted', 'cancel': 'Cancelled'}
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| Type | Status | Count | Total |", "|------|--------|-------|-------|"]
                else:
                    type_labels = {'out_invoice': 'فاتورة عميل', 'in_invoice': 'فاتورة مورد',
                                   'out_refund': 'إشعار دائن', 'in_refund': 'إشعار مدين'}
                    state_labels = {'draft': 'مسودة', 'posted': 'مؤكدة', 'cancel': 'ملغاة'}
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| النوع | الحالة | العدد | الإجمالي |", "|------|--------|-------|---------|"]
                for r in rows:
                    lines.append(
                        f"| {type_labels.get(r['move_type'], r['move_type'])} "
                        f"| {state_labels.get(r['state'], r['state'])} "
                        f"| {r['count']} | {_fmt_money(r['total'], lang)} |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            elif report == 'stock_valuation':
                title = ("Stock Valuation" if lang == 'en' else "تقييم المخزون")
                products = env['product.product'].search_read(
                    [('type', 'in', ['product', 'consu']), ('qty_available', '>', 0)],
                    fields=['name', 'qty_available', 'standard_price', 'categ_id'],
                    limit=limit, order='qty_available desc',
                )
                if lang == 'en':
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**\n",
                             "| Product | Qty | Unit Cost | Total Value |",
                             "|---------|-----|-----------|-------------|"]
                else:
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**\n",
                             "| المنتج | الكمية | سعر التكلفة | القيمة الإجمالية |",
                             "|--------|--------|-------------|-----------------|"]
                total_val = 0
                for p in products:
                    qty  = float(p['qty_available'])
                    cost = float(p['standard_price'])
                    val  = qty * cost
                    total_val += val
                    cat  = p['categ_id'][1] if p.get('categ_id') else '-'
                    lines.append(
                        f"| {p['name']} ({cat}) | {qty:,.1f} | {_fmt_money(cost, lang)} | {_fmt_money(val, lang)} |"
                    )
                total_label = "**Total Inventory Value**" if lang == 'en' else "**إجمالي قيمة المخزون**"
                lines.append(f"| {total_label} | — | — | **{_fmt_money(total_val, lang)}** |")
                self._post_message("\n".join(lines), mail_message_id)

            elif report == 'sales_pipeline':
                title = ("Sales Pipeline (CRM)" if lang == 'en' else "خط أنابيب المبيعات (CRM)")
                env.cr.execute("""
                    SELECT cs.name AS stage, COUNT(cl.id) AS count,
                           SUM(cl.expected_revenue) AS expected, AVG(cl.probability) AS avg_prob
                    FROM crm_lead cl JOIN crm_stage cs ON cs.id = cl.stage_id
                    WHERE cl.type = 'opportunity' AND cl.active = true AND cl.company_id = %s
                    GROUP BY cs.name, cs.sequence ORDER BY cs.sequence
                """, (env.company.id,))
                rows = env.cr.dictfetchall()

                if lang == 'en':
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**\n",
                             "| Stage | Count | Expected Revenue | Probability |",
                             "|-------|-------|-----------------|-------------|"]
                else:
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**\n",
                             "| المرحلة | العدد | الإيراد المتوقع | احتمالية الإغلاق |",
                             "|---------|-------|----------------|-----------------|"]
                for r in rows:
                    prob = round(float(r['avg_prob'] or 0), 0)
                    prob_icon = "🟢" if prob >= 70 else "🟡" if prob >= 40 else "🔴"
                    lines.append(
                        f"| {r['stage']} | {r['count']} "
                        f"| {_fmt_money(r['expected'], lang)} | {prob_icon} {prob}% |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            elif report == 'project_cost':
                title = ("Project Costs" if lang == 'en' else "تكاليف المشاريع")
                env.cr.execute("""
                    SELECT COALESCE(pp.name->>'en_US', pp.name->>'ar_001', pp.name::text) AS project,
                           SUM(aal.amount) AS total_cost, SUM(aal.unit_amount) AS total_hours,
                           COUNT(DISTINCT aal.employee_id) AS team_size
                    FROM account_analytic_line aal
                    JOIN project_task pt2 ON pt2.id = aal.task_id
                    JOIN project_project pp ON pp.id = pt2.project_id
                    WHERE aal.date BETWEEN %s AND %s AND pp.company_id = %s
                      AND aal.task_id IS NOT NULL
                    GROUP BY pp.name ORDER BY total_cost DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                if not rows:
                    env.cr.execute("""
                        SELECT COALESCE(pp.name->>'en_US', pp.name->>'ar_001', pp.name::text) AS project,
                               SUM(aal.amount) AS total_cost, SUM(aal.unit_amount) AS total_hours,
                               COUNT(DISTINCT aal.employee_id) AS team_size
                        FROM account_analytic_line aal
                        JOIN project_project pp ON pp.id = aal.project_id
                        WHERE aal.date BETWEEN %s AND %s AND pp.company_id = %s
                          AND aal.project_id IS NOT NULL
                        GROUP BY pp.name ORDER BY total_cost DESC LIMIT %s
                    """, (date_from, date_to, env.company.id, limit))
                    rows = env.cr.dictfetchall()

                if not rows:
                    projects_orm = env['project.project'].search_read(
                        [('company_id', '=', env.company.id)],
                        fields=['name', 'allocated_hours'], limit=limit,
                    )
                    projects_orm = [p for p in projects_orm if str(p['name']).lower().startswith('project:')]
                    rows = [{'project': p['name'], 'total_cost': 0,
                             'total_hours': p.get('allocated_hours') or 0, 'team_size': 0}
                            for p in projects_orm]

                if not rows:
                    projects = env['project.project'].search_read(
                        [('company_id', '=', env.company.id)],
                        fields=['name', 'allocated_hours', 'date_start', 'date'], limit=limit,
                    )
                    if lang == 'en':
                        lines = [f"{AGENT_PERSONA}: 📊 **{title}** (no analytic data linked)\n",
                                 "| Project | Allocated Hours | Start Date | End Date |",
                                 "|---------|----------------|-----------|----------|"]
                    else:
                        lines = [f"{AGENT_PERSONA}: 📊 **{title}** (لا توجد بيانات تحليلية مرتبطة)\n",
                                 "| المشروع | ساعات مخصصة | تاريخ البدء | تاريخ الانتهاء |",
                                 "|---------|------------|------------|----------------|"]
                    for p in projects:
                        lines.append(
                            f"| {p['name']} | {p.get('allocated_hours') or 0:,.0f} "
                            f"| {p.get('date_start') or '-'} | {p.get('date') or '-'} |"
                        )
                    self._post_message("\n".join(lines), mail_message_id)
                else:
                    def _clean_name(val):
                        if isinstance(val, dict):
                            return val.get('en_US') or val.get('ar_001') or next(iter(val.values()), str(val))
                        s = str(val)
                        if s.startswith('{') and ':' in s:
                            try:
                                d = json.loads(s.replace("'", '"'))
                                return d.get('en_US') or next(iter(d.values()), s)
                            except Exception:
                                pass
                        return s

                    rows = [r for r in rows if _clean_name(r['project']).lower().startswith('project:')]
                    if not rows:
                        no_proj = ("🔍 No projects found starting with 'Project:' prefix."
                                   if lang == 'en'
                                   else "🔍 لم أجد مشاريع تبدأ بـ 'Project:'.")
                        self._post_message(f"{AGENT_PERSONA}: {no_proj}", mail_message_id)
                        return {}

                    if lang == 'en':
                        lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                                 "| # | Project | Total Cost | Hours | Team Size |",
                                 "|---|---------|-----------|-------|-----------|"]
                    else:
                        lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                                 "| # | المشروع | التكلفة الإجمالية | الساعات | حجم الفريق |",
                                 "|---|---------|-----------------|---------|-----------|"]
                    for i, r in enumerate(rows, 1):
                        cost  = float(r['total_cost']  or 0)
                        hours = float(r['total_hours'] or 0)
                        team  = int(r['team_size']     or 0)
                        name  = _clean_name(r['project'])
                        lines.append(f"| {i} | {name} | {_fmt_money(cost, lang)} | {hours:,.1f} h | {team} |")
                    self._post_message("\n".join(lines), mail_message_id)

            elif report == 'timesheet_hours':
                title = ("Timesheet Hours" if lang == 'en' else "ساعات العمل (Timesheets)")
                env.cr.execute("""
                    SELECT pp.name AS project, he.name AS employee, SUM(aal.unit_amount) AS hours
                    FROM account_analytic_line aal
                    JOIN project_task pt2 ON pt2.id = aal.task_id
                    JOIN project_project pp ON pp.id = pt2.project_id
                    LEFT JOIN hr_employee he ON he.id = aal.employee_id
                    WHERE aal.date BETWEEN %s AND %s AND pp.company_id = %s
                      AND aal.task_id IS NOT NULL
                    GROUP BY pp.name, he.name ORDER BY hours DESC LIMIT %s
                """, (date_from, date_to, env.company.id, limit))
                rows = env.cr.dictfetchall()

                if lang == 'en':
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| Project | Employee | Hours |", "|---------|----------|-------|"]
                else:
                    lines = [f"{AGENT_PERSONA}: 📊 **{title}**", f"{period_header}\n",
                             "| المشروع | الموظف | الساعات |", "|---------|--------|---------|"]
                na = "N/A" if lang == 'en' else "غير محدد"
                for r in rows:
                    lines.append(
                        f"| {r['project']} | {r['employee'] or na} | {float(r['hours'] or 0):,.1f} h |"
                    )
                self._post_message("\n".join(lines), mail_message_id)

            elif report == 'project_financial':
                project_keyword = (args.get('project_name') or '').strip()

                if not project_keyword:
                    err = ("⚠️ Please specify the project name or number."
                           if lang == 'en'
                           else "⚠️ يرجى تحديد اسم المشروع أو رقمه.")
                    self._post_message(f"{AGENT_PERSONA}: {err}", mail_message_id)
                    return {}

                _all = env['project.project'].sudo().search_read(
                    [], fields=['id', 'name', 'partner_id', 'date_start', 'date'], limit=500
                )

                from difflib import SequenceMatcher as _SM
                _kw = project_keyword.lower()
                _skip_words = {'project', 'client', 'matar', 'ahmed', 'ahmad', 'saeed',
                               'salem', 'ali', 'omar', 'rashed', 'abdulla', 'khaled',
                               'mohamed', 'mohammed', 'opportunity', 'and', 'the'}

                def _word_sim(a, b):
                    return _SM(None, a.lower(), b.lower()).ratio()

                def _score(p):
                    _n  = str(p.get('name') or '').lower()
                    _pa = str(p['partner_id'][1] if p.get('partner_id') else '').lower()
                    _full = _n + ' ' + _pa
                    _kw_words = [w for w in _kw.split() if len(w) > 2 and w not in _skip_words]
                    if not _kw_words:
                        _kw_words = [w for w in _kw.split() if len(w) > 2]
                    _pn_words = [w for w in re.split(r'[\s\-|:]+', _full) if len(w) > 2]
                    _total = 0.0
                    for _kw_word in _kw_words:
                        _best = max((_word_sim(_kw_word, pw) for pw in _pn_words), default=0)
                        if _best > 0.75:
                            _total += 4 * _best
                        elif _best > 0.6:
                            _total += 2 * _best
                    _num = re.search(r'\d{4,5}', _kw)
                    if _num and _num.group() in _n:
                        _total += 10
                    return _total

                _ranked = sorted(_all, key=_score, reverse=True)
                _best   = _ranked[0] if _ranked else None
                _best_score = _score(_best) if _best else 0
                _logger.info(f"KH_AI v2.4 project_financial: kw='{project_keyword}' best='{_best['name'] if _best else None}' score={_best_score:.2f}")

                if not _best or _best_score < 0.5:
                    not_found = (f"🔍 No project matches '{project_keyword}'."
                                 if lang == 'en'
                                 else f"🔍 لم أجد مشروعاً يطابق '{project_keyword}'.")
                    self._post_message(f"{AGENT_PERSONA}: {not_found}", mail_message_id)
                    return {}

                projects = [_best]
                report_lines = [f"{AGENT_PERSONA}: 📊 **{_t('financial_status', lang)}**\n"]

                for proj in projects:
                    partner    = (proj['partner_id'][1] if proj.get('partner_id')
                                  else ('Not specified' if lang == 'en' else 'غير محدد'))
                    partner_id = proj['partner_id'][0] if proj.get('partner_id') else None

                    _proj_name_full = str(proj.get('name') or '')
                    _partner_name   = str(proj['partner_id'][1] if proj.get('partner_id') else '')
                    _combined_name  = _proj_name_full + ' ' + _partner_name
                    _skip = {'project', 'client', 'matar', 'ahmed', 'ahmad', 'saeed',
                             'salem', 'ali', 'omar', 'rashed', 'abdulla', 'khaled',
                             'mohamed', 'mohammed', 'opportunity'}
                    _eng_words = [w for w in re.findall(r'[A-Za-z]{5,}', _combined_name)
                                  if w.lower() not in _skip]
                    _family_name = max(_eng_words, key=len) if _eng_words else ''

                    all_partner_ids = []
                    if partner_id:
                        all_partner_ids.append(partner_id)

                    if _family_name:
                        _search_variants = [_family_name]
                        if _family_name.lower().startswith('al') and len(_family_name) > 4:
                            _search_variants.append(_family_name[2:])
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

                    all_partner_ids = list(set(all_partner_ids))

                    total_invoiced = total_paid = total_due = 0.0
                    inv_count = 0
                    if all_partner_ids:
                        inv = env['account.move'].read_group(
                            [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                             ('partner_id', 'in', all_partner_ids), ('company_id', '=', env.company.id)],
                            fields=['amount_total:sum', 'amount_residual:sum', 'id:count'],
                            groupby=[],
                        )
                        if inv:
                            total_invoiced = float(inv[0].get('amount_total') or 0)
                            total_due      = float(inv[0].get('amount_residual') or 0)
                            total_paid     = total_invoiced - total_due
                            inv_count      = int(inv[0].get('id') or 0)

                    total_bills = bill_due = 0.0
                    bill_count  = 0
                    if all_partner_ids:
                        bills = env['account.move'].read_group(
                            [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                             ('partner_id', 'in', all_partner_ids), ('company_id', '=', env.company.id)],
                            fields=['amount_total:sum', 'amount_residual:sum', 'id:count'],
                            groupby=[],
                        )
                        if bills:
                            total_bills = float(bills[0].get('amount_total') or 0)
                            bill_due    = float(bills[0].get('amount_residual') or 0)
                            bill_count  = int(bills[0].get('id') or 0)

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
                        f"{_t('client', lang)}: {partner}",
                        f"{_t('period', lang)}: {proj.get('date_start') or '-'} → {proj.get('date') or '-'}",
                        "",
                        f"{_t('invoices', lang)} ({inv_count}):**",
                        f"  • {_t('total', lang)}: **{_fmt_money(total_invoiced, lang)}**",
                        f"  • {_t('paid', lang)}: **{_fmt_money(total_paid, lang)}**",
                        f"  • {_t('due', lang)}: **{_fmt_money(total_due, lang)}**",
                        "",
                        f"{_t('expenses', lang)} ({bill_count} {_t('invoice_vendor', lang)} + {_t('analytic', lang)}):**",
                        f"  • {_t('vendor_bills', lang)}: **{_fmt_money(total_bills, lang)}**",
                        f"  • {_t('analytic', lang)}: **{_fmt_money(analytic_cost, lang)}**",
                        "",
                        f"{_t('result', lang)}",
                        f"  • {_t('net_profit', lang)}: **{_fmt_money(profit, lang)}** {margin_icon} ({margin_pct}%)",
                        "─" * 45,
                    ]
                self._post_message("\n".join(report_lines), mail_message_id)

            else:
                available = [
                    'profit_by_category', 'revenue_by_partner', 'top_products',
                    'expense_breakdown', 'invoice_summary', 'stock_valuation',
                    'sales_pipeline', 'project_cost', 'project_financial', 'timesheet_hours'
                ]
                err = (f"⚠️ Unknown report type '{report}'.\nAvailable: {', '.join(available)}"
                       if lang == 'en'
                       else f"⚠️ نوع التقرير '{report}' غير معروف.\nالأنواع المتاحة: {', '.join(available)}")
                self._post_message(f"{AGENT_PERSONA}: {err}", mail_message_id)

        except Exception as e:
            _logger.exception("KH_AI v2.4: analytics error")
            try:
                env.cr.rollback()
            except Exception:
                pass
            err = (f"{AGENT_PERSONA}: ⛔ Analytics error:\n{e}"
                   if lang == 'en'
                   else f"{AGENT_PERSONA}: ⛔ خطأ في التحليل:\n{e}")
            self._post_message(err, mail_message_id)

        return {}

    # ── ASK USER (bilingual-aware) ───────────────────────────────
    def _tool_ask_user(self, args, mail_message_id, lang='ar'):
        question = args.get('question', '')
        options  = args.get('options', [])
        context  = args.get('context', '')

        lines = [f"{AGENT_PERSONA}: 🤔"]
        if context:
            lines.append(f"_{context}_\n")
        lines.append(f"**{question}**")
        if options:
            lines.append("")
            for i, opt in enumerate(options, 1):
                lines.append(f"{i}️⃣ {opt}")
            hint = ("\n💬 Reply with the number of your choice."
                    if lang == 'en'
                    else "\n💬 أجب برقم الخيار.")
            lines.append(hint)

        self._post_message("\n".join(lines), mail_message_id)
        return {}

    # ── BULK UPDATE RECORDS ──────────────────────────────────────
    def _tool_update_records(self, args, mail_message_id, lang='ar'):
        env = request.env
        operation    = args.get('operation', '')
        partner_name = args.get('partner_name', '')
        account_code = args.get('account_code', '')
        account_name = args.get('account_name', '')

        if operation == 'set_bank_statement_account':
            senv    = env(su=True)
            dry_run = bool(args.get('dry_run', False))

            # ── 1. Resolve target account ─────────────────────────────
            base_acc_domain = [('company_ids', 'in', env.company.id)]
            account = senv['account.account'].browse()
            if account_code:
                account = senv['account.account'].search(
                    base_acc_domain + [('code', '=', account_code)], limit=1
                )
            if not account and account_name:
                account = senv['account.account'].search(
                    base_acc_domain + [('name', 'ilike', account_name)], limit=1
                ) or senv['account.account'].search(
                    base_acc_domain + [('code', 'ilike', account_name)], limit=1
                )
            if not account:
                err = (f"⛔ No account found with code '{account_code}' or name '{account_name}'."
                       if lang == 'en'
                       else f"⛔ لم أجد حساباً بالكود '{account_code}' أو الاسم '{account_name}'.")
                self._post_message(f"{AGENT_PERSONA}: {err}", mail_message_id)
                return {}

            # ── 2. Robust partner + bank-line lookup ──────────────────
            if not partner_name:
                err = ("⚠️ Please specify the partner name."
                       if lang == 'en'
                       else "⚠️ يرجى تحديد اسم الشريك.")
                self._post_message(f"{AGENT_PERSONA}: {err}", mail_message_id)
                return {}

            stmt_lines, partners = _find_bank_lines_for_partner(senv, partner_name)

            if not stmt_lines:
                if not partners:
                    msg = ("🔍 No partner matches" if lang == 'en' else "🔍 لم أجد شريكاً مطابقاً")
                else:
                    pnames = ', '.join(partners.mapped('name')[:3])
                    msg = (f"🔍 No bank statement lines found for: {pnames}"
                           if lang == 'en'
                           else f"🔍 لم أجد بنود كشف بنكي لـ: {pnames}")
                variants_hint = ', '.join(_partner_keyword_variants(partner_name))
                hint = (f"\n💡 Tried: {variants_hint}" if lang == 'en'
                        else f"\n💡 جربت: {variants_hint}")
                self._post_message(f"{AGENT_PERSONA}: {msg}{hint}", mail_message_id)
                return {}

            # ── 3. Dry-run preview ────────────────────────────────────
            partner_label = ', '.join(partners.mapped('name')[:3]) if partners else partner_name
            if dry_run:
                if lang == 'en':
                    preview = [
                        f"{AGENT_PERSONA}: 🔍 **Preview — would update {len(stmt_lines)} lines**",
                        f"• Partner match: **{partner_label}**",
                        f"• Target account: **{account.code} - {account.display_name}**",
                        "", "**Sample (first 10):**",
                    ]
                else:
                    preview = [
                        f"{AGENT_PERSONA}: 🔍 **معاينة — سيتم تحديث {len(stmt_lines)} بند**",
                        f"• الشريك المطابق: **{partner_label}**",
                        f"• الحساب المستهدف: **{account.code} - {account.display_name}**",
                        "", "**عينة (أول 10):**",
                    ]
                for st in stmt_lines[:10]:
                    lbl = (st.payment_ref or '')[:60]
                    preview.append(f"   • {st.date} | {lbl} | {_fmt_money(st.amount, lang)}")
                confirm = ("\n💬 Reply 'confirm' to apply." if lang == 'en'
                           else "\n💬 رد بـ 'confirm' للتنفيذ.")
                preview.append(confirm)
                self._post_message("\n".join(preview), mail_message_id)
                return {}

            # ── 4. Apply the update ───────────────────────────────────
            updated = 0
            skipped_already_set    = 0
            skipped_no_counterpart = 0
            failed = 0
            samples = []

            for st_line in stmt_lines:
                try:
                    move = senv['account.move'].browse(st_line.move_id.id)
                    if not move:
                        failed += 1
                        continue

                    bank_account = senv['account.journal'].browse(
                        st_line.journal_id.id
                    ).default_account_id

                    counterpart = move.line_ids.filtered(
                        lambda ml: ml.account_id.id != bank_account.id
                    )
                    already     = counterpart.filtered(
                        lambda ml: ml.account_id.id == account.id
                    )
                    counterpart = counterpart - already

                    if not counterpart and already:
                        skipped_already_set += 1
                        continue
                    if not counterpart:
                        skipped_no_counterpart += 1
                        continue

                    was_posted = move.state == 'posted'
                    if was_posted:
                        move.button_draft()
                    counterpart.write({'account_id': account.id})
                    if was_posted:
                        move.action_post()

                    updated += 1
                    if len(samples) < 5:
                        lbl = (st_line.payment_ref or '')[:55]
                        samples.append(f"   • {st_line.date} | {lbl} → **{account.code}**")

                except Exception as e:
                    _logger.warning(
                        f"KH_AI v2.5 set_bank_statement_account on line {st_line.id}: {e}"
                    )
                    failed += 1

            # ── 5. Report ─────────────────────────────────────────────
            if lang == 'en':
                out = [
                    f"{AGENT_PERSONA}: ✅ **Account assignment complete**",
                    f"• Partner: **{partner_label}**",
                    f"• Account: **{account.code} - {account.display_name}**",
                    f"• Lines matched: **{len(stmt_lines)}**",
                    f"• Updated: **{updated}**",
                ]
                if skipped_already_set:
                    out.append(f"• Already on target account: **{skipped_already_set}**")
                if skipped_no_counterpart:
                    out.append(f"• Skipped (no counterpart line): **{skipped_no_counterpart}**")
                if failed:
                    out.append(f"• Failed: **{failed}**")
                if samples:
                    out.append("\n**Sample updates:**")
                    out.extend(samples)
            else:
                out = [
                    f"{AGENT_PERSONA}: ✅ **تم تحديث الحساب**",
                    f"• الشريك: **{partner_label}**",
                    f"• الحساب: **{account.code} - {account.display_name}**",
                    f"• البنود المطابقة: **{len(stmt_lines)}**",
                    f"• تم تحديثها: **{updated}**",
                ]
                if skipped_already_set:
                    out.append(f"• على الحساب المستهدف مسبقاً: **{skipped_already_set}**")
                if skipped_no_counterpart:
                    out.append(f"• تم تجاوزها (لا يوجد سطر مقابل): **{skipped_no_counterpart}**")
                if failed:
                    out.append(f"• فشل: **{failed}**")
                if samples:
                    out.append("\n**عينة من التحديثات:**")
                    out.extend(samples)
            self._post_message("\n".join(out), mail_message_id)
            return {}

        else:
            err = (f"⚠️ Operation '{operation}' not supported yet."
                   if lang == 'en'
                   else f"⚠️ العملية '{operation}' غير مدعومة حالياً.")
            self._post_message(f"{AGENT_PERSONA}: {err}", mail_message_id)
            return {}

    # ── EXTRACT REFERENCES FROM BANK STATEMENT LABELS ─────────────
    def _tool_extract_references(self, args, mail_message_id, lang='ar'):
        """
        Pull reference codes (ECS xxxx, Cheque xxxx, Cheque 30-6-2024 …)
        out of bank statement line labels and write them to `ref`.

        Logic: split payment_ref on the LAST '|' and use the trailing chunk.
        Skips lines whose label has no '|' or whose tail is empty.
        """
        env = request.env

        statement_name = (args.get('statement_name') or '').strip()
        overwrite      = bool(args.get('overwrite', False))

        # Optional statement filter
        domain = [('statement_id', '!=', False)]
        matched_stmts = None
        if statement_name:
            matched_stmts = env['account.bank.statement'].sudo().search(
                [('name', 'ilike', statement_name)]
            )
            if not matched_stmts:
                err = (f"🔍 No bank statement matches '{statement_name}'."
                       if lang == 'en'
                       else f"🔍 لم أجد كشفاً بنكياً يطابق '{statement_name}'.")
                self._post_message(f"{AGENT_PERSONA}: {err}", mail_message_id)
                return {}

            domain.append(('statement_id', 'in', matched_stmts.ids))

        # Only touch empty refs unless explicitly told otherwise
        if not overwrite:
            domain.append(('ref', 'in', [False, '']))

        lines = env['account.bank.statement.line'].sudo().search(domain, limit=5000)

        if not lines:
            msg = ("🔍 No bank statement lines need a reference update."
                   if lang == 'en'
                   else "🔍 لا توجد بنود تحتاج تحديث المرجع.")
            self._post_message(f"{AGENT_PERSONA}: {msg}", mail_message_id)
            return {}

        updated     = 0
        skipped_pipe   = 0   # no '|' in label
        skipped_empty  = 0   # empty tail after '|'
        failed         = 0
        samples        = []

        # Strip helper — clean trailing ellipsis, dots, spaces, tabs
        def _clean_tail(s: str) -> str:
            s = (s or '').strip()
            # remove a trailing "..." (1-3 dots) that the grid often adds
            s = re.sub(r'\.{1,3}$', '', s).strip()
            return s

        for line in lines:
            label = line.payment_ref or ''
            if '|' not in label:
                skipped_pipe += 1
                continue

            # Last '|' is safer in case the label itself contains a pipe
            ref_text = _clean_tail(label.rsplit('|', 1)[1])

            if not ref_text:
                skipped_empty += 1
                continue

            try:
                line.sudo().write({'ref': ref_text})
                updated += 1
                if len(samples) < 5:
                    shown_label = (label[:55] + '…') if len(label) > 55 else label
                    samples.append(f"   • {shown_label} → **{ref_text}**")
            except Exception as e:
                _logger.warning(f"KH_AI v2.4: ref update failed on line {line.id}: {e}")
                failed += 1

        # ── Build response ────────────────────────────────────────
        if lang == 'en':
            out = [f"{AGENT_PERSONA}: ✅ **References extracted from labels**"]
            if statement_name:
                out.append(f"• Statement filter: **{statement_name}** "
                           f"({len(matched_stmts)} matched)")
            out += [
                f"• Lines processed: **{len(lines)}**",
                f"• Updated: **{updated}**",
                f"• Skipped (no `|`): **{skipped_pipe}**",
                f"• Skipped (empty tail): **{skipped_empty}**",
            ]
            if failed:
                out.append(f"• Failed: **{failed}**")
            if samples:
                out.append("\n**Sample updates:**")
                out.extend(samples)
            if not overwrite and updated:
                out.append("\n💡 Use `overwrite=true` to also replace existing references.")
        else:
            out = [f"{AGENT_PERSONA}: ✅ **تم استخراج المراجع من اللابل**"]
            if statement_name:
                out.append(f"• الكشف المُحدَّد: **{statement_name}** "
                           f"({len(matched_stmts)} مطابق)")
            out += [
                f"• البنود المعالجة: **{len(lines)}**",
                f"• تم تحديثها: **{updated}**",
                f"• تجاهل (بدون `|`): **{skipped_pipe}**",
                f"• تجاهل (فارغ بعد `|`): **{skipped_empty}**",
            ]
            if failed:
                out.append(f"• فشل: **{failed}**")
            if samples:
                out.append("\n**عينة من التحديثات:**")
                out.extend(samples)
            if not overwrite and updated:
                out.append("\n💡 استخدم `overwrite=true` لاستبدال المراجع الموجودة أيضاً.")

        self._post_message("\n".join(out), mail_message_id)
        return {}

    # ── READ CHATTER & SUMMARIZE ──────────────────────────────────
    def _tool_read_chatter(self, args, mail_message_id, lang='ar'):
        env  = request.env
        senv = env(su=True)

        model_name  = (args.get('model_name')  or '').strip()
        record_name = (args.get('record_name') or '').strip()
        limit       = min(int(args.get('limit', 40)), 100)

        if not model_name or not record_name:
            err = ("⚠️ Please provide both model and record name."
                   if lang == 'en'
                   else "⚠️ يرجى تحديد اسم النموذج والسجل.")
            self._post_message(f"{AGENT_PERSONA}: {err}", mail_message_id)
            return {}

        # ── Find the record ───────────────────────────────────────
        try:
            Model = senv[model_name]
        except KeyError:
            err = (f"⛔ Model '{model_name}' not found."
                   if lang == 'en'
                   else f"⛔ النموذج '{model_name}' غير موجود.")
            self._post_message(f"{AGENT_PERSONA}: {err}", mail_message_id)
            return {}

        record = Model.search([('name', 'ilike', record_name)], limit=1)
        if not record:
            err = (f"🔍 No '{model_name}' record found matching '{record_name}'."
                   if lang == 'en'
                   else f"🔍 لم أجد سجلاً في '{model_name}' يطابق '{record_name}'.")
            self._post_message(f"{AGENT_PERSONA}: {err}", mail_message_id)
            return {}

        record_display = record.display_name or record_name

        # ── Fetch chatter messages ────────────────────────────────
        messages = senv['mail.message'].search([
            ('model',        '=',  model_name),
            ('res_id',       '=',  record.id),
            ('message_type', 'in', ['comment', 'email']),
        ], order='date asc', limit=limit)

        if not messages:
            msg = (f"🔍 No chatter messages found on **{record_display}**."
                   if lang == 'en'
                   else f"🔍 لا توجد رسائل في الشاتر لـ **{record_display}**.")
            self._post_message(f"{AGENT_PERSONA}: {msg}", mail_message_id)
            return {}

        # ── Build transcript for Gemini to summarize ─────────────
        lines = []
        for msg in messages:
            author  = msg.author_id.name if msg.author_id else '?'
            date_s  = str(msg.date)[:16]
            body    = html2plaintext(msg.body or '').strip()
            body    = re.sub(r'\n{3,}', '\n\n', body)
            if body:
                lines.append(f"[{date_s}] {author}: {body}")

        transcript = "\n".join(lines)

        if lang == 'en':
            prompt = (
                f"Below are the chatter messages from the Odoo record "
                f"**{record_display}** ({model_name}).\n\n"
                f"Please write a concise summary: key decisions, status updates, "
                f"open action items, and any blockers. Use bullet points.\n\n"
                f"---\n{transcript}\n---"
            )
        else:
            prompt = (
                f"فيما يلي رسائل الشاتر من سجل Odoo "
                f"**{record_display}** ({model_name}).\n\n"
                f"اكتب ملخصاً موجزاً: القرارات الرئيسية، تحديثات الحالة، "
                f"البنود المفتوحة، وأي عوائق. استخدم نقاطاً.\n\n"
                f"---\n{transcript}\n---"
            )

        # ── Post header then ask Gemini to summarize ──────────────
        header = (
            f"{AGENT_PERSONA}: 📋 **Chatter summary — {record_display}**\n"
            f"_(fetched {len(messages)} message(s))_\n\n"
            if lang == 'en'
            else
            f"{AGENT_PERSONA}: 📋 **ملخص الشاتر — {record_display}**\n"
            f"_(تم جلب {len(messages)} رسالة)_\n\n"
        )

        # Use Gemini to produce the summary text
        try:
            api_key = request.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
            client  = genai.Client(api_key=api_key)
            summary_resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.3),
            )
            summary_text = self._extract_response_text(summary_resp)
        except Exception as e:
            _logger.warning(f"KH_AI v2.5 chatter summary Gemini call failed: {e}")
            summary_text = transcript[:3000]

        self._post_message(header + summary_text, mail_message_id)
        return {}
