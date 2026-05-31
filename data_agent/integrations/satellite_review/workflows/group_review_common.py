"""Shared helpers for AD/AC group review sub-workflows (minimal source-equivalent skeleton)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from data_agent.core.domain_registry import review_units_for_domain
from data_agent.integrations.satellite_review.review_units import run_unit_review

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"info": 0, "suggestion": 1, "minor": 2, "major": 3, "critical": 4}


@dataclass
class StageRunResult:
    stage_key: str
    unit_id: str
    unit_key: str
    unit_name: str
    status: str
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    rule_results: list[dict[str, Any]] = field(default_factory=list)
    rule_judgments: list[dict[str, Any]] = field(default_factory=list)
    is_blocked: bool = False
    knowledge_gap: bool = False
    confidence: float = 0.0
    execution: str = "deterministic"
    blocking_flags: list[str] = field(default_factory=list)


def _rule_result_to_judgment(item: dict[str, Any]) -> str:
    if str(item.get("execution_status") or "") == "not_checked":
        return "not_checked"
    if str(item.get("execution_status") or "") == "insufficient_evidence":
        return "insufficient_evidence"
    if item.get("passed"):
        return "satisfied"
    if not item.get("evidence_refs"):
        return "insufficient_evidence"
    return "not_satisfied"


def _expected_rules_for_unit(
    unit_id: str,
    unit_name: str,
    knowledge_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve the full rule set for a unit (template / registry unit spec)."""
    from data_agent.integrations.satellite_review.review_units import _resolve_unit_spec_for_review

    catalog = review_units_for_domain("aerospace_review")
    quality_data = knowledge_data.get("quality_data") or {}
    unit_spec = _resolve_unit_spec_for_review(unit_id, unit_name, quality_data, catalog)
    rules: list[dict[str, Any]] = []
    for rule in unit_spec.get("rules") or []:
        if isinstance(rule, dict) and str(rule.get("rule_id") or "").strip():
            rules.append(rule)
    return rules


def _supplement_not_checked_rules(
    rule_results: list[dict[str, Any]],
    rule_judgments: list[dict[str, Any]],
    expected_rules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Mark template rules that never entered rule_results as not_checked (source parity)."""
    if not expected_rules:
        return rule_results, rule_judgments

    executed_ids = {
        str(item.get("rule_id") or "").strip()
        for item in rule_results
        if isinstance(item, dict) and str(item.get("rule_id") or "").strip()
    }
    supplemented_results = list(rule_results)
    supplemented_judgments = list(rule_judgments)
    for rule in expected_rules:
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id or rule_id in executed_ids:
            continue
        rule_text = str(rule.get("rule_text") or rule.get("rule_desc") or rule_id)
        rationale = "该规则未进入确定性或 LLM 执行路径，记为 not_checked。"
        supplemented_results.append(
            {
                "rule_id": rule_id,
                "rule_desc": rule_text,
                "rule_text": rule_text,
                "passed": False,
                "reasoning": rationale,
                "evidence_refs": [],
                "execution_status": "not_checked",
            }
        )
        supplemented_judgments.append(
            {
                "rule_id": rule_id,
                "rule_text": rule_text,
                "judgment": "not_checked",
                "rationale": rationale,
                "evidence_ids": [],
                "related_issue_ids": [],
            }
        )
    return supplemented_results, supplemented_judgments


def _build_rule_judgments(rule_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    judgments: list[dict[str, Any]] = []
    for item in rule_results:
        if not isinstance(item, dict):
            continue
        judgments.append(
            {
                "rule_id": item.get("rule_id", ""),
                "rule_text": item.get("rule_desc") or item.get("rule_text") or "",
                "judgment": _rule_result_to_judgment(item),
                "rationale": item.get("reasoning", ""),
                "evidence_ids": list(item.get("evidence_refs") or []),
                "related_issue_ids": [],
            }
        )
    return judgments


def _stage_status_from_review(review: dict[str, Any]) -> str:
    raw = str(review.get("status") or "degraded")
    if raw == "placeholder":
        return "placeholder"
    if raw in {"ok", "completed"}:
        return "completed"
    if raw == "failed":
        return "blocked"
    return "completed" if review.get("completed", True) else "blocked"


def _run_one_stage(
    stage_key: str,
    unit_id: str,
    *,
    knowledge_data: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    model_id: str | None,
    debug_mode: bool,
    matched_signals: list[str] | None = None,
) -> StageRunResult:
    catalog = review_units_for_domain("aerospace_review")
    payload = catalog.get(unit_id, {})
    unit_name = str(payload.get("name") or unit_id)
    unit = {
        "unit_id": unit_id,
        "unit_name": unit_name,
        "unit_group": str(payload.get("unit_group") or ""),
        "matched_signals": matched_signals or [],
    }
    _, review, findings = run_unit_review(
        unit,
        knowledge_data,
        evidence_map,
        model_id=model_id,
        debug_mode=debug_mode,
    )
    rule_results = [item for item in (review.get("rule_results") or []) if isinstance(item, dict)]
    expected_rules = _expected_rules_for_unit(unit_id, unit_name, knowledge_data)
    rule_results, rule_judgments = _supplement_not_checked_rules(
        rule_results,
        _build_rule_judgments(rule_results),
        expected_rules,
    )
    blocking_flags: list[str] = []
    if review.get("execution") == "blocked":
        blocking_flags.append(f"{stage_key}:gatekeeping_blocked")
    if any(j.get("judgment") == "not_checked" for j in rule_judgments):
        blocking_flags.append(f"{stage_key}:not_checked_rules")

    return StageRunResult(
        stage_key=stage_key,
        unit_id=unit_id,
        unit_key=unit_id,
        unit_name=unit_name,
        status=_stage_status_from_review(review),
        summary=str(review.get("summary") or ""),
        findings=list(findings or []),
        rule_results=rule_results,
        rule_judgments=rule_judgments,
        is_blocked=bool(review.get("is_blocked")) or review.get("execution") == "blocked",
        knowledge_gap=bool(review.get("knowledge_gap")),
        confidence=float(review.get("confidence") or 0.0),
        execution=str(review.get("execution") or "deterministic"),
        blocking_flags=blocking_flags,
    )


def _run_stages_parallel(
    stage_items: list[tuple[str, str, list[str] | None]],
    *,
    run_stage: Callable[..., StageRunResult],
    max_workers: int,
) -> list[StageRunResult]:
    if not stage_items:
        return []
    if max_workers <= 1 or len(stage_items) == 1:
        return [
            run_stage(stage_key, unit_id, matched_signals=signals)
            for stage_key, unit_id, signals in stage_items
        ]

    results: list[StageRunResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(run_stage, stage_key, unit_id, matched_signals=signals): stage_key
            for stage_key, unit_id, signals in stage_items
        }
        for future in as_completed(futures):
            stage_key = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                logger.exception("[GroupReview] stage %s failed: %s", stage_key, exc)
                results.append(
                    StageRunResult(
                        stage_key=stage_key,
                        unit_id="",
                        unit_key="",
                        unit_name=stage_key,
                        status="blocked",
                        summary=f"环节执行异常: {exc}",
                        knowledge_gap=True,
                        blocking_flags=[f"{stage_key}:runtime_error"],
                    )
                )
    order = {stage_key: index for index, (stage_key, _, _) in enumerate(stage_items)}
    results.sort(key=lambda item: order.get(item.stage_key, 999))
    return results


def _finding_to_group_dict(finding: dict[str, Any], *, group: str, stage_key: str) -> dict[str, Any]:
    severity = str(finding.get("severity") or "minor")
    return {
        "finding_id": finding.get("finding_id") or finding.get("issue_id") or "",
        "agent_id": finding.get("agent_id") or f"{group}_{stage_key}_reviewer",
        "discipline": finding.get("discipline") or f"{group}_{stage_key}",
        "title": finding.get("title") or finding.get("issue_type") or "",
        "description": finding.get("description") or "",
        "severity": severity,
        "evidence_ids": list(finding.get("evidence_ids") or finding.get("evidence_refs") or []),
        "recommendation": finding.get("recommendation") or "",
        "judgment": finding.get("judgment") or "",
        "source_text": finding.get("source_text") or "",
        "metadata": {
            **(finding.get("metadata") or {}),
            "group": group,
            "stage_key": stage_key,
            "source": "group_sub_workflow",
        },
    }


def _build_stage_coverage(stage_results: list[StageRunResult]) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    for stage in stage_results:
        high_risk = any(
            str(f.get("severity") or "") in {"critical", "major", "high"}
            for f in stage.findings
        )
        coverage.append(
            {
                "stage": stage.stage_key,
                "stage_label": stage.stage_key,
                "completed": stage.status == "completed",
                "has_high_risk": high_risk,
                "is_closed_loop": not stage.knowledge_gap,
                "finding_count": len(stage.findings),
                "blocking_count": sum(1 for flag in stage.blocking_flags if flag),
            }
        )
    return coverage


def _build_chief_merge(
    *,
    group_label: str,
    stage_results: list[StageRunResult],
    all_findings: list[dict[str, Any]],
    blocking_flags: list[str],
) -> dict[str, Any]:
    failed_rule_checks = sum(
        1
        for stage in stage_results
        for judgment in stage.rule_judgments
        if judgment.get("judgment") == "not_satisfied"
    )
    insufficient_rule_checks = sum(
        1
        for stage in stage_results
        for judgment in stage.rule_judgments
        if judgment.get("judgment") == "insufficient_evidence"
    )
    not_checked_rule_checks = sum(
        1
        for stage in stage_results
        for judgment in stage.rule_judgments
        if judgment.get("judgment") == "not_checked"
    )
    blocking_count = len(blocking_flags)
    if blocking_count > 0 or failed_rule_checks > 0:
        verdict = "rejected"
    elif insufficient_rule_checks > 0 or not_checked_rule_checks > 0:
        verdict = "conditionally_approved"
    else:
        verdict = "approved"

    key_risks = [
        f"{stage.stage_key} 不满足 {sum(1 for j in stage.rule_judgments if j.get('judgment') == 'not_satisfied')} 条"
        for stage in stage_results
        if any(j.get("judgment") == "not_satisfied" for j in stage.rule_judgments)
    ][:5]

    deterministic_checked = sum(
        1
        for stage in stage_results
        for item in stage.rule_results
        if str(item.get("execution_status") or "") == "deterministic_checked"
    )
    llm_checked = sum(
        1
        for stage in stage_results
        for item in stage.rule_results
        if str(item.get("execution_status") or "") == "llm_checked"
    )

    summary = (
        f"{group_label} 共完成 {len(stage_results)} 个环节，形成 {len(all_findings)} 条审查记录；"
        f"关重标记 {blocking_count} 项，规则不满足 {failed_rule_checks} 条，"
        f"证据不足 {insufficient_rule_checks} 条，未检查 {not_checked_rule_checks} 条。"
    )

    return {
        "verdict": verdict,
        "total_findings": len(all_findings),
        "blocking_findings": blocking_count,
        "high_risk_findings": sum(
            1 for f in all_findings if str(f.get("severity") or "") in {"critical", "major", "high"}
        ),
        "total_rule_checks": sum(len(stage.rule_judgments) for stage in stage_results),
        "failed_rule_checks": failed_rule_checks,
        "insufficient_rule_checks": insufficient_rule_checks,
        "not_checked_rule_checks": not_checked_rule_checks,
        "llm_checked_rule_checks": llm_checked,
        "deterministic_checked_rule_checks": deterministic_checked,
        "key_risks": key_risks,
        "conflict_resolutions": [],
        "stage_coverage": _build_stage_coverage(stage_results),
        "summary": summary,
        "follow_up_actions": [
            "优先闭环 not_satisfied 规则并补充整改证据",
            "对 insufficient_evidence 与 not_checked 规则补充可追溯证据并复审",
        ],
        "chief_merge_mode": "deterministic",
        "merged_at": datetime.now().isoformat(),
    }


def _build_unit_results(stage_results: list[StageRunResult]) -> list[dict[str, Any]]:
    unit_results: list[dict[str, Any]] = []
    for stage in stage_results:
        unit_results.append(
            {
                "unit_key": stage.unit_id,
                "unit_name": stage.unit_name,
                "agent_id": stage.unit_id,
                "stage_key": stage.stage_key,
                "status": stage.status,
                "execution": stage.execution,
                "rule_results": [
                    {
                        **item,
                        "judgment": next(
                            (
                                judgment.get("judgment")
                                for judgment in stage.rule_judgments
                                if judgment.get("rule_id") == item.get("rule_id")
                            ),
                            _rule_result_to_judgment(item),
                        ),
                    }
                    for item in stage.rule_results
                ]
                or stage.rule_judgments,
                "summary": stage.summary,
                "is_blocked": stage.is_blocked,
                "confidence": stage.confidence,
                "evidence_ids": sorted(
                    {
                        ev
                        for finding in stage.findings
                        for ev in (finding.get("evidence_ids") or [])
                        if ev
                    }
                ),
                "findings": [
                    {
                        "finding_id": finding.get("finding_id", ""),
                        "unit_key": stage.unit_id,
                        "severity": finding.get("severity", ""),
                        "description": finding.get("description", ""),
                        "evidence_refs": finding.get("evidence_ids") or [],
                        "recommendation": finding.get("recommendation", ""),
                    }
                    for finding in stage.findings
                ],
            }
        )
    return unit_results


def run_group_review_pipeline(
    *,
    group: str,
    group_label: str,
    stage_plan: list[tuple[list[tuple[str, str, list[str] | None]], int]],
    knowledge_data: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    model_id: str | None = None,
    debug_mode: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Execute staged unit reviews and return findings, group review, native payload, unit_results."""
    quality_data = knowledge_data.get("quality_data") or {}
    selected_map = {
        str(item.get("unit_id") or ""): item
        for item in (quality_data.get("selected_units") or [])
        if isinstance(item, dict) and item.get("unit_id")
    }

    def _run_stage(stage_key: str, unit_id: str, matched_signals: list[str] | None = None) -> StageRunResult:
        signals = matched_signals
        if not signals and unit_id in selected_map:
            signals = list(selected_map[unit_id].get("matched_signals") or [])
        return _run_one_stage(
            stage_key,
            unit_id,
            knowledge_data=knowledge_data,
            evidence_map=evidence_map,
            model_id=model_id,
            debug_mode=debug_mode,
            matched_signals=signals,
        )

    stage_results: list[StageRunResult] = []
    blocking_flags: list[str] = []
    for phase_items, max_workers in stage_plan:
        phase_results = _run_stages_parallel(
            phase_items,
            run_stage=_run_stage,
            max_workers=max_workers,
        )
        stage_results.extend(phase_results)
        for stage in phase_results:
            blocking_flags.extend(stage.blocking_flags)

    all_findings = [
        _finding_to_group_dict(finding, group=group, stage_key=stage.stage_key)
        for stage in stage_results
        for finding in stage.findings
    ]
    conclusion = _build_chief_merge(
        group_label=group_label,
        stage_results=stage_results,
        all_findings=all_findings,
        blocking_flags=blocking_flags,
    )
    unit_results = _build_unit_results(stage_results)
    conclusion["rule_coverage_summary"] = {
        "llm_checked": conclusion.get("llm_checked_rule_checks", 0),
        "deterministic_checked": conclusion.get("deterministic_checked_rule_checks", 0),
        "not_checked": conclusion.get("not_checked_rule_checks", 0),
    }
    conclusion["stage_rule_judgments"] = {
        stage.stage_key: stage.rule_judgments for stage in stage_results if stage.rule_judgments
    }
    conclusion["unit_results"] = unit_results
    conclusion["blocking_flags"] = blocking_flags
    conclusion["stage_results"] = {
        stage.stage_key: {
            "status": stage.status,
            "summary": stage.summary,
            "finding_count": len(stage.findings),
            "rule_judgment_count": len(stage.rule_judgments),
            "knowledge_gap": stage.knowledge_gap,
            "execution": stage.execution,
        }
        for stage in stage_results
    }

    group_review = {
        "discipline": f"{group}_group",
        "reviewer": group_label,
        "score": float(conclusion.get("confidence_score") or 0.0),
        "summary": conclusion.get("summary", ""),
        "completed": True,
        "verdict": conclusion.get("verdict", "pending"),
    }
    native_result = {
        "conclusion": conclusion,
        "stage_coverage": conclusion.get("stage_coverage", []),
        "unit_results": unit_results,
        "stage_results": conclusion.get("stage_results", {}),
        "blocking_flags": blocking_flags,
    }
    return all_findings, group_review, native_result, unit_results
