"""Minimal evidence pool helpers for unit review (source-compatible subset)."""

from __future__ import annotations

from typing import Any

from data_agent.review.p0_schemas import UnitEvidenceBundle


def build_unit_primary_evidences(
    *,
    unit_key: str,
    matched_section_ids: list[str],
    evidence_pool: Any,
) -> list[dict[str, Any]]:
    del unit_key
    evidences: list[dict[str, Any]] = []
    pool = evidence_pool
    if isinstance(pool, dict):
        items = pool.get("evidences") or pool.get("items") or []
    elif hasattr(pool, "evidences"):
        items = getattr(pool, "evidences") or []
    else:
        items = pool or []
    matched = set(matched_section_ids or [])
    for item in items:
        if not isinstance(item, dict) and hasattr(item, "model_dump"):
            item = item.model_dump(mode="json")
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("section_id") or "")
        if matched and section_id not in matched:
            continue
        evidences.append(dict(item))
    return evidences


def merge_supporting_evidences(
    *,
    unit_key: str,
    primary_evidences: list[dict[str, Any]],
    supporting_evidences: list[dict[str, Any]],
    gatekeeping_status: str,
    warnings: list[str],
) -> UnitEvidenceBundle:
    return UnitEvidenceBundle(
        unit_key=unit_key,
        primary_evidences=list(primary_evidences or []),
        supporting_evidences=list(supporting_evidences or []),
        gatekeeping_status=gatekeeping_status or "pass",
        warnings=list(warnings or []),
    )
