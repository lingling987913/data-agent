"""Minimal rule source ref validation stub for template normalization."""

from __future__ import annotations

from typing import Any


def validate_rule_source_refs(source_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for ref in source_refs or []:
        if not isinstance(ref, dict):
            results.append({"valid": False, "errors": ["invalid_ref_type"]})
            continue
        errors: list[str] = []
        if not str(ref.get("source_id") or ref.get("source_title") or "").strip():
            errors.append("missing_source_identity")
        results.append({"valid": not errors, "errors": errors})
    return results
