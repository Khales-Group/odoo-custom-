# -*- coding: utf-8 -*-
"""
i18n Engine — Self-Contained PO Loader
=======================================
Loads standard gettext .po files from `translations/` into in-memory dicts.

IMPORTANT: We use `translations/` (not `i18n/`) to avoid conflicts with
Odoo's native translation loader, which auto-imports `i18n/*.po` at module
install time.

Why not Odoo's native `_()`?
  1. `_()` uses frame inspection — fragile in HTTP controllers + Gemini callbacks.
  2. `_()` reads lang from user profile. We need lang from the CHAT MESSAGE.
  3. This gives O(1) dict lookups after a one-time parse.

Usage:
    from ..utils.i18n import translator
    t = translator('ar')
    t("Total")                               # → "الإجمالي"
    t("Found %(count)s records", count=5)    # → "تم العثور على 5 سجلات"
"""

import os
import re
import logging
from functools import lru_cache
from typing import Dict

from .lang import Lang

_logger = logging.getLogger(__name__)

# translations/ directory (sibling of utils/, at module root)
_TRANSLATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'translations',
)
_PO_LINE_RE = re.compile(r'^(msgid|msgstr)\s+"(.*)"\s*$')


@lru_cache(maxsize=4)
def _load_po(lang: Lang) -> Dict[str, str]:
    """Parse translations/<lang>.po into {msgid: msgstr}. Cached per process."""
    path = os.path.join(_TRANSLATIONS_DIR, f'{lang}.po')
    if not os.path.isfile(path):
        _logger.warning("kh_ai_backport.i18n: %s not found — returning empty map", path)
        return {}

    translations: Dict[str, str] = {}
    current_id: str = ''
    current_str: str = ''

    def _flush():
        if current_id and current_str:
            translations[current_id] = current_str

    try:
        with open(path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                m = _PO_LINE_RE.match(line)
                if not m:
                    continue
                key, val = m.group(1), m.group(2)
                val = val.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
                if key == 'msgid':
                    _flush()
                    current_id, current_str = val, ''
                elif key == 'msgstr':
                    current_str = val
        _flush()
    except Exception:
        _logger.exception("kh_ai_backport.i18n: failed to parse %s", path)
        return {}

    _logger.info("kh_ai_backport.i18n: loaded %d translations for '%s'", len(translations), lang)
    return translations


class Translator:
    """Language-bound translator. Cheap to instantiate (dict ref only)."""

    __slots__ = ('lang', '_dict')

    def __init__(self, lang: Lang):
        self.lang = lang
        # English is the source language — no lookup needed
        self._dict = {} if lang == 'en' else _load_po(lang)

    def __call__(self, source: str, **kwargs) -> str:
        """Translate + interpolate. Always safe: missing key → return source."""
        text = self._dict.get(source, source)
        if kwargs:
            try:
                return text % kwargs
            except (KeyError, TypeError, ValueError):
                return text
        return text


def translator(lang: Lang) -> Translator:
    """Factory: build a translator bound to `lang`."""
    return Translator(lang)