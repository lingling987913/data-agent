"""Project GNC review runs into unified workbench read/write models."""

from __future__ import annotations

from typing import Any

from data_agent.integrations.satellite_review.gnc_schemas import (
    GNCReviewResult,
    GNCReviewRun,
    GNCReviewStatus,
)
from data_agent.integrations.satellite_review.arbitration_service import annotate_rid_prior_cycle_status
from data_agent.review_workbench.mappers import (
    GNC_STEP_LABELS,
    GNC_STEP_TO_TAB,
    GNC_WORKFLOW_STEPS,
    map_gnc_status_to_phase,
    resolve_gnc_visible_tabs,
)
from data_agent.review_workbench.issue_taxonomy import (
    BUSINESS_BUCKET_LABELS,
    build_conclusion_payload,
    classify_finding,
    compute_workbench_issue_summary,
    infer_evidence_gap_reason,
)
from data_agent.review_workbench.schemas import (
    GNCArbitrationRequest,
    GNCRidPatchRequest,
    ReviewType,
    UnifiedReviewWorkbenchDetail,
    WorkbenchConclusionOverview,
    WorkbenchMetrics,
    WorkbenchSummary,
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _gnc_completed_steps(run: GNCReviewRun) -> set[str]:
    return {step for step in GNC_WORKFLOW_STEPS if step in (run.step_outputs or {})}


def _committee_payload(run: GNCReviewRun) -> dict[str, Any]:
    editorial = _as_dict((run.step_outputs or {}).get("editorial_synthesis"))
    committee = editorial.get("committee_data")
    if isinstance(committee, dict):
        return committee
    return _as_dict((run.step_outputs or {}).get("committee_review"))


def _editorial_payload(run: GNCReviewRun) -> dict[str, Any]:
    if run.result and isinstance(run.result.editorial_synthesis, dict):
        return run.result.editorial_synthesis
    editorial_step = _as_dict((run.step_outputs or {}).get("editorial_synthesis"))
    payload = editorial_step.get("editorial_synthesis")
    return payload if isinstance(payload, dict) else editorial_step


def _chief_payload(run: GNCReviewRun) -> dict[str, Any]:
    if run.result and isinstance(run.result.chief_decision, dict):
        return run.result.chief_decision
    chief_step = _as_dict((run.step_outputs or {}).get("chief_adjudication"))
    decision = chief_step.get("chief_decision")
    return decision if isinstance(decision, dict) else {}


def _arbitration_payload(run: GNCReviewRun) -> dict[str, Any]:
    if run.result and isinstance(run.result.arbitration, dict):
        return run.result.arbitration
    return _as_dict((run.step_outputs or {}).get("human_arbitration"))


def project_findings(run: GNCReviewRun) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    if run.result and run.result.findings:
        raw = [item.model_dump(mode="json") for item in run.result.findings]
    else:
        committee = _committee_payload(run)
        raw = [item for item in (committee.get("findings") or []) if isinstance(item, dict)]
    enriched: list[dict[str, Any]] = []
    for item in raw:
        bucket, _ = classify_finding(item, review_mode="gnc")
        gap = infer_evidence_gap_reason(item) if bucket == "insufficient_evidence" else ""
        enriched.append(
            {
                **item,
                "business_bucket": bucket,
                "business_bucket_label": BUSINESS_BUCKET_LABELS[bucket],
                "missing_reason": gap,
                "evidence_gap_reason": gap,
            }
        )
    return enriched


def _rid_related_finding_ids(rid: dict[str, Any], findings: list[dict[str, Any]]) -> list[str]:
    related: list[str] = []
    source_finding = str(rid.get("source_finding_id") or rid.get("finding_id") or "")
    if source_finding:
        related.append(source_finding)
    source_rule = str(rid.get("source_rule_id") or "")
    if source_rule:
        for finding in findings:
            rule_ids = finding.get("rule_ids") or []
            if source_rule in {str(rule_id) for rule_id in rule_ids}:
                finding_id = str(finding.get("finding_id") or "")
                if finding_id and finding_id not in related:
                    related.append(finding_id)
    return related


def project_rid_items(run: GNCReviewRun) -> list[dict[str, Any]]:
    editorial = _editorial_payload(run)
    rid_items = editorial.get("rid_items") or []
    if not rid_items:
        editorial_step = _as_dict((run.step_outputs or {}).get("editorial_synthesis"))
        rid_items = editorial_step.get("rid_items") or []
    findings = project_findings(run)
    review_focus = run.request.review_focus if run.request else {}
    annotated, _summary = annotate_rid_prior_cycle_status(
        [item for item in rid_items if isinstance(item, dict)],
        review_focus,
    )
    enriched: list[dict[str, Any]] = []
    for item in annotated:
        payload = dict(item)
        payload["related_finding_ids"] = _rid_related_finding_ids(payload, findings)
        payload["related_evidence_ids"] = [
            str(evidence_id)
            for evidence_id in (payload.get("source_evidence_ids") or payload.get("evidence_ids") or [])
            if evidence_id
        ]
        enriched.append(payload)
    return enriched


def project_minutes(run: GNCReviewRun) -> dict[str, Any]:
    editorial = _editorial_payload(run)
    minutes = editorial.get("minutes_struct") or editorial.get("minutes")
    if isinstance(minutes, dict):
        return minutes
    if isinstance(minutes, str) and minutes.strip():
        return {"text": minutes}
    editorial_step = _as_dict((run.step_outputs or {}).get("editorial_synthesis"))
    fallback = editorial_step.get("minutes")
    if isinstance(fallback, dict):
        return fallback
    if isinstance(fallback, str) and fallback.strip():
        return {"text": fallback}
    return {}


def project_decision(run: GNCReviewRun) -> dict[str, Any]:
    chief = _chief_payload(run)
    findings = project_findings(run)
    summary = build_workbench_summary(run)
    committee = _committee_payload(run)
    scope = _resolve_review_scope(committee, run)
    payload = build_conclusion_payload(
        review_mode="gnc",
        verdict=str(chief.get("verdict") or summary.verdict),
        rationale=str(chief.get("rationale") or summary.rationale),
        findings=findings,
        cross_doc_items=project_cross_document(run),
        materials=project_materials(run),
        explicit_scope=scope,
        scenario=str(run.request.review_phase if run.request else ""),
        total_check_items=len(findings),
        evidence_count=len(project_evidences(run)),
        extra_priority=[
            {
                "id": str(rid.get("rid_id") or ""),
                "title": str(rid.get("impact") or rid.get("description") or "RID"),
                "business_bucket": "severe_error"
                if str(rid.get("severity") or "").lower() == "critical"
                else "content_nonconforming",
                "business_bucket_label": BUSINESS_BUCKET_LABELS["severe_error"]
                if str(rid.get("severity") or "").lower() == "critical"
                else BUSINESS_BUCKET_LABELS["content_nonconforming"],
                "severity": rid.get("severity") or "",
                "reason": str(rid.get("impact") or rid.get("description") or ""),
                "tab_hint": "rid",
            }
            for rid in project_rid_items(run)
            if str(rid.get("status") or "").lower() in {"open", "pending", "reopened", ""}
        ],
    )
    return {**chief, **payload}


def _normalize_rule_result(rule: dict[str, Any]) -> dict[str, Any]:
    execution_status = str(rule.get("execution_status") or rule.get("status") or "checked")
    passed = rule.get("passed")
    judgment = str(rule.get("judgment") or "")
    if passed is False and not judgment:
        judgment = "not_satisfied"
    elif passed is True and not judgment:
        judgment = "satisfied"
    hard_fail = bool(rule.get("hard_fail") or rule.get("blocking") or (passed is False and execution_status != "not_checked"))
    placeholder = execution_status in {"not_checked", "placeholder", "skipped"} or bool(rule.get("placeholder"))
    return {
        **rule,
        "rule_id": str(rule.get("rule_id") or ""),
        "judgment": judgment,
        "execution_status": execution_status,
        "hard_fail": hard_fail,
        "placeholder": placeholder,
        "blocking": bool(rule.get("blocking") or hard_fail),
        "not_checked": execution_status == "not_checked" or placeholder,
    }


_AD_SUBFLOW_STAGE_DEFS: list[tuple[str, str, str]] = [
    ("req_err", "ad_requirement_error_unit", "需求误差"),
    ("timing", "ad_sampling_timing_unit", "时序/采样"),
    ("install", "ad_mounting_pointing_unit", "安装/指向"),
    ("algorithm", "ad_determination_algorithm_unit", "算法"),
    ("simulation", "ad_simulation_analysis_unit", "仿真"),
    ("consistency", "ad_cross_consistency_unit", "一致性"),
    ("report", "ad_report_completeness_unit", "报告完整性"),
]

_AC_SUBFLOW_STAGE_DEFS: list[tuple[str, str, str]] = [
    ("req_err", "ac_requirement_error_unit", "需求误差"),
    ("thruster_layout", "ac_thruster_layout_unit", "推力器布局"),
    ("other_actuator_layout", "ac_actuator_layout_unit", "执行机构布局"),
    ("control_law", "ac_control_law_unit", "控制律设计"),
    ("control_params", "ac_control_param_unit", "控制参数"),
    ("maneuver_law", "ac_maneuver_control_unit", "机动控制"),
    ("unloading_law", "ac_momentum_unload_unit", "动量卸载"),
    ("simulation", "ac_control_simulation_unit", "仿真"),
    ("consistency", "ac_cross_consistency_unit", "一致性"),
    ("report", "ac_report_completeness_unit", "报告完整性"),
]


def _resolve_review_scope(committee: dict[str, Any], run: GNCReviewRun | None = None) -> str:
    scope = str(committee.get("review_scope") or "").strip()
    if scope:
        return scope
    if run and run.request:
        return str(run.request.review_scope or "").strip()
    return "ad_ac"


def _normalize_stage_result(stage_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    blocking_flags = [str(flag) for flag in (payload.get("blocking_flags") or []) if flag]
    return {
        "stage_key": stage_key,
        "status": str(payload.get("status") or "pending"),
        "summary": str(payload.get("summary") or ""),
        "finding_count": int(payload.get("finding_count") or 0),
        "rule_judgment_count": int(payload.get("rule_judgment_count") or 0),
        "knowledge_gap": bool(payload.get("knowledge_gap")),
        "execution": str(payload.get("execution") or ""),
        "blocking_flags": blocking_flags,
    }


def _normalize_group_subflow_result(
    group_key: str,
    group_label: str,
    *,
    group_payload: dict[str, Any],
    stage_defs: list[tuple[str, str, str]],
    enabled: bool,
    skipped_stages: list[str] | None = None,
) -> dict[str, Any]:
    conclusion = _as_dict(group_payload.get("conclusion"))
    stage_results_raw = group_payload.get("stage_results")
    if not isinstance(stage_results_raw, dict):
        stage_results_raw = conclusion.get("stage_results")
    stage_results_raw = stage_results_raw if isinstance(stage_results_raw, dict) else {}

    unit_results = [
        _normalize_unit_result(item)
        for item in (group_payload.get("unit_results") or conclusion.get("unit_results") or [])
        if isinstance(item, dict)
    ]
    unit_by_stage = {
        str(item.get("stage_key") or item.get("stage") or ""): item
        for item in unit_results
        if item.get("stage_key") or item.get("stage")
    }

    stage_rule_judgments = conclusion.get("stage_rule_judgments")
    if not isinstance(stage_rule_judgments, dict):
        stage_rule_judgments = {}

    skipped = {str(item) for item in (skipped_stages or group_payload.get("skipped_stages") or []) if item}
    stages: list[dict[str, Any]] = []
    for stage_key, unit_key, stage_label in stage_defs:
        if not enabled:
            stages.append(
                {
                    "stage_key": stage_key,
                    "stage_label": stage_label,
                    "unit_key": unit_key,
                    "status": "skipped",
                    "skip_reason": "本轮未启用（由 review_scope 跳过）",
                    "finding_count": 0,
                    "rule_judgment_count": 0,
                    "blocking_flags": [],
                    "summary": "",
                }
            )
            continue
        if stage_key in skipped:
            stages.append(
                {
                    "stage_key": stage_key,
                    "stage_label": stage_label,
                    "unit_key": unit_key,
                    "status": "skipped",
                    "skip_reason": "模板/证据未启用",
                    "finding_count": 0,
                    "rule_judgment_count": 0,
                    "blocking_flags": [],
                    "summary": "",
                }
            )
            continue

        stage_payload = stage_results_raw.get(stage_key)
        unit_payload = unit_by_stage.get(stage_key)
        if isinstance(stage_payload, dict):
            normalized = _normalize_stage_result(stage_key, stage_payload)
        elif isinstance(unit_payload, dict):
            findings = unit_payload.get("findings") or []
            rule_results = unit_payload.get("rule_results") or []
            normalized = {
                "stage_key": stage_key,
                "status": str(unit_payload.get("status") or "pending"),
                "summary": str(unit_payload.get("summary") or ""),
                "finding_count": len(findings) if isinstance(findings, list) else 0,
                "rule_judgment_count": len(rule_results) if isinstance(rule_results, list) else 0,
                "knowledge_gap": bool(unit_payload.get("knowledge_gap")),
                "execution": str(unit_payload.get("execution") or ""),
                "blocking_flags": list(unit_payload.get("blocking_flags") or []),
            }
        else:
            judgments = stage_rule_judgments.get(stage_key)
            normalized = {
                "stage_key": stage_key,
                "status": "pending",
                "summary": "",
                "finding_count": 0,
                "rule_judgment_count": len(judgments) if isinstance(judgments, list) else 0,
                "knowledge_gap": False,
                "execution": "",
                "blocking_flags": [],
            }

        stage_blocking = [
            str(flag)
            for flag in normalized.get("blocking_flags") or []
            if flag
        ]
        if not stage_blocking and isinstance(unit_payload, dict):
            stage_blocking = [str(flag) for flag in (unit_payload.get("blocking_flags") or []) if flag]

        stages.append(
            {
                "stage_key": stage_key,
                "stage_label": stage_label,
                "unit_key": unit_key,
                "status": normalized.get("status") or "pending",
                "skip_reason": "",
                "finding_count": int(normalized.get("finding_count") or 0),
                "rule_judgment_count": int(normalized.get("rule_judgment_count") or 0),
                "blocking_flags": stage_blocking,
                "summary": str(normalized.get("summary") or ""),
                "knowledge_gap": bool(normalized.get("knowledge_gap")),
                "execution": str(normalized.get("execution") or ""),
            }
        )

    blocking_flags = [str(flag) for flag in (group_payload.get("blocking_flags") or conclusion.get("blocking_flags") or []) if flag]
    return {
        "group_key": group_key,
        "group_label": group_label,
        "enabled": enabled,
        "skip_reason": "" if enabled else "本轮未启用（由 review_scope 跳过）",
        "verdict": str(conclusion.get("verdict") or group_payload.get("verdict") or ""),
        "summary": str(conclusion.get("summary") or group_payload.get("summary") or ""),
        "blocking_flags": blocking_flags,
        "stage_coverage": group_payload.get("stage_coverage") or conclusion.get("stage_coverage") or [],
        "stage_results": {
            stage["stage_key"]: {
                key: stage[key]
                for key in (
                    "status",
                    "summary",
                    "finding_count",
                    "rule_judgment_count",
                    "blocking_flags",
                    "knowledge_gap",
                    "execution",
                )
            }
            for stage in stages
            if stage.get("status") != "skipped" or not stage.get("skip_reason", "").startswith("本轮未启用")
        },
        "stage_rule_judgments": stage_rule_judgments,
        "unit_results": unit_results,
        "stages": stages,
        "enabled_stages": group_payload.get("enabled_stages") or [],
        "skipped_stages": sorted(skipped),
    }


def _normalize_unit_result(unit: dict[str, Any]) -> dict[str, Any]:
    rule_results = [
        _normalize_rule_result(rule)
        for rule in (unit.get("rule_results") or [])
        if isinstance(rule, dict)
    ]
    blocking_flags = [
        str(flag)
        for flag in (unit.get("blocking_flags") or [])
        if flag
    ]
    if not blocking_flags:
        blocking_flags = [
            rule["rule_id"]
            for rule in rule_results
            if rule.get("blocking") and rule.get("rule_id")
        ]
    not_checked = [rule["rule_id"] for rule in rule_results if rule.get("not_checked") and rule.get("rule_id")]
    hard_fail_rules = [rule["rule_id"] for rule in rule_results if rule.get("hard_fail") and rule.get("rule_id")]
    placeholder_rules = [rule["rule_id"] for rule in rule_results if rule.get("placeholder") and rule.get("rule_id")]
    return {
        **unit,
        "unit_key": str(unit.get("unit_key") or unit.get("unit_id") or ""),
        "stage": str(unit.get("stage") or unit.get("stage_key") or unit.get("discipline") or ""),
        "stage_key": str(unit.get("stage_key") or unit.get("stage") or ""),
        "rule_results": rule_results,
        "blocking_flags": blocking_flags,
        "not_checked_rule_ids": not_checked,
        "hard_fail_rule_ids": hard_fail_rules,
        "placeholder_rule_ids": placeholder_rules,
    }


def project_committee(run: GNCReviewRun) -> dict[str, Any]:
    committee = _committee_payload(run)
    discipline_reviews = committee.get("discipline_reviews") or {}
    unit_results = [
        _normalize_unit_result(item)
        for item in (committee.get("unit_results") or [])
        if isinstance(item, dict)
    ]
    ad_group = discipline_reviews.get("ad_group") if isinstance(discipline_reviews, dict) else {}
    ac_group = discipline_reviews.get("ac_group") if isinstance(discipline_reviews, dict) else {}
    if not isinstance(ad_group, dict):
        ad_group = {}
    if not isinstance(ac_group, dict):
        ac_group = {}

    ad_group_result_raw = committee.get("ad_group_result")
    ac_group_result_raw = committee.get("ac_group_result")
    ad_group_result = ad_group_result_raw if isinstance(ad_group_result_raw, dict) else {}
    ac_group_result = ac_group_result_raw if isinstance(ac_group_result_raw, dict) else {}

    review_scope = _resolve_review_scope(committee, run)
    run_ad_group = review_scope in {"ad_only", "ad_ac"}
    run_ac_group = review_scope in {"ac_only", "ad_ac"}

    ad_subflow = _normalize_group_subflow_result(
        "ad_group",
        "AD 姿态确定",
        group_payload=ad_group_result,
        stage_defs=_AD_SUBFLOW_STAGE_DEFS,
        enabled=run_ad_group,
    )
    ac_subflow = _normalize_group_subflow_result(
        "ac_group",
        "AC 姿态控制",
        group_payload=ac_group_result,
        stage_defs=_AC_SUBFLOW_STAGE_DEFS,
        enabled=run_ac_group,
    )

    blocking_flags = committee.get("blocking_flags") or []
    if not blocking_flags:
        blocking_flags = sorted(
            {
                flag
                for unit in unit_results
                for flag in unit.get("blocking_flags") or []
            }
        )
    return {
        "discipline_reviews": discipline_reviews,
        "ad_group": ad_group,
        "ac_group": ac_group,
        "ad_group_result": ad_subflow,
        "ac_group_result": ac_subflow,
        "groups": {"ad_group": ad_group, "ac_group": ac_group},
        "review_scope": review_scope,
        "subflow_lanes": [ad_subflow, ac_subflow],
        "findings": committee.get("findings") or [],
        "conflicts": committee.get("conflicts") or [],
        "failures": committee.get("failures") or {},
        "unit_results": unit_results,
        "blocking_flags": blocking_flags,
        "not_checked_rule_ids": sorted(
            {
                rule_id
                for unit in unit_results
                for rule_id in unit.get("not_checked_rule_ids") or []
            }
        ),
        "hard_fail_rule_ids": sorted(
            {
                rule_id
                for unit in unit_results
                for rule_id in unit.get("hard_fail_rule_ids") or []
            }
        ),
        "placeholder_rule_ids": sorted(
            {
                rule_id
                for unit in unit_results
                for rule_id in unit.get("placeholder_rule_ids") or []
            }
        ),
    }


_EVIDENCE_RID_LIST_KEYS = (
    "related_rid_ids",
    "rid_ids",
    "review_item_ids",
    "related_review_item_ids",
    "linked_rid_ids",
)

_EVIDENCE_RID_SCALAR_KEYS = (
    "related_rid_id",
    "rid_id",
    "review_item_id",
    "related_review_item_id",
    "linked_rid_id",
)


def _collect_evidence_rid_ids(item: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            ids.append(text)

    for key in _EVIDENCE_RID_LIST_KEYS:
        raw = item.get(key)
        if isinstance(raw, list):
            for value in raw:
                add(value)
        elif raw is not None:
            add(raw)
    for key in _EVIDENCE_RID_SCALAR_KEYS:
        add(item.get(key))
    return ids


def _normalize_evidence_rid_fields(payload: dict[str, Any]) -> None:
    rid_ids = _collect_evidence_rid_ids(payload)
    if not rid_ids:
        return
    primary = rid_ids[0]
    if not str(payload.get("review_item_id") or "").strip():
        payload["review_item_id"] = primary
    if not str(payload.get("related_rid_id") or "").strip():
        payload["related_rid_id"] = primary
    existing_related = payload.get("related_rid_ids")
    if isinstance(existing_related, list):
        merged: list[str] = []
        seen: set[str] = set()
        for value in [*existing_related, *rid_ids]:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
        payload["related_rid_ids"] = merged
    else:
        payload["related_rid_ids"] = rid_ids


def _enrich_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    payload["evidence_id"] = str(payload.get("evidence_id") or payload.get("id") or "")
    payload["finding_id"] = str(payload.get("finding_id") or payload.get("linked_finding_id") or "")
    payload["rule_id"] = str(payload.get("rule_id") or payload.get("source_rule_id") or "")
    payload["unit_key"] = str(payload.get("unit_key") or payload.get("unit_id") or "")
    _normalize_evidence_rid_fields(payload)
    return payload


def project_evidences(run: GNCReviewRun) -> list[dict[str, Any]]:
    if run.result and run.result.evidence:
        return [_enrich_evidence_item(item) for item in run.result.evidence if isinstance(item, dict)]
    committee = _committee_payload(run)
    evidences = committee.get("evidences") or []
    return [_enrich_evidence_item(item) for item in evidences if isinstance(item, dict)]


def _requires_arbitration(run: GNCReviewRun) -> bool:
    status = run.status.value if isinstance(run.status, GNCReviewStatus) else str(run.status)
    if status == GNCReviewStatus.ARBITRATION_PENDING.value:
        return True
    decision = _chief_payload(run)
    if decision.get("requires_arbitration"):
        return True
    arbitration = _arbitration_payload(run)
    return bool(arbitration.get("requires_arbitration"))


def build_workbench_metrics(run: GNCReviewRun) -> WorkbenchMetrics:
    rid_items = project_rid_items(run)
    open_rids = [
        item for item in rid_items if str(item.get("status", "open")).lower() in {"open", "pending", "reopened"}
    ]
    committee = _committee_payload(run)
    conflicts = committee.get("conflicts") or []
    if run.result and run.result.conflicts:
        conflict_count = len(run.result.conflicts)
    else:
        conflict_count = len(conflicts)
    findings = project_findings(run)
    check_item_count = len(findings)
    issue_stats = compute_workbench_issue_summary(
        findings,
        review_mode="gnc",
        cross_doc_items=project_cross_document(run),
        total_check_items=check_item_count,
        open_rid_count=len(open_rids),
    )
    return WorkbenchMetrics(
        finding_count=issue_stats["problem_count"],
        problem_count=issue_stats["problem_count"],
        check_item_count=issue_stats["check_item_count"],
        pending_confirm=issue_stats["pending_confirm"],
        rid_count=len(rid_items),
        open_rid_count=len(open_rids),
        evidence_count=len(project_evidences(run)),
        conflict_count=conflict_count,
        requires_arbitration=_requires_arbitration(run),
    )


def build_workbench_summary(run: GNCReviewRun) -> WorkbenchSummary:
    decision = _chief_payload(run)
    arbitration = _arbitration_payload(run)
    report_markdown = ""
    if run.result:
        report_markdown = run.result.report_markdown or ""
    return WorkbenchSummary(
        verdict=str(decision.get("verdict") or ""),
        rationale=str(decision.get("rationale") or ""),
        requires_arbitration=_requires_arbitration(run),
        arbitration_status=str(arbitration.get("arbitration_status") or ""),
        report_available=bool(report_markdown.strip()),
    )


def _build_conclusion_overview(run: GNCReviewRun) -> WorkbenchConclusionOverview:
    chief = _chief_payload(run)
    summary = build_workbench_summary(run)
    committee = _committee_payload(run)
    scope = _resolve_review_scope(committee, run)
    payload = project_decision(run)
    return WorkbenchConclusionOverview(
        headline_verdict=str(payload.get("headline_verdict") or chief.get("verdict") or summary.verdict),
        one_line_conclusion=str(payload.get("one_line_conclusion") or ""),
        verdict_label_zh=str(payload.get("verdict_label_zh") or ""),
        rationale_zh=str(payload.get("rationale_zh") or ""),
        issue_buckets=dict(payload.get("issue_buckets") or {}),
        bucket_labels=dict(payload.get("bucket_labels") or {}),
        review_scope=dict(payload.get("review_scope") or {}),
        priority_items=list(payload.get("priority_items") or []),
        coverage_summary=dict(payload.get("coverage_summary") or {}),
    )


def build_workbench_detail(run: GNCReviewRun) -> UnifiedReviewWorkbenchDetail:
    status = run.status.value if isinstance(run.status, GNCReviewStatus) else str(run.status)
    completed_steps = _gnc_completed_steps(run)
    requires_arbitration = _requires_arbitration(run)
    summary = build_workbench_summary(run)
    conclusion = _build_conclusion_overview(run)
    summary.headline_verdict = conclusion.headline_verdict
    summary.one_line_conclusion = conclusion.one_line_conclusion
    summary.review_mode_label = conclusion.review_scope.get("review_mode_label", "")
    summary.verdict_label_zh = conclusion.verdict_label_zh or summary.verdict_label_zh
    summary.rationale_zh = conclusion.rationale_zh or summary.rationale_zh
    return UnifiedReviewWorkbenchDetail(
        review_id=run.review_id,
        name=run.name,
        review_type=ReviewType.GNC,
        status=status,
        workbench_phase=map_gnc_status_to_phase(
            status,
            current_step=run.current_step,
            completed_steps=completed_steps,
        ),
        visible_tabs=resolve_gnc_visible_tabs(
            status=status,
            current_step=run.current_step,
            completed_steps=completed_steps,
            requires_arbitration=requires_arbitration,
            report_available=summary.report_available,
        ),
        current_step=run.current_step,
        metrics=build_workbench_metrics(run),
        summary=summary,
        conclusion_overview=conclusion,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def paginate_events(events: list[dict[str, Any]], *, page: int, size: int) -> tuple[list[dict[str, Any]], int]:
    safe_page = max(page, 1)
    safe_size = max(min(size, 200), 1)
    total = len(events)
    start = (safe_page - 1) * safe_size
    end = start + safe_size
    return events[start:end], total


def _replace_rid_items(run: GNCReviewRun, rid_items: list[dict[str, Any]]) -> None:
    editorial_step = _as_dict((run.step_outputs or {}).setdefault("editorial_synthesis", {}))
    editorial_payload = editorial_step.setdefault("editorial_synthesis", {})
    if not isinstance(editorial_payload, dict):
        editorial_payload = {}
        editorial_step["editorial_synthesis"] = editorial_payload
    editorial_payload["rid_items"] = rid_items
    editorial_step["rid_items"] = rid_items

    if run.result is None:
        return
    if not isinstance(run.result.editorial_synthesis, dict):
        run.result.editorial_synthesis = {}
    run.result.editorial_synthesis["rid_items"] = rid_items


def apply_arbitration(run: GNCReviewRun, payload: GNCArbitrationRequest) -> dict[str, Any]:
    arbitration = _arbitration_payload(run)
    updated = {
        **arbitration,
        "arbitration_status": payload.status,
        "human_decisions": payload.decisions,
        "notes": payload.notes,
        "resolved": payload.status in {"resolved", "completed"},
    }

    if run.result is None:
        run.result = GNCReviewResult(review_id=run.review_id, status=run.status)
    run.result.arbitration = updated

    human_step = _as_dict((run.step_outputs or {}).setdefault("human_arbitration", {}))
    human_step.update(updated)
    human_step["requires_arbitration"] = not updated["resolved"]

    if updated["resolved"]:
        run.status = GNCReviewStatus.COMPLETED
        if isinstance(run.result, GNCReviewResult):
            run.result.status = GNCReviewStatus.COMPLETED
    else:
        run.status = GNCReviewStatus.ARBITRATION_PENDING
        if isinstance(run.result, GNCReviewResult):
            run.result.status = GNCReviewStatus.ARBITRATION_PENDING

    chief = _chief_payload(run)
    if chief:
        chief["requires_arbitration"] = not updated["resolved"]
        chief_step = _as_dict((run.step_outputs or {}).setdefault("chief_adjudication", {}))
        chief_step["chief_decision"] = chief
        if run.result:
            run.result.chief_decision = chief

    return updated


def _resolve_step_status(
    run: GNCReviewRun,
    step_key: str,
    *,
    completed: set[str],
    normalized_status: str,
) -> str:
    if step_key in completed:
        return "completed"
    if normalized_status == GNCReviewStatus.FAILED.value and run.current_step == step_key:
        return "failed"
    if run.current_step == step_key and normalized_status == GNCReviewStatus.RUNNING.value:
        return "running"
    if run.current_step == step_key:
        return "running"
    return "pending"


def _step_subtitle(step_key: str, output: dict[str, Any]) -> str:
    if step_key == "document_structuring":
        section_count = output.get("section_count")
        evidence_count = output.get("evidence_count")
        if section_count is not None:
            return f"{section_count} 章节 · {evidence_count or 0} 条证据"
    if step_key == "quality_screening":
        return str(output.get("gate_summary") or output.get("gate_status") or "")
    if step_key == "committee_review":
        finding_count = len(output.get("findings") or [])
        if finding_count:
            return f"{finding_count} 条发现"
    if step_key == "human_arbitration":
        items = output.get("arbitration_items") or []
        if items:
            return f"{len(items)} 项待确认"
    return str(output.get("summary") or output.get("status") or "")


def _step_duration_ms(step_key: str, output: dict[str, Any], events: list[dict[str, Any]]) -> int | None:
    for key in ("duration_ms", "elapsed_ms", "latency_ms"):
        value = output.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    started_at = output.get("started_at")
    finished_at = output.get("finished_at") or output.get("completed_at")
    if started_at and finished_at:
        return None
    event_prefix = f"{step_key}_"
    step_events = [
        event
        for event in events
        if isinstance(event, dict) and str(event.get("type", "")).startswith(event_prefix)
    ]
    if not step_events:
        return None
    payload = step_events[-1].get("payload") or {}
    if isinstance(payload, dict):
        value = payload.get("duration_ms") or payload.get("elapsed_ms")
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


def project_flow(run: GNCReviewRun) -> dict[str, Any]:
    completed = _gnc_completed_steps(run)
    status = run.status.value if isinstance(run.status, GNCReviewStatus) else str(run.status)
    events = list(run.events or [])
    steps = []
    for step_key in GNC_WORKFLOW_STEPS:
        output = _as_dict((run.step_outputs or {}).get(step_key))
        step_status = _resolve_step_status(run, step_key, completed=completed, normalized_status=status)
        related_tab = GNC_STEP_TO_TAB.get(step_key)
        steps.append(
            {
                "step_key": step_key,
                "label": GNC_STEP_LABELS.get(step_key, step_key),
                "status": step_status,
                "completed": step_key in completed,
                "is_current": run.current_step == step_key,
                "related_tab": related_tab.value if related_tab else "overview",
                "duration_ms": _step_duration_ms(step_key, output, events),
                "error": str(output.get("error") or "")
                or (run.error if step_status == "failed" and run.current_step == step_key else ""),
                "subtitle": _step_subtitle(step_key, output),
            }
        )
    requires_arbitration = _requires_arbitration(run)
    workbench_phase = map_gnc_status_to_phase(
        status,
        current_step=run.current_step,
        completed_steps=completed,
    )
    return {
        "review_id": run.review_id,
        "status": status,
        "current_step": run.current_step,
        "workbench_phase": workbench_phase.value,
        "requires_arbitration": requires_arbitration,
        "failed_step": run.current_step if status == GNCReviewStatus.FAILED.value else "",
        "error": run.error,
        "steps": steps,
    }


def project_materials(run: GNCReviewRun) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    if run.request and run.request.documents:
        documents = [doc.model_dump(mode="json") for doc in run.request.documents]
    intake = _as_dict((run.step_outputs or {}).get("review_intake"))
    enriched: list[dict[str, Any]] = []
    for index, document in enumerate(documents):
        metadata = _as_dict(document.get("metadata"))
        content = str(document.get("content") or "")
        role = str(metadata.get("role") or document.get("document_type") or "design_document")
        parse_status = str(metadata.get("parse_status") or ("parsed" if content.strip() else "pending"))
        enriched.append(
            {
                **document,
                "material_id": str(metadata.get("material_id") or document.get("name") or f"doc-{index + 1}"),
                "name": str(document.get("name") or metadata.get("filename") or f"材料 {index + 1}"),
                "role": role,
                "parse_status": parse_status,
                "role_confirmed": metadata.get("role_confirmed", True),
                "blocking": metadata.get("blocking", False),
                "warnings": metadata.get("warnings") or [],
            }
        )
    if intake.get("documents"):
        for item in intake.get("documents") or []:
            if isinstance(item, dict) and item.get("name") and not any(doc.get("name") == item.get("name") for doc in enriched):
                enriched.append(
                    {
                        **item,
                        "material_id": str(item.get("material_id") or item.get("name")),
                        "role": str(item.get("role") or item.get("document_type") or "unknown"),
                        "parse_status": str(item.get("parse_status") or "parsed"),
                        "role_confirmed": item.get("role_confirmed", True),
                        "blocking": item.get("blocking", False),
                        "warnings": item.get("warnings") or [],
                    }
                )
    return enriched


def project_gatekeeping(run: GNCReviewRun) -> dict[str, Any]:
    quality = _as_dict((run.step_outputs or {}).get("quality_screening"))
    intake = _as_dict((run.step_outputs or {}).get("review_intake"))
    base = {
        "gate_status": "passed",
        "can_start_review": True,
        "gate_summary": "GNC 送审包已接收",
        "blocking_reasons": [],
        "warnings": [],
        "missing_materials": [],
        "material_count": len(run.request.documents) if run.request else 0,
        "review_scope": run.request.review_scope if run.request else "",
        "review_phase": run.request.review_phase if run.request else "",
    }
    if intake:
        base["material_count"] = intake.get("document_count") or base["material_count"]
        base["warnings"] = list(intake.get("warnings") or base["warnings"])
    if quality:
        return {
            **base,
            "gate_status": quality.get("gate_status") or base["gate_status"],
            "can_start_review": quality.get("can_start_review", base["can_start_review"]),
            "gate_summary": quality.get("gate_summary") or quality.get("summary") or base["gate_summary"],
            "blocking_reasons": list(
                quality.get("blocking_reasons") or quality.get("blockers") or base["blocking_reasons"]
            ),
            "warnings": list(quality.get("warnings") or base["warnings"]),
            "missing_materials": list(
                quality.get("missing_materials") or quality.get("missing_slots") or base["missing_materials"]
            ),
        }
    return base


def project_report(run: GNCReviewRun) -> dict[str, Any] | None:
    if not run.result:
        return None
    markdown = _build_gnc_user_report_markdown(run)
    if not markdown.strip():
        markdown = run.result.report_markdown or ""
    if not markdown.strip():
        return None
    return {"markdown": markdown, "review_id": run.review_id, "status": run.result.status.value}


def _gnc_structured_bundle(run: GNCReviewRun) -> dict[str, Any]:
    intake = _as_dict((run.step_outputs or {}).get("intake"))
    committee = _committee_payload(run)
    documents = _as_list(intake.get("documents"))
    materials: list[dict[str, Any]] = []
    for doc in documents:
        item = _as_dict(doc)
        if not item:
            continue
        materials.append(
            {
                "name": item.get("file_name") or item.get("name") or "",
                "role": item.get("role") or item.get("document_role") or "",
                "file_type": item.get("file_type") or "",
            }
        )
    evidences = _as_list(committee.get("evidences"))
    return {
        "materials": materials,
        "evidence_pool": {"evidences": evidences},
        "stats": {
            "document_count": len(materials),
            "evidence_count": len(evidences),
            "finding_count": len(_as_list(committee.get("findings"))),
        },
        "warnings": [],
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _build_gnc_user_report_markdown(run: GNCReviewRun) -> str:
    if not run.result:
        return ""
    from data_agent.reporting import ReviewReportInput, build_review_report
    from data_agent.review_workbench.workbench_report_snapshot import detail_to_report_snapshot

    intake = _as_dict((run.step_outputs or {}).get("intake"))
    quality = _as_dict((run.step_outputs or {}).get("quality_screening"))
    structuring = _as_dict((run.step_outputs or {}).get("document_structuring"))
    struct_data = _as_dict(structuring.get("struct_data"))
    workbench_detail = build_workbench_detail(run)
    workbench_overview = detail_to_report_snapshot(workbench_detail)
    artifact = build_review_report(
        ReviewReportInput(
            report_id=f"gnc-{run.review_id}",
            review_type="gnc_review",
            audience="user",
            structured_bundle={
                **_gnc_structured_bundle(run),
                "extracted_parameters": _as_list(struct_data.get("extracted_parameters")),
                "design_elements": _as_list(struct_data.get("design_elements")),
            },
            review_results={"gnc_review_result": run.result.model_dump(mode="json")},
            quality_report={
                **(run.result.quality_scores if isinstance(run.result.quality_scores, dict) else {}),
                "template_gatekeeping": quality.get("template_gatekeeping"),
                "package_gatekeeping": quality.get("package_gatekeeping"),
                "is_reviewable": quality.get("is_reviewable"),
                "missing_items": quality.get("missing_items"),
                "warnings": quality.get("warnings"),
            },
            metadata={
                "title": "GNC 设计文档审查报告",
                "review_id": run.review_id,
                "product_model": run.request.product_model if run.request else "",
                "review_phase": run.request.review_phase if run.request else "",
                "review_scope": run.request.review_scope if run.request else "",
                "objective": intake.get("name") or run.name or "",
                "verdict": workbench_detail.summary.verdict,
                "rationale": workbench_detail.summary.rationale,
                "workbench_overview": workbench_overview,
            },
        )
    )
    from data_agent.review_workbench.issue_taxonomy import localize_report_markdown

    return localize_report_markdown(artifact.markdown)


def project_traceability(run: GNCReviewRun) -> dict[str, Any] | None:
    return None


def project_cross_document(run: GNCReviewRun) -> list[dict[str, Any]]:
    if run.result and run.result.conflicts:
        return [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in run.result.conflicts
            if isinstance(item, (dict,)) or hasattr(item, "model_dump")
        ]
    committee = _committee_payload(run)
    return [item for item in (committee.get("conflicts") or []) if isinstance(item, dict)]


def patch_rid_item(run: GNCReviewRun, rid_id: str, payload: GNCRidPatchRequest) -> dict[str, Any] | None:
    rid_items = project_rid_items(run)
    target: dict[str, Any] | None = None
    for item in rid_items:
        if str(item.get("rid_id")) == rid_id:
            target = item
            break
    if target is None:
        return None

    if payload.status is not None:
        target["status"] = payload.status
    if payload.notes is not None:
        target["notes"] = payload.notes
    if payload.comment is not None:
        target["comment"] = payload.comment

    _replace_rid_items(run, rid_items)
    return target
