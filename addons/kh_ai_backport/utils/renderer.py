# -*- coding: utf-8 -*-
"""
Report Renderer
===============
Builds markdown tables with auto-translated headers.
"""

from typing import Callable, Iterable, Sequence, Mapping, Any

Formatter = Callable[[Any], str]


def _default_format(val: Any) -> str:
    """Format a cell value. Numbers get thousand separators."""
    if val is None:
        return '-'
    if isinstance(val, float):
        if val.is_integer():
            return f"{int(val):,}"
        return f"{val:,.2f}"
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def render_table(
    translator,
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[str],
    formatters: Mapping[str, Formatter] = None,
) -> str:
    """
    Build a markdown table with translated headers.

    Args:
        translator: Translator callable (from i18n.translator()).
        rows: Iterable of dicts keyed by English column name.
        columns: Ordered list of English column keys.
        formatters: Optional {column: fn} for custom formatting.

    Returns:
        Markdown table string.
    """
    formatters = formatters or {}
    header = '| ' + ' | '.join(translator(c) for c in columns) + ' |'
    sep = '|' + '|'.join('---' for _ in columns) + '|'
    lines = [header, sep]

    for row in rows:
        cells = []
        for col in columns:
            fmt = formatters.get(col, _default_format)
            cells.append(fmt(row.get(col)))
        lines.append('| ' + ' | '.join(cells) + ' |')

    return '\n'.join(lines)


def render_kv_block(translator, items: Sequence[tuple]) -> str:
    """Render a key-value block. `items` is [(english_label, value), ...]."""
    return '\n'.join(
        f"  • {translator(label)}: **{_default_format(value)}**"
        for label, value in items
    )


def margin_icon(percentage: float) -> str:
    """Traffic-light icon for profit margin percentage."""
    if percentage >= 20:
        return '🟢'
    if percentage >= 10:
        return '🟡'
    return '🔴'