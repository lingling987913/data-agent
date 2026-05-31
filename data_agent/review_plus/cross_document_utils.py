"""Shared cross-document version/baseline checks for Review-Plus."""

from __future__ import annotations

import re
from typing import Any

VERSION_RE = re.compile(r"\b(?:V|v|版本\s*)(\d+(?:\.\d+){0,3})\b")
BASELINE_RE = re.compile(r"\b(?:BL|BASELINE)-[A-Z0-9_-]+\b", re.IGNORECASE)


def formal_material_version_values(task: Any) -> set[str]:
    return {
        str(getattr(material, "document_version", "") or "").strip()
        for material in getattr(task, "materials", []) or []
        if getattr(material, "included_in_formal_review", True)
        and str(getattr(material, "document_version", "") or "").strip()
    }


def formal_material_baseline_values(task: Any) -> set[str]:
    return {
        str(getattr(material, "baseline_id", "") or "").strip()
        for material in getattr(task, "materials", []) or []
        if getattr(material, "included_in_formal_review", True)
        and str(getattr(material, "baseline_id", "") or "").strip()
    }


def material_version_baseline_meta(task: Any) -> list[dict[str, str]]:
    """Collect version/baseline metadata, including regex fallbacks from content."""
    material_meta: list[dict[str, str]] = []
    for material in getattr(task, "materials", []) or []:
        content = getattr(material, "content", "") or ""
        version_match = VERSION_RE.search(content)
        baseline_match = BASELINE_RE.search(content)
        material_meta.append({
            "name": getattr(material, "name", ""),
            "version": (
                getattr(material, "document_version", "") or ""
            ).strip() or (version_match.group(1) if version_match else ""),
            "baseline": (
                getattr(material, "baseline_id", "") or ""
            ).strip() or (baseline_match.group(0) if baseline_match else ""),
        })
    return material_meta


def version_baseline_mismatch_summaries(task: Any) -> tuple[set[str], set[str]]:
    """Return distinct version and baseline values across formal materials."""
    meta = material_version_baseline_meta(task)
    versions = {item["version"] for item in meta if item["version"]}
    baselines = {item["baseline"] for item in meta if item["baseline"]}
    if not versions:
        versions = formal_material_version_values(task)
    if not baselines:
        baselines = formal_material_baseline_values(task)
    return versions, baselines
