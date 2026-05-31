"""Project Super Agent native runs into unified workbench models."""

from __future__ import annotations

from typing import Any

from data_agent.super_agent.schemas import SuperAgentRun, SuperAgentStatus
from data_agent.review_workbench.issue_taxonomy import (
    BUSINESS_BUCKET_LABELS,
    build_conclusion_payload,
    classify_finding,
    compute_workbench_issue_summary,
    dedupe_findings,
    derive_rationale_zh,
    infer_evidence_gap_reason,
    resolve_agent_display_name,
    resolve_check_item_title,
    resolve_evidence_status_label_zh,
    resolve_judgment_label_zh,
    resolve_verdict_label_zh,
)
from data_agent.review_workbench.schemas import (
    ReviewType,
    UnifiedReviewWorkbenchDetail,
    WorkbenchConclusionOverview,
    WorkbenchMetrics,
    WorkbenchPhase,
    WorkbenchSummary,
    WorkbenchTab,
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _smart_result(run: SuperAgentRun) -> dict[str, Any]:
    result = _as_dict(run.review_plus_result)
    if result:
        return result
    doc_review = _as_dict(run.phase_artifacts.get("document_review"))
    return _as_dict(doc_review.get("smart_committee_result"))


def _gnc_result(run: SuperAgentRun) -> dict[str, Any]:
    return _as_dict(run.gnc_review_result)


def _smart_primary_path(run: SuperAgentRun) -> str:
    classification = _as_dict(run.classification)
    smart_plan = _as_dict(classification.get("smart_review_plan"))
    return str(smart_plan.get("primary_path") or "").strip().lower()


def _prefer_gnc_result(run: SuperAgentRun) -> bool:
    gnc = _gnc_result(run)
    if not gnc:
        return False
    if _smart_primary_path(run) == "gnc":
        return True
    return bool(gnc.get("findings") or gnc.get("chief_decision") or gnc.get("editorial_synthesis"))


def _active_result(run: SuperAgentRun) -> dict[str, Any]:
    return _gnc_result(run) if _prefer_gnc_result(run) else _smart_result(run)


def _flatten_findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    direct = [item for item in _as_list(result.get("findings")) if isinstance(item, dict)]
    if direct:
        return direct
    findings: list[dict[str, Any]] = []
    for review_index, review in enumerate(_as_list(result.get("specialist_reviews")), start=1):
        if not isinstance(review, dict):
            continue
        agent_id = str(review.get("agent_id") or review.get("specialist_id") or f"agent-{review_index}")
        for finding_index, finding in enumerate(_as_list(review.get("findings")), start=1):
            if not isinstance(finding, dict):
                continue
            finding_id = str(
                finding.get("finding_id")
                or finding.get("id")
                or f"{agent_id}-F{finding_index}"
            )
            findings.append(
                {
                    **finding,
                    "finding_id": finding_id,
                    "agent_id": agent_id,
                    "source": finding.get("source") or agent_id,
                }
            )
    return findings


def _review_mode(run: SuperAgentRun) -> str:
    return "gnc" if _prefer_gnc_result(run) else "super_agent"


def _finding_bucket(finding: dict[str, Any], *, review_mode: str = "super_agent") -> str:
    bucket, _ = classify_finding(finding, review_mode=review_mode)  # type: ignore[arg-type]
    return bucket


def _finding_bucket_label(bucket: str) -> str:
    return BUSINESS_BUCKET_LABELS.get(bucket, bucket)


def _issue_summary(findings: list[dict[str, Any]], rid_items: list[dict[str, Any]] | None = None, *, review_mode: str = "super_agent") -> dict[str, Any]:
    buckets: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for finding in findings:
        bucket = _finding_bucket(finding, review_mode=review_mode)
        buckets[bucket] = buckets.get(bucket, 0) + 1
        severity = str(finding.get("severity") or "unknown").strip().lower() or "unknown"
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    open_rids = [
        item for item in (rid_items or [])
        if str(item.get("status") or "").strip().lower() in {"open", "pending", ""}
    ]
    return {
        "buckets": buckets,
        "bucket_labels": {key: _finding_bucket_label(key) for key in buckets},
        "severity_counts": severity_counts,
        "rid_count": len(rid_items or []),
        "open_rid_count": len(open_rids),
    }


def _gnc_rid_items(gnc: dict[str, Any]) -> list[dict[str, Any]]:
    editorial = _as_dict(gnc.get("editorial_synthesis"))
    minutes_struct = _as_dict(editorial.get("minutes_struct"))
    candidates = (
        _as_list(editorial.get("rid_items"))
        or _as_list(minutes_struct.get("rid_items"))
        or _as_list(_as_dict(gnc.get("metadata")).get("rid_items"))
    )
    return [item for item in candidates if isinstance(item, dict)]


_CROSS_DOCUMENT_RESULT_KEYS = (
    "cross_doc_findings",
    "cross_document_findings",
    "cross_document_items",
    "cross_document_review_items",
    "cross_document_conflicts",
    "consistency_findings",
    "traceability_gaps",
    "conflicts",
)


def _cross_document_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return cross-document issue rows from all result shapes used by Super Agent."""
    items: list[dict[str, Any]] = []
    for key in _CROSS_DOCUMENT_RESULT_KEYS:
        items.extend(item for item in _as_list(result.get(key)) if isinstance(item, dict))

    traceability = _as_dict(result.get("traceability_result"))
    items.extend(item for item in _as_list(traceability.get("review_items")) if isinstance(item, dict))
    items.extend(item for item in _as_list(traceability.get("cross_document_review_items")) if isinstance(item, dict))
    return items


def _cross_document_findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(_cross_document_items(result), start=1):
        status = str(item.get("status") or "open").strip().lower()
        if status in {"closed", "resolved"}:
            continue
        finding_id = str(
            item.get("finding_id")
            or item.get("review_item_id")
            or item.get("item_id")
            or item.get("id")
            or item.get("cross_doc_id")
            or item.get("conflict_id")
            or f"XDC-{index}"
        )
        source_quote = str(
            item.get("source_quote")
            or item.get("quote")
            or item.get("excerpt")
            or item.get("evidence_excerpt")
            or ""
        )
        raw_item_type = str(item.get("item_type") or item.get("conflict_type") or "cross_document_issue")
        item_type = raw_item_type if raw_item_type.startswith("cross") or "conflict" in raw_item_type else f"cross_document_{raw_item_type}"
        evidence_ids = _as_list(item.get("evidence_ids")) or _as_list(item.get("source_evidence_ids"))
        findings.append(
            {
                **item,
                "finding_id": finding_id,
                "title": str(item.get("title") or item.get("summary") or item.get("description") or "文文不一致项"),
                "description": str(item.get("description") or item.get("summary") or item.get("impact") or ""),
                "judgment": str(item.get("judgment") or "not_satisfied"),
                "item_type": item_type,
                "category": str(item.get("category") or "cross_document"),
                "severity": str(item.get("severity") or "major"),
                "recommendation": str(item.get("recommendation") or item.get("suggestion") or "请对齐相关文档中的术语、指标、约束和追溯关系。"),
                "agent_id": str(item.get("agent_id") or item.get("source") or "cross_document_reviewer"),
                "source": "cross_document",
                "source_materials": _as_list(item.get("source_artifact_ids")) or _as_list(item.get("source_materials")),
                "target_materials": _as_list(item.get("target_artifact_ids")) or _as_list(item.get("target_materials")),
                "evidence_ids": evidence_ids,
                "quote": source_quote,
                "excerpt": source_quote,
                "page": item.get("page") or item.get("page_number") or "",
                "section_path": item.get("section_path") or item.get("chapter_path") or "",
            }
        )
    return findings


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return dedupe_findings(findings)


def _conclusion_items(
    findings: list[dict[str, Any]],
    rid_items: list[dict[str, Any]] | None = None,
    *,
    review_mode: str = "super_agent",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, finding in enumerate(findings, start=1):
        bucket = _finding_bucket(finding, review_mode=review_mode)
        _, reason = classify_finding(finding, review_mode=review_mode)  # type: ignore[arg-type]
        evidence_ids = _as_list(finding.get("evidence_ids"))
        gap_reason = infer_evidence_gap_reason(finding) if bucket == "insufficient_evidence" else ""
        agent_id = str(finding.get("agent_id") or finding.get("discipline") or "")
        agent_label, agent_raw = resolve_agent_display_name(agent_id)
        title = resolve_check_item_title(
            str(finding.get("title") or finding.get("description") or "审查发现"),
            bucket=bucket,
        )
        items.append(
            {
                "check_item_id": str(finding.get("finding_id") or f"F-{index}"),
                "title": title,
                "status": bucket,
                "status_label": _finding_bucket_label(bucket),
                "business_bucket": bucket,
                "business_bucket_label": _finding_bucket_label(bucket),
                "bucket_reason": reason,
                "missing_reason": gap_reason,
                "evidence_gap_reason": gap_reason,
                "severity": finding.get("severity") or "",
                "judgment": finding.get("judgment") or "",
                "judgment_label": resolve_judgment_label_zh(str(finding.get("judgment") or "")),
                "description": finding.get("description") or "",
                "recommendation": finding.get("recommendation") or "",
                "agent_id": agent_id,
                "agent_display_name": agent_label,
                "agent_id_raw": agent_raw or (agent_id if agent_label != agent_id else ""),
                "evidence_ids": evidence_ids,
                "evidence_status": resolve_evidence_status_label_zh(
                    "supported" if evidence_ids or finding.get("source_quotes") else "missing"
                ),
                "source": "finding",
            }
        )
    for index, rid in enumerate(rid_items or [], start=1):
        rid_id = str(rid.get("rid_id") or rid.get("rid") or f"RID-{index}")
        items.append(
            {
                "check_item_id": rid_id,
                "title": str(rid.get("impact") or rid.get("description") or rid_id),
                "status": "rid_open" if str(rid.get("status") or "").lower() in {"open", "pending", ""} else "rid_closed",
                "status_label": "待闭环 RID" if str(rid.get("status") or "").lower() in {"open", "pending", ""} else "已关闭 RID",
                "severity": rid.get("severity") or "",
                "judgment": rid.get("status") or "",
                "description": rid.get("impact") or rid.get("description") or "",
                "recommendation": rid.get("recommendation") or "",
                "agent_id": rid.get("owner") or "",
                "evidence_ids": rid.get("source_evidence_ids") or [],
                "evidence_status": "已关联证据" if rid.get("source_evidence_ids") else "待补证",
                "source": "rid",
            }
        )
    return items


def _evidences(run: SuperAgentRun) -> list[dict[str, Any]]:
    if _prefer_gnc_result(run):
        evidence = _as_list(_gnc_result(run).get("evidence"))
        if evidence:
            return [item for item in evidence if isinstance(item, dict)]
    pool = run.structured_bundle.evidence_pool or {}
    evidences = pool.get("evidences") or pool.get("items") or []
    if isinstance(evidences, list):
        return [item for item in evidences if isinstance(item, dict)]
    return []


def _phase(run: SuperAgentRun) -> WorkbenchPhase:
    status = run.status.value if isinstance(run.status, SuperAgentStatus) else str(run.status or "")
    if status == SuperAgentStatus.FAILED.value:
        return WorkbenchPhase.FAILED
    if status in {SuperAgentStatus.COMPLETED.value, SuperAgentStatus.LIMITED.value}:
        return WorkbenchPhase.COMPLETED
    if status == SuperAgentStatus.RUNNING.value:
        if not run.completed_steps and not run.skill_traces:
            return WorkbenchPhase.STARTUP
        return WorkbenchPhase.EXECUTING
    return WorkbenchPhase.PRE_REVIEW


_SUPER_AGENT_TAB_ORDER = (
    WorkbenchTab.OVERVIEW,
    WorkbenchTab.MATERIALS,
    WorkbenchTab.ROUTES,
    WorkbenchTab.FINDINGS,
    WorkbenchTab.CLOSURE,
    WorkbenchTab.QUALITY,
)


def _visible_tabs(run: SuperAgentRun) -> list[str]:
    """Six business tabs for Super Agent; legacy keys are not exposed."""
    phase = _phase(run)
    if phase in {WorkbenchPhase.PRE_REVIEW, WorkbenchPhase.STARTUP, WorkbenchPhase.EXECUTING}:
        subset = {
            WorkbenchTab.OVERVIEW,
            WorkbenchTab.MATERIALS,
            WorkbenchTab.ROUTES,
            WorkbenchTab.QUALITY,
        }
        return [tab.value for tab in _SUPER_AGENT_TAB_ORDER if tab in subset]
    if phase == WorkbenchPhase.FAILED:
        subset = {
            WorkbenchTab.OVERVIEW,
            WorkbenchTab.MATERIALS,
            WorkbenchTab.ROUTES,
            WorkbenchTab.QUALITY,
        }
        return [tab.value for tab in _SUPER_AGENT_TAB_ORDER if tab in subset]
    return [tab.value for tab in _SUPER_AGENT_TAB_ORDER]


def build_workbench_metrics(run: SuperAgentRun) -> WorkbenchMetrics:
    result = _active_result(run)
    findings = _flatten_findings(result)
    cross_items = _cross_document_items(result)
    rid_items = _gnc_rid_items(result) if _prefer_gnc_result(run) else []
    board_summary = _as_dict(result.get("task_board_summary") or result.get("scheduler_summary"))
    conflicts = cross_items
    open_rids = [
        item for item in rid_items
        if str(item.get("status") or "").lower() in {"open", "pending", ""}
    ]
    materials = project_materials(run)
    check_item_count = len(run.structured_bundle.check_items) or len(findings)
    issue_stats = compute_workbench_issue_summary(
        findings,
        review_mode=_review_mode(run),  # type: ignore[arg-type]
        cross_doc_items=cross_items if isinstance(cross_items, list) else [],
        total_check_items=check_item_count,
        open_rid_count=len(open_rids),
    )
    return WorkbenchMetrics(
        finding_count=issue_stats["problem_count"],
        problem_count=issue_stats["problem_count"],
        check_item_count=issue_stats["check_item_count"],
        pending_confirm=issue_stats["pending_confirm"],
        rid_count=len(rid_items),
        open_rid_count=len(open_rids) or len([item for item in findings if str(item.get("status") or "").lower() in {"open", "pending"}]),
        evidence_count=len(_evidences(run)),
        conflict_count=len(conflicts) if isinstance(conflicts, list) else 0,
        requires_arbitration=bool(_as_dict(result.get("chief_decision")).get("requires_arbitration") or board_summary.get("blocked") or result.get("blocked_tasks")),
        material_count=len(materials),
    )


def _enrich_check_item(item: dict[str, Any], *, review_mode: str = "super_agent") -> dict[str, Any]:
    bucket = _finding_bucket(item, review_mode=review_mode)
    _, reason = classify_finding(item, review_mode=review_mode)  # type: ignore[arg-type]
    evidence_ids = _as_list(item.get("evidence_ids"))
    gap_reason = infer_evidence_gap_reason(item) if bucket == "insufficient_evidence" else ""
    judgment = str(item.get("judgment") or item.get("status") or "")
    raw_evidence_status = str(item.get("evidence_status") or "")
    if not raw_evidence_status:
        raw_evidence_status = "supported" if evidence_ids or item.get("source_quotes") else "missing"
    agent_id = str(item.get("agent_id") or item.get("discipline") or item.get("expert_role") or "")
    agent_label, agent_raw = resolve_agent_display_name(agent_id)
    title = resolve_check_item_title(
        str(item.get("title") or item.get("description") or item.get("check_item_id") or ""),
        bucket=bucket,
    )
    return {
        **item,
        "title": title,
        "status": bucket,
        "status_label": _finding_bucket_label(bucket),
        "business_bucket": bucket,
        "business_bucket_label": _finding_bucket_label(bucket),
        "conclusion_bucket": bucket,
        "conclusion_label": _finding_bucket_label(bucket),
        "bucket_reason": reason,
        "missing_reason": gap_reason or item.get("missing_reason") or "",
        "evidence_gap_reason": gap_reason or item.get("evidence_gap_reason") or "",
        "judgment_label": resolve_judgment_label_zh(judgment),
        "evidence_status": resolve_evidence_status_label_zh(raw_evidence_status),
        "agent_display_name": agent_label,
        "agent_id_raw": agent_raw or (agent_id if agent_label != agent_id else ""),
    }


def build_workbench_summary(run: SuperAgentRun) -> WorkbenchSummary:
    result = _active_result(run)
    chief_decision = _as_dict(result.get("chief_decision"))
    editorial = _as_dict(result.get("editorial_synthesis"))
    arbiter = _as_dict(result.get("arbiter_summary"))
    verdict_raw = str(
        chief_decision.get("verdict")
        or arbiter.get("verdict")
        or result.get("review_conclusion")
        or result.get("status")
        or run.status.value
    )
    rationale_raw = str(
        chief_decision.get("rationale")
        or editorial.get("conclusion_draft")
        or arbiter.get("summary")
        or arbiter.get("rationale")
        or result.get("message")
        or (run.quality_report.warnings[0] if run.quality_report.warnings else "")
    )
    return WorkbenchSummary(
        verdict=verdict_raw,
        verdict_label_zh=resolve_verdict_label_zh(verdict_raw),
        rationale=rationale_raw,
        rationale_zh=derive_rationale_zh(verdict=verdict_raw, rationale=rationale_raw),
        requires_arbitration=bool(chief_decision.get("requires_arbitration") or result.get("blocked_tasks")),
        arbitration_status="pending" if result.get("blocked_tasks") else "",
        report_available=bool((run.report_markdown or "").strip() or run.report_artifact or result.get("report_markdown")),
    )


_ROUTE_LABELS_ZH = {
    "auto": "自动路由",
    "smart": "通用审查",
    "smart_committee": "智能专家委员会",
    "review_plus": "文件组审查",
    "gnc_review": "GNC 审查",
    "gnc_review_only": "GNC 专项",
    "hybrid": "混合审查",
    "structure_only": "结构化解析",
}


def _enrich_super_agent_review_scope(run: SuperAgentRun, review_scope: dict[str, Any]) -> dict[str, Any]:
    classification = _as_dict(run.classification)
    route = _as_dict(run.route_decision)
    smart_plan = _as_dict(classification.get("smart_review_plan"))
    chief_plan = _as_dict(_active_result(run).get("chief_review_plan"))
    plan_lines = list(review_scope.get("review_plan_lines") or review_scope.get("actual_scope") or [])
    route_key = str(route.get("route") or smart_plan.get("primary_path") or _smart_primary_path(run) or "").strip()
    if route_key:
        route_label = _ROUTE_LABELS_ZH.get(route_key, route_key)
        route_line = f"执行路由：{route_label}"
        if route_line not in plan_lines:
            plan_lines.append(route_line)
    template_id = str(
        classification.get("review_template")
        or smart_plan.get("template_id")
        or classification.get("template_id")
        or ""
    ).strip()
    if template_id:
        template_line = f"审查模板：{template_id}"
        if template_line not in plan_lines:
            plan_lines.append(template_line)
    chief_name = str(chief_plan.get("chief_agent_name") or "").strip()
    if chief_name:
        chief_line = f"总师调度：{chief_name}"
        if chief_line not in plan_lines:
            plan_lines.append(chief_line)
    return {
        **review_scope,
        "review_plan_lines": plan_lines,
        "route_key": route_key,
    }


def _build_conclusion_overview(run: SuperAgentRun) -> WorkbenchConclusionOverview:
    result = _active_result(run)
    mode = _review_mode(run)
    findings = _flatten_findings(result)
    rid_items = _gnc_rid_items(result) if _prefer_gnc_result(run) else []
    summary = build_workbench_summary(run)
    cross_items = _cross_document_items(result)
    payload = build_conclusion_payload(
        review_mode=mode,  # type: ignore[arg-type]
        verdict=summary.verdict,
        rationale=summary.rationale,
        findings=findings,
        cross_doc_items=cross_items if isinstance(cross_items, list) else [],
        materials=project_materials(run),
        explicit_scope=str(_as_dict(run.classification).get("document_type") or ""),
        scenario=str(_as_dict(result.get("chief_review_plan")).get("scenario") or ""),
        total_check_items=len(run.structured_bundle.check_items) or len(findings),
        evidence_count=len(_evidences(run)),
        extra_priority=[
            {
                "id": str(rid.get("rid_id") or ""),
                "title": str(rid.get("impact") or rid.get("description") or "RID"),
                "business_bucket": "severe_error" if str(rid.get("severity") or "").lower() == "critical" else "content_nonconforming",
                "business_bucket_label": BUSINESS_BUCKET_LABELS["severe_error"]
                if str(rid.get("severity") or "").lower() == "critical"
                else BUSINESS_BUCKET_LABELS["content_nonconforming"],
                "severity": rid.get("severity") or "",
                "reason": str(rid.get("impact") or rid.get("description") or ""),
                "tab_hint": "rid",
            }
            for rid in rid_items
            if str(rid.get("status") or "").lower() in {"open", "pending", ""}
        ],
    )
    overview_summary = build_workbench_summary(run)
    overview_summary.headline_verdict = payload["headline_verdict"]
    overview_summary.one_line_conclusion = payload["one_line_conclusion"]
    overview_summary.review_mode_label = payload["review_scope"].get("review_mode_label", "")
    overview_summary.verdict_label_zh = str(payload.get("verdict_label_zh") or resolve_verdict_label_zh(summary.verdict))
    overview_summary.rationale_zh = str(payload.get("rationale_zh") or derive_rationale_zh(
        buckets=payload["issue_buckets"],
        verdict=str(payload.get("verdict") or summary.verdict),
        rationale=summary.rationale,
        material_insufficiency=bool(payload.get("material_insufficiency")),
    ))
    return WorkbenchConclusionOverview(
        headline_verdict=payload["headline_verdict"],
        headline_zh=str(payload.get("headline_zh") or payload["headline_verdict"]),
        one_line_conclusion=payload["one_line_conclusion"],
        verdict_label_zh=str(payload.get("verdict_label_zh") or overview_summary.verdict_label_zh),
        rationale_zh=str(payload.get("rationale_zh") or overview_summary.rationale_zh),
        issue_buckets=payload["issue_buckets"],
        bucket_labels=payload["bucket_labels"],
        review_scope=_enrich_super_agent_review_scope(run, dict(payload["review_scope"])),
        priority_items=payload["priority_items"],
        coverage_summary=payload["coverage_summary"],
    )


def build_workbench_detail(run: SuperAgentRun) -> UnifiedReviewWorkbenchDetail:
    summary = build_workbench_summary(run)
    conclusion = _build_conclusion_overview(run)
    summary.headline_verdict = conclusion.headline_verdict
    summary.one_line_conclusion = conclusion.one_line_conclusion
    summary.review_mode_label = conclusion.review_scope.get("review_mode_label", "")
    summary.verdict_label_zh = conclusion.verdict_label_zh or summary.verdict_label_zh
    summary.rationale_zh = conclusion.rationale_zh or summary.rationale_zh
    return UnifiedReviewWorkbenchDetail(
        review_id=run.run_id,
        name=run.name or "Super Agent 审查",
        review_type=ReviewType.SUPER_AGENT,
        status=run.status.value if isinstance(run.status, SuperAgentStatus) else str(run.status or ""),
        workbench_phase=_phase(run),
        visible_tabs=_visible_tabs(run),
        current_step=run.current_phase or (run.skill_traces[-1].skill_id if run.skill_traces else ""),
        metrics=build_workbench_metrics(run),
        summary=summary,
        conclusion_overview=conclusion,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def project_flow(run: SuperAgentRun) -> dict[str, Any]:
    trace_by_skill = {trace.skill_id: trace for trace in run.skill_traces}
    ordered = [
        "classify_and_route",
        "document_parse",
        "structure_materials",
        "bootstrap_review_plus_task",
        "run_review_plus",
        "run_gnc_review",
        "smart_review_committee",
        "review_results",
    ]
    steps = []
    for step in ordered:
        trace = trace_by_skill.get(step)
        completed = step in run.completed_steps or (trace is not None and trace.status == "completed")
        if trace or completed or step in {"classify_and_route", "document_parse", "review_results"}:
            steps.append(
                {
                    "step_key": step,
                    "label": step,
                    "status": trace.status if trace else ("completed" if completed else "pending"),
                    "completed": completed,
                    "output_summary": trace.output_summary if trace else {},
                    "warnings": trace.warnings if trace else [],
                    "elapsed_ms": trace.elapsed_ms if trace else 0,
                }
            )
    return {
        "review_id": run.run_id,
        "status": run.status.value if isinstance(run.status, SuperAgentStatus) else str(run.status or ""),
        "current_step": run.current_phase or (steps[-1]["step_key"] if steps else ""),
        "steps": steps,
    }


def project_materials(run: SuperAgentRun) -> list[dict[str, Any]]:
    if run.structured_bundle.materials:
        return [dict(item) for item in run.structured_bundle.materials if isinstance(item, dict)]
    return [material.model_dump(mode="json") for material in run.materials]


def project_check_items(run: SuperAgentRun) -> list[dict[str, Any]]:
    mode = _review_mode(run)
    if _prefer_gnc_result(run):
        gnc = _gnc_result(run)
        return _conclusion_items(_flatten_findings(gnc), _gnc_rid_items(gnc), review_mode=mode)
    return [
        _enrich_check_item(dict(item), review_mode=mode)
        for item in run.structured_bundle.check_items
        if isinstance(item, dict)
    ]


def project_findings(run: SuperAgentRun) -> list[dict[str, Any]]:
    mode = _review_mode(run)
    result = _active_result(run)
    findings = _dedupe_findings([*_flatten_findings(result), *_cross_document_findings(result)])
    enriched: list[dict[str, Any]] = []
    for item in findings:
        bucket = _finding_bucket(item, review_mode=mode)
        gap = infer_evidence_gap_reason(item) if bucket == "insufficient_evidence" else ""
        agent_id = str(item.get("agent_id") or item.get("discipline") or "")
        agent_label, agent_raw = resolve_agent_display_name(agent_id)
        enriched.append(
            {
                **item,
                "title": resolve_check_item_title(
                    str(item.get("title") or item.get("description") or ""),
                    bucket=bucket,
                ),
                "business_bucket": bucket,
                "business_bucket_label": _finding_bucket_label(bucket),
                "conclusion_bucket": bucket,
                "conclusion_label": _finding_bucket_label(bucket),
                "missing_reason": gap,
                "evidence_gap_reason": gap,
                "judgment_label": resolve_judgment_label_zh(str(item.get("judgment") or "")),
                "agent_display_name": agent_label,
                "agent_id_raw": agent_raw or (agent_id if agent_label != agent_id else ""),
                "evidence_status": resolve_evidence_status_label_zh(
                    "supported" if item.get("evidence_ids") or item.get("source_quotes") else "missing"
                ),
            }
        )
    return enriched


def project_evidences(run: SuperAgentRun) -> list[dict[str, Any]]:
    return _evidences(run)


def project_committee(run: SuperAgentRun) -> dict[str, Any]:
    if _prefer_gnc_result(run):
        result = _gnc_result(run)
        discipline_reviews = _as_dict(result.get("discipline_reviews"))
        specialists = []
        for key, review in discipline_reviews.items():
            if not isinstance(review, dict):
                continue
            specialists.append(
                {
                    "agent_id": str(review.get("agent_id") or review.get("unit_key") or key),
                    "agent_name": str(review.get("unit_name") or review.get("reviewer") or key),
                    "status": str(review.get("status") or ("completed" if review.get("completed") else "")),
                    "summary": review.get("summary") or review.get("verdict") or "",
                    "findings": _as_list(review.get("findings")),
                    "rule_results": _as_list(review.get("rule_results")),
                }
            )
        return {
            "review_mode": "gnc",
            "chief_review_plan": {
                "chief_agent_name": "GNC 总师审定 Agent",
                "scenario": _as_dict(result.get("editorial_synthesis")).get("minutes")
                or _as_dict(result.get("chief_decision")).get("rationale")
                or "",
                "selected_agents": specialists,
            },
            "specialist_reviews": specialists,
            "discipline_reviews": discipline_reviews,
            "editorial_synthesis": _as_dict(result.get("editorial_synthesis")),
            "chief_decision": _as_dict(result.get("chief_decision")),
        }
    result = _smart_result(run)
    return {
        "chief_review_plan": _as_dict(result.get("chief_review_plan")),
        "specialist_reviews": [item for item in _as_list(result.get("specialist_reviews")) if isinstance(item, dict)],
        "smart_task_board": _as_dict(result.get("smart_task_board")),
        "task_board_summary": _as_dict(result.get("task_board_summary") or result.get("scheduler_summary")),
        "bootstrap_summary": _as_dict(result.get("bootstrap_summary")),
    }


def project_decision(run: SuperAgentRun) -> dict[str, Any]:
    result = _active_result(run)
    mode = _review_mode(run)
    findings = _flatten_findings(result)
    rid_items = _gnc_rid_items(result) if _prefer_gnc_result(run) else []
    chief_decision = _as_dict(result.get("chief_decision"))
    editorial = _as_dict(result.get("editorial_synthesis"))
    summary = build_workbench_summary(run)
    cross_items = _cross_document_items(result)
    conclusion = build_conclusion_payload(
        review_mode=mode,  # type: ignore[arg-type]
        verdict=summary.verdict,
        rationale=summary.rationale,
        findings=findings,
        cross_doc_items=cross_items if isinstance(cross_items, list) else [],
        materials=project_materials(run),
        explicit_scope=str(_as_dict(run.classification).get("document_type") or ""),
        scenario=str(_as_dict(result.get("chief_review_plan")).get("scenario") or ""),
        total_check_items=len(run.structured_bundle.check_items) or len(findings),
        evidence_count=len(_evidences(run)),
    )
    return {
        "verdict": summary.verdict,
        "verdict_label_zh": conclusion.get("verdict_label_zh") or summary.verdict_label_zh,
        "rationale": summary.rationale,
        "rationale_zh": conclusion.get("rationale_zh") or summary.rationale_zh,
        "headline_verdict": conclusion["headline_verdict"],
        "headline_zh": conclusion.get("headline_zh") or conclusion["headline_verdict"],
        "one_line_conclusion": conclusion["one_line_conclusion"],
        "arbiter_summary": _as_dict(result.get("arbiter_summary")),
        "chief_decision": chief_decision,
        "editorial_synthesis": editorial,
        "issue_buckets": conclusion["issue_buckets"],
        "bucket_labels": conclusion["bucket_labels"],
        "review_scope": conclusion["review_scope"],
        "priority_items": conclusion["priority_items"],
        "coverage_summary": conclusion["coverage_summary"],
        "issue_summary": _issue_summary(findings, rid_items, review_mode=mode),
        "conclusion_items": _conclusion_items(findings, rid_items, review_mode=mode),
        "rid_items": rid_items,
        "key_risks": _as_list(chief_decision.get("key_risks")) or _as_list(editorial.get("residual_risks")),
        "replan_suggestions": _as_list(result.get("replan_suggestions")),
        "quality_report": run.quality_report.model_dump(mode="json"),
        "trace_degradation_summary": list(run.trace_report.degradation_summary or []),
    }


def project_report(run: SuperAgentRun) -> dict[str, Any] | None:
    from data_agent.review_workbench.issue_taxonomy import localize_report_markdown

    try:
        from data_agent.super_agent.phases.review_results import build_super_agent_user_report

        artifact = build_super_agent_user_report(run)
        if artifact.markdown.strip():
            payload = artifact.model_dump(mode="json")
            payload["markdown"] = localize_report_markdown(str(payload.get("markdown") or artifact.markdown))
            return payload
    except Exception:
        pass
    from data_agent.reporting import is_internal_review_report

    if run.report_artifact:
        stored = dict(run.report_artifact)
        markdown = str(stored.get("markdown") or "")
        if markdown.strip() and not is_internal_review_report(markdown):
            stored["markdown"] = localize_report_markdown(markdown)
            return stored
    if run.report_markdown and not is_internal_review_report(run.report_markdown):
        return {"markdown": localize_report_markdown(run.report_markdown)}
    return None


def project_routes(run: SuperAgentRun) -> dict[str, Any]:
    classification = _as_dict(run.classification)
    smart_plan = _as_dict(classification.get("smart_review_plan"))
    return {
        "review_mode": _review_mode(run),
        "primary_path": _smart_primary_path(run) or smart_plan.get("primary_path") or "",
        "route_decision": _as_dict(run.route_decision),
        "flow": project_flow(run),
        "committee": project_committee(run),
        "events": project_events(run),
    }


def project_closure(run: SuperAgentRun) -> dict[str, Any]:
    decision = project_decision(run)
    report = project_report(run)
    chief = _as_dict(decision.get("chief_decision"))
    editorial = _as_dict(decision.get("editorial_synthesis"))
    return {
        **decision,
        "report": report,
        "closure_status": {
            "verdict": decision.get("verdict"),
            "verdict_label_zh": decision.get("verdict_label_zh"),
            "report_available": bool(report),
            "requires_arbitration": bool(chief.get("requires_arbitration")),
            "editorial_draft": editorial.get("conclusion_draft") or "",
            "remediation_notes": _as_list(editorial.get("remediation_items") or editorial.get("action_items")),
            "re_review_required": bool(editorial.get("re_review_required") or chief.get("re_review_required")),
        },
        "fact_summary": decision.get("coverage_summary") or {},
        "issue_recommendations": decision.get("priority_items") or [],
        "expert_confirmation_items": [
            item for item in _conclusion_items(
                _flatten_findings(_active_result(run)),
                _gnc_rid_items(_active_result(run)) if _prefer_gnc_result(run) else [],
                review_mode=_review_mode(run),
            )
            if str(item.get("business_bucket") or "") in {"manual_review", "insufficient_evidence"}
        ],
    }


def project_quality(run: SuperAgentRun) -> dict[str, Any]:
    decision = project_decision(run)
    quality = run.quality_report.model_dump(mode="json")
    parse_quality = _as_dict(_as_dict(run.phase_artifacts.get("document_review")).get("parse_quality"))
    return {
        "quality_report": quality,
        "parse_quality": parse_quality,
        "trace_degradation_summary": list(run.trace_report.degradation_summary or []),
        "execution_events": project_events(run),
        "output_integrity": {
            "report_available": bool((run.report_markdown or "").strip() or run.report_artifact),
            "finding_count": build_workbench_metrics(run).finding_count,
            "evidence_count": build_workbench_metrics(run).evidence_count,
        },
        "technical_review_disclaimer": "技术复盘，不替代专家审查判断",
    }


def project_events(run: SuperAgentRun) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, trace in enumerate(run.skill_traces, start=1):
        events.append(
            {
                "sequence": index,
                "type": trace.skill_id,
                "status": trace.status,
                "payload": {
                    "agent_id": trace.agent_id,
                    "tool_name": trace.tool_name,
                    "input_summary": trace.input_summary,
                    "output_summary": trace.output_summary,
                    "warnings": trace.warnings,
                    "elapsed_ms": trace.elapsed_ms,
                },
            }
        )
    offset = len(events)
    for index, event in enumerate(run.trace_report.workflow_events or [], start=1):
        payload = dict(event) if isinstance(event, dict) else {"value": event}
        events.append({"sequence": offset + index, "type": str(payload.get("source") or "workflow_event"), "payload": payload})
    return events
