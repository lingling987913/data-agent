"""Numeric token conservation checks for LLM rewrite safety."""

from __future__ import annotations

import re

_NUMERIC_RE = re.compile(r"-?\d+\.?\d*(?:[eE][+-]?\d+)?")


def extract_numeric_tokens(text: str) -> set[str]:
    """Extract all numeric tokens (sign, decimal, scientific notation)."""
    return set(_NUMERIC_RE.findall(text))


def check_numeric_conservation(before: str, after: str) -> bool:
    """Return True if after contains every numeric token from before."""
    before_nums = extract_numeric_tokens(before)
    after_nums = extract_numeric_tokens(after)
    return before_nums.issubset(after_nums)
