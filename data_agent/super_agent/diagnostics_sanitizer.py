"""Generic separation of internal execution telemetry from business-facing conclusions."""

from __future__ import annotations

import re
from collections.abc import Iterable

_INTERNAL_TELEMETRY_KEYS = (
    "execution_mode_summary",
    "scheduler_summary",
    "task_board_summary",
    "fallback_reason",
    "harness_count",
    "generic_llm_harness_count",
    "deterministic_count",
    "blocked_count",
    "failed_count",
)

_TELEMETRY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bexecution_mode_summary\s*[=:]\s*[\{\[]", re.I),
    re.compile(r"\bscheduler_summary\s*[=:]\s*[\{\[]", re.I),
    re.compile(r"\btask_board_summary\s*[=:]\s*[\{\[]", re.I),
    re.compile(r"\bfallback_reason\s*=", re.I),
    re.compile(r"\b\w+_summary\s*=\s*[\{\[]"),
    re.compile(r"\bexecution_mode\s*=\s*[\{]", re.I),
    re.compile(r"\bexecution_mode\s*=\s*deterministic", re.I),
    re.compile(r"\blimited\s*=\s*(true|false)", re.I),
    re.compile(r"\bbootstrap_mode\s*=", re.I),
    re.compile(r"\bgate_limited:", re.I),
    re.compile(
        r"\b(harness_count|generic_llm_harness_count|deterministic_count|blocked_count|failed_count)\s*[=:]\s*\d",
        re.I,
    ),
    re.compile(
        r"['\"](harness_count|generic_llm_harness_count|deterministic_count|blocked_count|failed_count)['\"]\s*:\s*\d",
        re.I,
    ),
    re.compile(r"\btraceability_summary\s*=", re.I),
    re.compile(r"\bdeterministic_items\s*=", re.I),
)

_DICT_TELEMETRY_INNER = re.compile(
    r"[\{\[][^}\]]*"
    r"(harness_count|generic_llm_harness_count|deterministic_count|blocked_count|failed_count|execution_mode)"
    r"[^}\]]*[\}\]]",
    re.I,
)

_KEY_VALUE_DICT_LINE = re.compile(
    r"^[\w.\s/-]+=\{.*\}$",
)


def _cjk_char_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def is_internal_diagnostic_text(text: str) -> bool:
    """Return True when *text* is execution telemetry rather than a business conclusion."""
    normalized = str(text or "").strip()
    if not normalized:
        return False

    for pattern in _TELEMETRY_PATTERNS:
        if pattern.search(normalized):
            return True

    if _DICT_TELEMETRY_INNER.search(normalized):
        return True

    if _KEY_VALUE_DICT_LINE.match(normalized):
        inner = normalized.split("=", 1)[1]
        if any(key in inner for key in _INTERNAL_TELEMETRY_KEYS):
            return True

    lowered = normalized.lower()
    if lowered.startswith("smart committee limited:") and "{" in normalized:
        return True

    # Mostly Chinese prose without inline dict/json payloads — treat as business text.
    if _cjk_char_count(normalized) >= max(4, len(normalized) // 3):
        if not re.search(r"[\{\[]", normalized):
            return False
        if not any(key in normalized for key in _INTERNAL_TELEMETRY_KEYS):
            return False

    return False


def sanitize_business_lines(lines: Iterable[str]) -> list[str]:
    """Drop internal telemetry lines while preserving order and deduplicating."""
    seen: set[str] = set()
    filtered: list[str] = []
    for item in lines:
        text = str(item or "").strip()
        if not text or is_internal_diagnostic_text(text):
            continue
        if text in seen:
            continue
        seen.add(text)
        filtered.append(text)
    return filtered


def sanitize_report_markdown(markdown: str) -> str:
    """Remove internal diagnostic bullet/paragraph lines from report markdown."""
    if not markdown:
        return ""
    kept: list[str] = []
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("- "):
            content = stripped[2:].strip()
            if is_internal_diagnostic_text(content):
                continue
        elif stripped.startswith("* "):
            content = stripped[2:].strip()
            if is_internal_diagnostic_text(content):
                continue
        elif is_internal_diagnostic_text(line.strip()):
            continue
        kept.append(line)
    return "\n".join(kept)


# User-facing aliases
sanitize_smart_diagnostic_text = sanitize_report_markdown
sanitize_business_report_text = sanitize_report_markdown

__all__ = [
    "is_internal_diagnostic_text",
    "sanitize_business_lines",
    "sanitize_business_report_text",
    "sanitize_report_markdown",
    "sanitize_smart_diagnostic_text",
]
