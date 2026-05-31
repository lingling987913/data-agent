"""Review-Plus artifact sync helpers for document_review phase."""

from __future__ import annotations

from typing import Any

from data_agent.parsing.artifact_builder import is_parse_artifact_complete
from data_agent.review_plus.artifact_adapter import (
    apply_parse_artifact_to_task,
    apply_structured_bundle_to_task,
)
from data_agent.super_agent.schemas import SuperAgentRun


def sync_wizard_parse_artifact_to_review_plus_task(svc: Any, task: Any, run: SuperAgentRun) -> bool:
    """Apply wizard Step 3 parse-only artifact to a Review-Plus task when available."""
    parse_preview = run.parse_preview if isinstance(run.parse_preview, dict) else {}
    parse_artifact = dict(parse_preview.get("parse_artifact") or run.structured_bundle.parse_artifact or {})
    if not is_parse_artifact_complete(parse_artifact):
        return False
    return apply_parse_artifact_to_task(svc, task, parse_artifact)


def sync_structured_bundle_to_review_plus_task(svc: Any, task: Any, run: SuperAgentRun) -> bool:
    """Apply the Super Agent artifact to Review-Plus through its adapter boundary."""
    from data_agent.parsing.artifact_builder import is_structure_artifact_complete

    bundle = run.structured_bundle
    if is_structure_artifact_complete(
        bundle.section_tree,
        bundle.evidence_pool,
        document_ir=bundle.document_ir,
        parse_artifact=bundle.parse_artifact,
    ):
        return apply_structured_bundle_to_task(svc, task, bundle)

    parse_artifact = dict(bundle.parse_artifact or {})
    if not parse_artifact and isinstance(run.parse_preview, dict):
        parse_artifact = dict(run.parse_preview.get("parse_artifact") or {})
    if is_parse_artifact_complete(parse_artifact):
        return apply_parse_artifact_to_task(svc, task, parse_artifact)
    return False


def ensure_review_plus_parsed(svc: Any, task: Any, run: SuperAgentRun) -> Any:
    """Align Review-Plus with Super Agent five-step semantics: classify → parse → review."""
    task = svc.get_review(task.review_plus_id) or task
    if is_parse_artifact_complete(getattr(task, "parse_artifact", {}) or {}):
        return task
    if sync_wizard_parse_artifact_to_review_plus_task(svc, task, run):
        return svc.get_review(task.review_plus_id) or task
    return svc.parse_materials(task.review_plus_id) or task
