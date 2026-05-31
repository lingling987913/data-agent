"""LaTeX delimiter validation for inline ($) and block ($$) math."""

from __future__ import annotations

import re

from data_agent.agents.format_guard.schemas import FormatDamageType
from data_agent.agents.format_guard.html_ast import strip_code_fences

_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _strip_inline_code(text: str) -> str:
    return _INLINE_CODE_RE.sub("", text)


def _mask_block_delimiters(text: str) -> tuple[str, int]:
    """Replace $$ pairs with spaces; return masked text and block delimiter count."""
    count = 0
    i = 0
    chars = list(text)
    n = len(chars)

    while i < n:
        if i + 1 < n and chars[i] == "$" and chars[i + 1] == "$" and (i == 0 or chars[i - 1] != "\\"):
            count += 1
            chars[i] = " "
            chars[i + 1] = " "
            i += 2
            continue
        i += 1

    return "".join(chars), count


def _count_unescaped_inline_dollars(text: str) -> int:
    """Count single $ delimiters not part of $$ and not escaped as \\$."""
    count = 0
    i = 0
    n = len(text)

    while i < n:
        if text[i] == "$" and (i == 0 or text[i - 1] != "\\"):
            if i + 1 < n and text[i + 1] == "$":
                i += 2
                continue
            count += 1
            i += 1
            continue
        i += 1

    return count


def scan_latex_delimiters(text: str) -> list[FormatDamageType]:
    """Detect odd inline $ or unpaired $$ in *text* (outside code fences)."""
    if not text or "$" not in text:
        return []

    cleaned = strip_code_fences(text)
    cleaned = _strip_inline_code(cleaned)
    if "$" not in cleaned:
        return []

    damages: list[FormatDamageType] = []
    masked, block_count = _mask_block_delimiters(cleaned)

    if block_count % 2 == 1:
        damages.append(FormatDamageType.ODD_BLOCK_LATEX)

    inline_count = _count_unescaped_inline_dollars(masked)
    if inline_count % 2 == 1:
        damages.append(FormatDamageType.ODD_INLINE_LATEX)

    return damages


def latex_damage_snippet(text: str, *, max_len: int = 120) -> str:
    cleaned = strip_code_fences(text)
    idx = cleaned.find("$")
    if idx < 0:
        snippet = cleaned.strip()
    else:
        start = max(0, idx - 40)
        end = min(len(cleaned), idx + 80)
        snippet = cleaned[start:end].strip()
    snippet = re.sub(r"\s+", " ", snippet)
    if len(snippet) > max_len:
        return snippet[: max_len - 3] + "..."
    return snippet
