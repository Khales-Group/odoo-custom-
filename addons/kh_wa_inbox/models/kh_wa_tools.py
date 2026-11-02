"""Helpers shared by the notebook models: masking, reading the bot's rows,
Dubai dates, Arabic age labels and the row-by-row runner of the XML-RPC API.

No Odoo imports here, so the masking and parsing rules can be read (and
tested) on their own.
"""
import logging
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_logger = logging.getLogger(__name__)

try:
    DUBAI = ZoneInfo("Asia/Dubai")
except ZoneInfoNotFoundError:  # no tz database on the machine; Dubai has no DST
    DUBAI = timezone(timedelta(hours=4), "Asia/Dubai")
DOTS = "••••"

# ---------------------------------------------------------------------------
# Masking one-time passwords and card numbers
# ---------------------------------------------------------------------------

# A line mentioning any of these is treated as an OTP message: every short
# stand-alone number on it (4-8 digits) is hidden. Over-masking a project
# code now and then is the price for never keeping a live OTP.
_OTP_LINE = re.compile(
    r"\bOTP\b|one[\s-]?time|verification|passcode|\bpin\b|\bcode\b|"
    r"رمز|كود|كلمة\s*(?:المرور|السر)|التحقق",
    re.IGNORECASE,
)
# 4-8 digits that aren't part of an amount, a date, a time or a longer number.
_OTP_NUMBER = re.compile(r"(?<![\d.,:/\-])\d{4,8}(?![\d]|[.,:/\-]\d)")
# Cards: 4-4-4-4 (same separator throughout), Amex 4-6-5, or 13-19 digits
# written in one piece. Phone numbers split in threes never match, and
# neither does the middle of an IBAN (a group right after another group).
_CARD_NUMBER = re.compile(
    r"(?<!\d)(?<!\d[ \-])"
    r"(?:\d{4}([ \-]?)\d{4}\1\d{4}\1\d{4}|\d{4}[ \-]\d{6}[ \-]\d{5}|\d{13,19})(?!\d)"
)


def _luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _mask_card(match):
    digits = re.sub(r"\D", "", match.group(0))
    # 16 digits is always a card; other lengths only when the check digit fits.
    if len(digits) == 16 or _luhn_ok(digits.translate(_ARABIC_DIGITS)):
        return f"{DOTS} {digits[-4:]}"
    return match.group(0)


def mask_text(text):
    """'OTP 482913' -> 'OTP ••••'; a 16-digit card -> '•••• 1234'."""
    if not text or not isinstance(text, str):
        return text
    text = _CARD_NUMBER.sub(_mask_card, text)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _OTP_LINE.search(line):
            lines[i] = _OTP_NUMBER.sub(DOTS, line)
    return "\n".join(lines)


def mask_vals(vals, field_names):
    for name in field_names:
        if vals.get(name):
            vals[name] = mask_text(vals[name])
    return vals


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_phone(raw):
    """+971 50 123 4567, 00971501234567, 0501234567 and
    971501234567@s.whatsapp.net all become '501234567'."""
    text = str(raw or "").split("@")[0].translate(_ARABIC_DIGITS)
    digits = re.sub(r"[^0-9]", "", text)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("971"):
        digits = digits[3:]
    digits = digits.lstrip("0")
    return digits if len(digits) >= 7 else ""


def phone_index(pairs):
    """{normalized phone: {user ids}} from (phone, user_id) pairs."""
    index = defaultdict(set)
    for phone, user_id in pairs:
        key = normalize_phone(phone)
        if key and user_id:
            index[key].add(user_id)
    return index


# ---------------------------------------------------------------------------
# Dates (stored in UTC, the notebook lives in Dubai)
# ---------------------------------------------------------------------------


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def dubai_today():
    return datetime.now(DUBAI).date()


def dubai_date(utc_naive):
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(DUBAI).date()


def dubai_day_bounds(day):
    """The UTC [start, end) of a calendar day in Dubai."""
    start = datetime.combine(day, time.min, DUBAI).astimezone(timezone.utc).replace(tzinfo=None)
    return start, start + timedelta(days=1)


def parse_utc_datetime(value):
    """'2026-11-02 06:45:00' (UTC), ISO 8601 with Z or an offset, or epoch
    seconds/milliseconds -> naive UTC datetime. Empty -> False."""
    if value in (None, False, ""):
        return False
    if isinstance(value, bool):
        raise ValueError(f"not a date-time: {value!r}")
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, timezone.utc).replace(tzinfo=None, microsecond=0)
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def parse_date(value):
    if value in (None, False, ""):
        return False
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


# ---------------------------------------------------------------------------
# "منذ 3 أيام"
# ---------------------------------------------------------------------------


def _ar_count(n, one, two, few, many):
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n % 100 <= 10:
        return f"{n} {few}"
    return f"{n} {many}"


def arabic_age(then, now=None):
    if not then:
        return ""
    minutes = int(((now or utc_now()) - then).total_seconds() // 60)
    if minutes < 1:
        return "الآن"
    if minutes < 60:
        return "منذ " + _ar_count(minutes, "دقيقة", "دقيقتين", "دقائق", "دقيقة")
    hours = minutes // 60
    if hours < 24:
        return "منذ " + _ar_count(hours, "ساعة", "ساعتين", "ساعات", "ساعة")
    days = hours // 24
    if days < 30:
        return "منذ " + _ar_count(days, "يوم", "يومين", "أيام", "يوماً")
    if days < 365:
        return "منذ " + _ar_count(min(days // 30, 11), "شهر", "شهرين", "أشهر", "شهراً")
    return "منذ " + _ar_count(days // 365, "سنة", "سنتين", "سنوات", "سنة")


# ---------------------------------------------------------------------------
# XML-RPC batches
# ---------------------------------------------------------------------------


def run_batch(model, rows, key_of, handler):
    """Calls handler(row, warnings) for each row in its own savepoint.

    A bad row is logged, skipped and reported; the rest of the batch goes on.
    Returns {"ids": [...], "errors": [...]}, where each error is
    {"index", "key", "error", "saved"}: saved=True is only a warning about a
    row that was stored anyway (e.g. an unknown assignee login).
    Never None in the result: Odoo's XML-RPC can't send it.
    """
    ids, errors = [], []
    if not isinstance(rows, (list, tuple)):
        return {"ids": ids, "errors": [{"index": False, "key": False, "error": "rows must be a list", "saved": False}]}
    for index, row in enumerate(rows):
        key = (key_of(row) if isinstance(row, dict) else False) or False
        warnings = []
        try:
            if not isinstance(row, dict):
                raise ValueError("each row must be an object")
            with model.env.cr.savepoint():
                record_id = handler(row, warnings)
        except Exception as e:  # noqa: BLE001 - one bad row must not sink the batch
            _logger.warning("%s: row %s (%s) skipped: %s", model._name, index, key, e)
            errors.append({"index": index, "key": key, "error": str(e) or type(e).__name__, "saved": False})
            continue
        if record_id:
            ids.append(record_id)
        for warning in warnings:
            _logger.info("%s: row %s (%s): %s", model._name, index, key, warning)
            errors.append({"index": index, "key": key, "error": warning, "saved": True})
    return {"ids": ids, "errors": errors}
