"""Project Review-Plus tasks into unified workbench read models."""

from __future__ import annotations

from typing import Any

from data_agent.review_plus.schemas import ReviewPlusStatus, ReviewPlusTask
from data_agent.review_workbench.mappers import (
    REVIEW_PLUS_PIPELINE_STEPS,
    map_review_plus_status_to_phase,
    resolve_review_plus_visible_tabs,
)
from data_agent.review_workbench.issue_taxonomy import build_conclusion_payload, compute_workbench_issue_summary
from data_agent.review_workbench.schemas import (
    ReviewType,
    UnifiedReviewWorkbenchDetail,
    WorkbenchConclusionOverview,
    WorkbenchMetrics,
    WorkbenchSummary,
)


def _review_plus_completed_steps(task: ReviewPlusTask) -> set[str]:
    event_types = {str(event.get("type", "")) for event in (task.events or []) if isinstance(event, dict)}
    return {step for step in REVIEW_PLUS_PIPELINE_STEPS if f"{step}_completed" in event_types}


def _has_coverage_artifacts(task: ReviewPlusTask) -> bool:
    matrix = task.coverage_matrix or {}
    return bool(matrix) and (
        bool(matrix.get("rows"))
        or bool(matrix.get("items"))
        or bool(matrix.get("coverage_rows"))
    )


def build_workbench_metrics(task: ReviewPlusTask) -> WorkbenchMetrics:
    cross_items = list(task.cross_document_review_items or [])
    report = task.report
    check_item_count = int(report.total_check_items if report else len(task.check_items or []))
    issue_stats = compute_workbench_issue_summary(
        _finding_dicts(task),
        review_mode="review_plus",
        cross_doc_items=cross_items,
        total_check_items=check_item_count,
        open_rid_count=0,
    )
    evidence_pool = task.evidence_pool or {}
    evidences = evidence_pool.get("items") or evidence_pool.get("evidences") or []
    return WorkbenchMetrics(
        finding_count=issue_stats["problem_count"],
        problem_count=issue_stats["problem_count"],
        check_item_count=issue_stats["check_item_count"],
        pending_confirm=issue_stats["pending_confirm"],
        rid_count=0,
        open_rid_count=0,
        evidence_count=len(evidences) if isinstance(evidences, list) else 0,
        conflict_count=len(
            [item for item in cross_items if str(item.get("status", "")).lower() in {"conflict", "open"}]
        ),
        requires_arbitration=False,
    )


def build_workbench_summary(task: ReviewPlusTask) -> WorkbenchSummary:
    report = task.report
    verdict = ""
    rationale = ""
    if report:
        verdict = str(report.conclusion or report.summary or "")
        rationale = str(report.summary or "")
    chief = (report.chief_comprehensive_review if report else None) or None
    if chief and getattr(chief, "release_recommendation", ""):
        verdict = str(chief.release_recommendation or verdict)
        rationale = str(chief.rationale or rationale)
    return WorkbenchSummary(
        verdict=verdict,
        rationale=rationale,
        report_available=bool((task.report_markdown or "").strip() or (report and report.markdown)),
    )


def _finding_dicts(task: ReviewPlusTask) -> list[dict[str, Any]]:
    return [finding.model_dump(mode="json") for finding in (task.findings or [])]


def _build_conclusion_overview(task: ReviewPlusTask) -> WorkbenchConclusionOverview:
    report = task.report
    summary = build_workbench_summary(task)
    gate = task.gatekeeping_result or {}
    materials = [material.model_dump(mode="json") for material in (task.materials or [])]
    payload = build_conclusion_payload(
        review_mode="review_plus",
        verdict=summary.verdict,
        rationale=summary.rationale,
        findings=_finding_dicts(task),
        cross_doc_items=list(task.cross_document_review_items or []),
        materials=materials,
        explicit_scope=str(task.scenario_reason or ""),
        scenario=str(task.scenario_reason or ""),
        total_check_items=int(report.total_check_items if report else len(task.check_items or [])),
        evidence_count=build_workbench_metrics(task).evidence_count,
        limited_scope=list(gate.get("limited_scope") or []),
    )
    return WorkbenchConclusionOverview(
        headline_verdict=payload["headline_verdict"],
        one_line_conclusion=payload["one_line_conclusion"],
        verdict_label_zh=str(payload.get("verdict_label_zh") or ""),
        rationale_zh=str(payload.get("rationale_zh") or ""),
        issue_buckets=payload["issue_buckets"],
        bucket_labels=payload["bucket_labels"],
        review_scope=payload["review_scope"],
        priority_items=payload["priority_items"],
        coverage_summary=payload["coverage_summary"],
    )


def build_workbench_detail(task: ReviewPlusTask) -> UnifiedReviewWorkbenchDetail:
    events = list(task.events or [])
    completed_steps = _review_plus_completed_steps(task)
    summary = build_workbench_summary(task)
    conclusion = _build_conclusion_overview(task)
    summary.headline_verdict = conclusion.headline_verdict
    summary.one_line_conclusion = conclusion.one_line_conclusion
    summary.review_mode_label = conclusion.review_scope.get("review_mode_label", "")
    summary.verdict_label_zh = conclusion.verdict_label_zh or summary.verdict_label_zh
    summary.rationale_zh = conclusion.rationale_zh or summary.rationale_zh
    return UnifiedReviewWorkbenchDetail(
        review_id=task.review_plus_id,
        name=task.name,
        review_type=ReviewType.REVIEW_PLUS,
        status=str(task.status or ""),
        workbench_phase=map_review_plus_status_to_phase(
            task.status,
            events=events,
            completed_steps=completed_steps,
        ),
        visible_tabs=resolve_review_plus_visible_tabs(
            status=task.status,
            events=events,
            completed_steps=completed_steps,
            has_coverage_artifacts=_has_coverage_artifacts(task),
        ),
        current_step=_infer_current_step(task, completed_steps),
        metrics=build_workbench_metrics(task),
        summary=summary,
        conclusion_overview=conclusion,
        error=_latest_failure_message(events),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _infer_current_step(task: ReviewPlusTask, completed_steps: set[str]) -> str:
    for step in reversed(REVIEW_PLUS_PIPELINE_STEPS):
        if step in completed_steps:
            return step
    status = str(task.status or "").lower()
    status_to_step = {
        ReviewPlusStatus.PARSING.value: "document_structuring",
        ReviewPlusStatus.STRUCTURING.value: "document_structuring",
        ReviewPlusStatus.RULE_EXTRACTING.value: "rule_extraction",
        ReviewPlusStatus.MAPPING.value: "rule_section_mapping",
        ReviewPlusStatus.REVIEWING.value: "item_review",
        ReviewPlusStatus.TRACEABILITY_BUILDING.value: "traceability",
        ReviewPlusStatus.REPORTING.value: "report_composition",
    }
    return status_to_step.get(status, "")


def _latest_failure_message(events: list[dict[str, Any]]) -> str:
    failures = [
        event
        for event in events
        if isinstance(event, dict) and str(event.get("type", "")) == "workflow_failed"
    ]
    if not failures:
        return ""
    payload = failures[-1].get("payload") or {}
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("error_message") or payload.get("error") or payload.get("message") or "")


def project_flow(task: ReviewPlusTask) -> dict[str, Any]:
    completed = _review_plus_completed_steps(task)
    steps = []
    for step_key in REVIEW_PLUS_PIPELINE_STEPS:
        steps.append(
            {
                "step_key": step_key,
                "status": "completed" if step_key in completed else "pending",
                "completed": step_key in completed,
            }
        )
    return {
        "review_id": task.review_plus_id,
        "status": task.status,
        "current_step": _infer_current_step(task, completed),
        "steps": steps,
    }


def project_materials(task: ReviewPlusTask) -> list[dict[str, Any]]:
    return [material.model_dump(mode="json") for material in (task.materials or [])]


def project_gatekeeping(task: ReviewPlusTask) -> dict[str, Any]:
    return dict(task.gatekeeping_result or {})


def project_findings(task: ReviewPlusTask) -> list[dict[str, Any]]:
    from data_agent.review_workbench.issue_taxonomy import (
        BUSINESS_BUCKET_LABELS,
        classify_finding,
        infer_evidence_gap_reason,
    )

    enriched: list[dict[str, Any]] = []
    for finding in task.findings or []:
        payload = finding.model_dump(mode="json")
        bucket, _ = classify_finding(payload, review_mode="review_plus")
        gap = infer_evidence_gap_reason(payload) if bucket == "insufficient_evidence" else ""
        enriched.append(
            {
                **payload,
                "business_bucket": bucket,
                "business_bucket_label": BUSINESS_BUCKET_LABELS[bucket],
                "missing_reason": gap,
                "evidence_gap_reason": gap,
            }
        )
    return enriched


def project_decision(task: ReviewPlusTask) -> dict[str, Any]:
    summary = build_workbench_summary(task)
    gate = task.gatekeeping_result or {}
    materials = [material.model_dump(mode="json") for material in (task.materials or [])]
    report = task.report
    payload = build_conclusion_payload(
        review_mode="review_plus",
        verdict=summary.verdict,
        rationale=summary.rationale,
        findings=_finding_dicts(task),
        cross_doc_items=list(task.cross_document_review_items or []),
        materials=materials,
        explicit_scope=str(task.scenario_reason or ""),
        scenario=str(task.scenario_reason or ""),
        total_check_items=int(report.total_check_items if report else len(task.check_items or [])),
        evidence_count=build_workbench_metrics(task).evidence_count,
        limited_scope=list(gate.get("limited_scope") or []),
    )
    chief = (report.chief_comprehensive_review.model_dump(mode="json") if report and report.chief_comprehensive_review else {})
    return {
        **payload,
        "chief_comprehensive_review": chief,
        "report_conclusion": str(report.conclusion if report else ""),
        "report_summary": str(report.summary if report else ""),
    }


def project_check_items(task: ReviewPlusTask) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in (task.check_items or [])]


def project_traceability(task: ReviewPlusTask) -> dict[str, Any] | None:
    return task.traceability_result or None


def project_cross_document(task: ReviewPlusTask) -> list[dict[str, Any]]:
    return list(task.cross_document_review_items or [])


def project_coverage(task: ReviewPlusTask) -> dict[str, Any]:
    return dict(task.coverage_matrix or {})


def project_report(task: ReviewPlusTask) -> dict[str, Any] | None:
    from data_agent.review_plus.report_service import build_review_plus_markdown

    markdown = build_review_plus_markdown(task)
    if not markdown.strip():
        if not task.report:
            return None
        return task.report.model_dump(mode="json")
    payload = task.report.model_dump(mode="json") if task.report else {}
    payload["markdown"] = markdown
    return payload


def project_events(task: ReviewPlusTask) -> list[dict[str, Any]]:
    return list(task.events or [])


def project_flow_materials_gatekeeping_bundle(task: ReviewPlusTask) -> dict[str, Any]:
    return {
        "flow": project_flow(task),
        "materials": project_materials(task),
        "gatekeeping": project_gatekeeping(task),
    }
