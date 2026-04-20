# -*- coding: utf-8 -*-
"""
Language Detection — Single Source of Truth
============================================
Detects user's language from the LAST user message only.
Returns ISO-639-1 code ('ar' or 'en').
"""

import re
from typing import Literal

Lang = Literal['ar', 'en']

# Unicode range for Arabic
_ARABIC_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]')

# If >= 20% of letters are Arabic, treat message as Arabic
_ARABIC_THRESHOLD = 0.20
_MIN_MEANINGFUL_LEN = 4


def detect(text: str) -> Lang:
    """Detect language from a single plain-text message."""
    if not text or len(text.strip()) < _MIN_MEANINGFUL_LEN:
        return 'en'

    arabic_count = len(_ARABIC_RE.findall(text))
    letter_count = sum(1 for c in text if c.isalpha())

    if letter_count == 0:
        return 'en'

    return 'ar' if (arabic_count / letter_count) >= _ARABIC_THRESHOLD else 'en'


def detect_from_history(chat_history: str) -> Lang:
    """
    Detect language from conversation history.
    Uses ONLY the last user message — ignores assistant replies.
    """
    if not chat_history:
        return 'en'

    last_user_msg = ''
    for line in reversed(chat_history.splitlines()):
        stripped = line.strip()
        if stripped.startswith('User:'):
            last_user_msg = stripped[5:].strip()
            if last_user_msg:
                break

    return detect(last_user_msg or chat_history)


def odoo_locale(lang: Lang) -> str:
    """Map short code to Odoo locale (for with_context(lang=...))."""
    return {'ar': 'ar_001', 'en': 'en_US'}.get(lang, 'en_US')