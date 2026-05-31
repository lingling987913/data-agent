"""Build typed P0 traceability result from Review-Plus task."""

from __future__ import annotations

from data_agent.review.traceability_p0_service import build_traceability_result
from data_agent.review_plus.p0_task_adapter import to_legacy_review_task
from data_agent.review_plus.schemas import ReviewPlusTask


def build_review_plus_traceability_result(task: ReviewPlusTask) -> dict:
    """Primary typed traceability path; returns JSON-serializable dict."""
    legacy_task = to_legacy_review_task(task)
    result = build_traceability_result(legacy_task)
    payload = result.model_dump(mode="json")
    payload["ruleset_version"] = payload.get("summary", {}).get("ruleset_version", "traceability-p0-2026-05-14")
    return payload
