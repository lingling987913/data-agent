"""Lightweight HTML tag stack scanner for table structure integrity."""

from __future__ import annotations

import re

from data_agent.agents.format_guard.schemas import FormatDamageType

_TABLE_TAG_RE = re.compile(r"</?(table|tr|td|th)\b[^>]*>", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)

_TAG_TO_DAMAGE: dict[str, FormatDamageType] = {
    "table": FormatDamageType.UNCLOSED_HTML_TABLE,
    "tr": FormatDamageType.UNCLOSED_HTML_TR,
    "td": FormatDamageType.UNCLOSED_HTML_TD,
    "th": FormatDamageType.UNCLOSED_HTML_TD,
}


def strip_code_fences(text: str) -> str:
    """Remove fenced code blocks so inner angle brackets are not scanned."""
    if not text:
        return ""
    return _CODE_FENCE_RE.sub("", text)


def scan_html_table_tags(text: str) -> list[FormatDamageType]:
    """Return damage types for unclosed table/tr/td/th tags in *text*."""
    cleaned = strip_code_fences(text)
    if not cleaned or "<" not in cleaned:
        return []

    stack: list[str] = []
    damages: list[FormatDamageType] = []

    for match in _TABLE_TAG_RE.finditer(cleaned):
        tag = match.group(1).lower()
        raw = match.group(0)
        is_close = raw.startswith("</")

        if is_close:
            if not stack:
                continue
            if stack[-1] == tag or (tag in {"td", "th"} and stack[-1] in {"td", "th"}):
                stack.pop()
            else:
                while stack and stack[-1] != tag:
                    unclosed = stack.pop()
                    damage = _TAG_TO_DAMAGE.get(unclosed)
                    if damage and damage not in damages:
                        damages.append(damage)
                if stack and stack[-1] == tag:
                    stack.pop()
                elif tag in {"td", "th"} and stack and stack[-1] in {"td", "th"}:
                    stack.pop()
        else:
            stack.append(tag)

    while stack:
        unclosed = stack.pop()
        damage = _TAG_TO_DAMAGE.get(unclosed)
        if damage and damage not in damages:
            damages.append(damage)

    return damages


def damage_snippet(text: str, *, max_len: int = 120) -> str:
    """Short excerpt around the first table tag for reporting."""
    cleaned = strip_code_fences(text)
    match = _TABLE_TAG_RE.search(cleaned)
    if not match:
        snippet = cleaned.strip()
    else:
        start = max(0, match.start() - 40)
        end = min(len(cleaned), match.end() + 80)
        snippet = cleaned[start:end].strip()
    snippet = re.sub(r"\s+", " ", snippet)
    if len(snippet) > max_len:
        return snippet[: max_len - 3] + "..."
    return snippet
