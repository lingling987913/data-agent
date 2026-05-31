"""RID candidate, conflict detection, and arbitration scoring for GNC review."""

from __future__ import annotations

import json
import re
from typing import Any

_ARBITRATION_SCORE_GAP = 0.12

_AD_STAGE_LABELS = {
    "req_err": "需求确认与误差分解",
    "timing": "采集时序设计",
    "install": "执行机构布局/安装设计",
    "algorithm": "控制律/算法设计",
    "simulation": "姿控仿真",
}

_AC_STAGE_LABELS = {
    "thruster_layout": "推力器布局审查",
    "other_actuator_layout": "其他执行机构布局审查",
    "control_law": "控制律设计审查",
    "control_params": "姿控参数设计审查",
    "maneuver_law": "操纵律设计审查",
    "unloading_law": "卸载律设计审查",
    "simulation": "姿控仿真审查",
}

_AD_STAGE_TO_UNIT_KEY = {
    "req_err": "ad_req_err",
    "timing": "ad_timing",
    "install": "ad_install",
    "algorithm": "ad_algorithm",
    "simulation": "ad_simulation",
}

_AC_STAGE_TO_UNIT_KEY = {
    "req_err": "ac_req_err",
    "thruster_layout": "ac_thruster_layout",
    "other_actuator_layout": "ac_other_actuator_layout",
    "control_law": "ac_control_law",
    "control_params": "ac_control_params",
    "maneuver_law": "ac_maneuver_law",
    "unloading_law": "ac_unloading_law",
    "simulation": "ac_simulation",
}


def _clip_source_quote(value: str, limit: int = 360) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def build_trace_context(
    review_data: dict[str, Any],
) -> tuple[dict[str, dict], dict[str, dict], dict[tuple[str, str], dict]]:
    knowledge_data = review_data.get("knowledge_data", {}) or {}
    quality_data = knowledge_data.get("quality_data", {}) or {}
    bundles = (
        knowledge_data.get("unit_evidence_bundles", [])
        or quality_data.get("unit_evidence_bundles", [])
        or []
    )
    unit_bundle_map = {
        str(bundle.get("unit_key", "")): bundle
        for bundle in bundles
        if isinstance(bundle, dict) and bundle.get("unit_key")
    }
    evidence_map: dict[str, dict] = {}
    for ev in review_data.get("evidences", []) or []:
        if isinstance(ev, dict) and ev.get("evidence_id"):
            evidence_map[str(ev["evidence_id"])] = ev
    for bundle in unit_bundle_map.values():
        for ev in (bundle.get("primary_evidences", []) or []) + (
            bundle.get("supporting_evidences", []) or []
        ):
            if isinstance(ev, dict) and ev.get("evidence_id"):
                evidence_map[str(ev.get("evidence_id"))] = ev

    rule_result_map: dict[tuple[str, str], dict] = {}
    for unit in review_data.get("unit_results", []) or []:
        if not isinstance(unit, dict):
            continue
        unit_key = str(unit.get("unit_key", ""))
        for rule in unit.get("rule_results", []) or []:
            if isinstance(rule, dict) and rule.get("rule_id"):
                rule_result_map[(unit_key, str(rule.get("rule_id")))] = rule
    return unit_bundle_map, evidence_map, rule_result_map


def collect_rule_trace_fields(
    unit_key: str,
    item: dict[str, Any],
    rich_rule: dict[str, Any],
    unit_bundle: dict[str, Any],
    evidence_map: dict[str, dict],
    rule_result_map: dict[tuple[str, str], dict] | None = None,
) -> dict[str, Any]:
    evidence_ids = [
        str(ev_id)
        for ev_id in (
            item.get("evidence_ids")
            or item.get("evidence_refs")
            or rich_rule.get("evidence_refs")
            or []
        )
        if ev_id
    ]
    if not evidence_ids:
        evidence_ids = [
            str(ev.get("evidence_id"))
            for ev in unit_bundle.get("primary_evidences", [])[:2]
            if isinstance(ev, dict) and ev.get("evidence_id")
        ]
    sections: list[str] = []
    blocks: list[str] = []
    quotes: list[str] = []
    for ev_id in evidence_ids:
        ev = evidence_map.get(ev_id) or {}
        section_id = ev.get("section_id") or ev.get("source_section_id")
        if section_id and str(section_id) not in sections:
            sections.append(str(section_id))
        for block_id in ev.get("block_ids", []) or []:
            if block_id and str(block_id) not in blocks:
                blocks.append(str(block_id))
        quote = ev.get("excerpt") or ev.get("summary") or ev.get("quote") or ""
        if quote:
            quotes.append(_clip_source_quote(str(quote), 180))

    parameter_ids = [
        str(ref.get("parameter_id") or ref.get("source_parameter_id") or ref.get("id"))
        for ref in rich_rule.get("parameter_refs", []) or []
        if isinstance(ref, dict) and (ref.get("parameter_id") or ref.get("source_parameter_id") or ref.get("id"))
    ]
    if not parameter_ids:
        parameter_ids = [
            str(param.get("parameter_id"))
            for param in unit_bundle.get("extracted_parameters", [])[:4]
            if isinstance(param, dict) and param.get("parameter_id")
        ]
    trace_link_ids = [
        str(link.get("link_id"))
        for link in unit_bundle.get("trace_links", []) or unit_bundle.get("trace_link_candidates", []) or []
        if isinstance(link, dict) and link.get("link_id")
    ]
    rule_source_refs: list[dict] = []
    for source in (rich_rule.get("rule_source_refs"), rich_rule.get("source_refs"), item.get("source_refs")):
        if isinstance(source, dict):
            rule_source_refs.append(source)
        elif isinstance(source, list):
            rule_source_refs.extend(ref for ref in source if isinstance(ref, dict))
    if rule_result_map:
        rule_id = item.get("rule_id") or rich_rule.get("rule_id")
        if rule_id:
            rule_result = rule_result_map.get((unit_key, str(rule_id)), {}) or {}
            for source in (rule_result.get("rule_source_refs"), rule_result.get("source_refs")):
                if isinstance(source, dict):
                    rule_source_refs.append(source)
                elif isinstance(source, list):
                    rule_source_refs.extend(ref for ref in source if isinstance(ref, dict))
    seen_refs: set[tuple[str, str, str]] = set()
    unique_refs: list[dict] = []
    for ref in rule_source_refs:
        key = (
            str(ref.get("source_type", "")),
            str(ref.get("source_id", "")),
            str(ref.get("clause", "")),
        )
        if not any(key):
            key = ("ref", json.dumps(ref, ensure_ascii=False, sort_keys=True), "")
        if key not in seen_refs:
            seen_refs.add(key)
            unique_refs.append(ref)
    calculation = rich_rule.get("calculation") or item.get("calculation") or {}
    if rule_result_map:
        rule_id = item.get("rule_id") or rich_rule.get("rule_id")
        if rule_id:
            rule_result = rule_result_map.get((unit_key, str(rule_id)), {}) or {}
            if not calculation and rule_result.get("calculation"):
                calculation = rule_result.get("calculation") or {}
    parameter_refs = rich_rule.get("parameter_refs") or item.get("parameter_refs") or []
    if rule_result_map and not parameter_refs:
        rule_id = item.get("rule_id") or rich_rule.get("rule_id")
        if rule_id:
            rule_result = rule_result_map.get((unit_key, str(rule_id)), {}) or {}
            parameter_refs = rule_result.get("parameter_refs") or []
    return {
        "unit_key": unit_key,
        "evidence_ids": evidence_ids,
        "source_section_ids": sections,
        "source_evidence_ids": evidence_ids,
        "source_block_ids": blocks,
        "source_quote": _clip_source_quote("；".join(q for q in quotes if q)),
        "source_parameter_ids": parameter_ids,
        "source_trace_link_ids": trace_link_ids,
        "rule_source_refs": unique_refs,
        "calculation": calculation if isinstance(calculation, dict) else {},
        "parameter_refs": [ref for ref in parameter_refs if isinstance(ref, dict)],
    }


def collect_finding_trace_fields(finding: dict[str, Any], evidence_map: dict[str, dict]) -> dict[str, Any]:
    evidence_ids = _as_str_list(finding.get("source_evidence_ids") or finding.get("evidence_ids"))
    sections = _as_str_list(finding.get("source_section_ids"))
    blocks = _as_str_list(finding.get("source_block_ids"))
    quotes = _as_str_list(finding.get("source_quote") or finding.get("source_text"))
    for ev_id in evidence_ids:
        ev = evidence_map.get(ev_id) or {}
        section_id = ev.get("section_id") or ev.get("source_section_id")
        if section_id and str(section_id) not in sections:
            sections.append(str(section_id))
        for block_id in ev.get("block_ids", []) or []:
            if block_id and str(block_id) not in blocks:
                blocks.append(str(block_id))
        quote = ev.get("excerpt") or ev.get("summary") or ev.get("quote") or ""
        if quote:
            quotes.append(_clip_source_quote(str(quote), 180))
    rule_source_refs = finding.get("rule_source_refs") or finding.get("source_refs") or []
    if isinstance(rule_source_refs, dict):
        rule_source_refs = [rule_source_refs]
    return {
        "source_section_ids": sections,
        "source_evidence_ids": evidence_ids,
        "source_block_ids": blocks,
        "source_quote": _clip_source_quote("；".join(q for q in quotes if q)),
        "source_parameter_ids": _as_str_list(finding.get("source_parameter_ids") or finding.get("parameter_ids")),
        "source_trace_link_ids": _as_str_list(
            finding.get("source_trace_link_ids") or finding.get("trace_link_ids")
        ),
        "rule_source_refs": [ref for ref in rule_source_refs if isinstance(ref, dict)],
    }


def rule_judgment_from_result(rule: dict[str, Any]) -> str:
    judgment = str(rule.get("judgment", "") or "").strip().lower()
    if judgment:
        return judgment
    status = str(rule.get("execution_status", "") or "").strip().lower()
    if status == "insufficient_evidence":
        return "insufficient_evidence"
    if status == "not_checked":
        return "not_checked"
    if "passed" in rule:
        return "satisfied" if rule.get("passed") is True else "not_satisfied"
    return "not_checked"


def rule_source_evidence_ids(rule: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for raw in rule.get("evidence_refs", []) or rule.get("evidence_ids", []) or []:
        if raw:
            refs.append(str(raw))
    for param in rule.get("parameter_refs", []) or []:
        if isinstance(param, dict):
            evidence_id = str(param.get("source_evidence_id", "") or "")
            if evidence_id:
                refs.append(evidence_id)
    return sorted({item for item in refs if item})


def tool_trust_score(rule: dict[str, Any]) -> float:
    tool_calls = [item for item in rule.get("tool_calls", []) or [] if isinstance(item, dict)]
    if any(item.get("status") == "ok" and item.get("tool_type") in {"calculation", "simulation"} for item in tool_calls):
        return 1.0
    if str(rule.get("execution_status", "") or "") == "deterministic_checked":
        return 0.9
    if any(item.get("status") == "ok" for item in tool_calls):
        return 0.75
    if rule.get("calculation"):
        return 0.65
    return 0.25


def evidence_completeness_score(rule: dict[str, Any]) -> float:
    score = 0.0
    if rule_source_evidence_ids(rule):
        score += 0.35
    if rule.get("parameter_refs"):
        score += 0.25
    if rule.get("rule_source_refs"):
        score += 0.25
    if str(rule.get("support_status", "") or "").lower() == "sufficient":
        score += 0.15
    return min(score, 1.0)


def task_relevance_score(unit_key: str, agent_id: str, rule: dict[str, Any]) -> float:
    rule_id = str(rule.get("rule_id", "") or "").lower()
    unit = str(unit_key or "").lower()
    agent = str(agent_id or "").lower()
    if unit and unit in agent:
        return 0.9
    if unit.startswith("ad_") and ":ad_" in agent:
        return 0.8
    if unit.startswith("ac_") and ":ac_" in agent:
        return 0.8
    if rule_id.startswith("ad-") and ":ad_" in agent:
        return 0.8
    if rule_id.startswith("ac-") and ":ac_" in agent:
        return 0.8
    if any(token in agent for token in ("interface", "simulation", "fdir")):
        return 0.65
    return 0.5


def confidence_score(unit: dict[str, Any], rule: dict[str, Any]) -> float:
    raw = rule.get("confidence", unit.get("confidence", 0.0))
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    if value > 1.0:
        value = value / 100.0
    return max(0.0, min(value, 1.0))


def arbitration_score(unit: dict[str, Any], rule: dict[str, Any]) -> tuple[float, dict[str, float]]:
    unit_key = str(unit.get("unit_key", "") or "")
    agent_id = str(unit.get("agent_id", "") or "")
    components = {
        "confidence": confidence_score(unit, rule),
        "evidence_completeness": evidence_completeness_score(rule),
        "tool_trust": tool_trust_score(rule),
        "task_relevance": task_relevance_score(unit_key, agent_id, rule),
    }
    score = (
        0.15 * components["confidence"]
        + 0.35 * components["evidence_completeness"]
        + 0.35 * components["tool_trust"]
        + 0.15 * components["task_relevance"]
    )
    return round(score, 4), components


def _candidate_from_judgment_item(
    *,
    group_key: str,
    stage_key: str,
    stage_label: str,
    stage_unit_key: str,
    item: dict[str, Any],
    findings_by_id: dict[str, dict],
    stage_blocking_count: int,
    unit_bundle_map: dict[str, dict],
    evidence_map: dict[str, dict],
    rule_result_map: dict[tuple[str, str], dict],
) -> dict[str, Any] | None:
    judgment = str(item.get("judgment", "")).strip()
    if judgment not in ("not_satisfied", "insufficient_evidence"):
        return None

    rule_id = str(item.get("rule_id", "")).strip()
    rule_text = str(item.get("rule_text", "")).strip()
    rationale = str(item.get("rationale", "")).strip()
    claim_present = item.get("claim_present", None)
    claim_sufficient = item.get("claim_sufficient", None)
    rule_consistent = item.get("rule_consistent", None)
    support_status = str(item.get("support_status", "") or "").strip().lower()
    residual_uncertainty = str(item.get("residual_uncertainty", "") or "").strip()
    related_ids = [rid for rid in item.get("related_issue_ids", []) if rid in findings_by_id]
    linked_findings = [findings_by_id[rid] for rid in related_ids]
    linked_high_severity = any(f.get("severity") in ("critical", "major") for f in linked_findings)

    severity = "major" if judgment == "not_satisfied" else "minor"
    if stage_blocking_count > 0 or linked_high_severity:
        severity = "major"

    if judgment == "not_satisfied":
        if claim_present is False:
            description = f"{stage_label}未覆盖规则要求：{rule_text}"
        elif rule_consistent is False:
            description = f"{stage_label}已声明相关设计，但与规则要求不一致：{rule_text}"
        elif claim_sufficient is False:
            description = f"{stage_label}对该规则的设计说明不充分，未达到审查要求：{rule_text}"
        else:
            description = f"{stage_label}存在未满足规则项：{rule_text}"
    else:
        if claim_present is True and support_status in ("none", "weak"):
            description = f"{stage_label}已提出相关设计主张，但缺少充分支撑：{rule_text}"
        elif claim_sufficient is False:
            description = f"{stage_label}涉及该规则的说明不充分，当前无法确认满足性：{rule_text}"
        else:
            description = f"{stage_label}缺少支撑规则判定的充分证据：{rule_text}"

    basis_parts = [f"规则判定 {rule_id}: {rule_text}"]
    if rationale:
        basis_parts.append(rationale)
    if claim_present is not None:
        basis_parts.append(f"文档声明: {'已明确' if claim_present else '未明确'}")
    if claim_sufficient is not None:
        basis_parts.append(f"说明充分性: {'充分' if claim_sufficient else '不足'}")
    if rule_consistent is not None:
        basis_parts.append(f"规则一致性: {'一致' if rule_consistent else '不一致'}")
    if support_status:
        basis_parts.append(f"支撑强度: {support_status}")
    if residual_uncertainty:
        basis_parts.append(f"剩余不确定性: {residual_uncertainty}")

    rich_rule = rule_result_map.get((stage_unit_key, rule_id), {}) or {}
    if not rich_rule and item.get("source_refs"):
        rich_rule = {"source_refs": item.get("source_refs")}
    trace_fields = collect_rule_trace_fields(
        stage_unit_key,
        item,
        rich_rule,
        unit_bundle_map.get(stage_unit_key, {}) or {},
        evidence_map,
        rule_result_map,
    )
    evidence_ids = [str(ev_id) for ev_id in item.get("evidence_ids", []) if ev_id] or trace_fields["source_evidence_ids"]
    if evidence_ids:
        basis_parts.append(f"关联知识依据: {', '.join(evidence_ids[:6])}")
    if trace_fields.get("source_quote"):
        basis_parts.append(f"原文摘录: {trace_fields['source_quote']}")
    if related_ids:
        basis_parts.append(f"关联审查记录: {', '.join(related_ids[:6])}")

    recommendation = (
        "补充设计整改说明、重新核对规则阈值与论证链路，并在修订后重新提交审查。"
        if judgment == "not_satisfied"
        else (
            "补充能够支撑该设计主张的规范依据、分析过程、附件结果或交叉一致性证明，并重新提交审查。"
            if claim_present is True
            else "补充该规则要求对应的设计说明、分析过程或验证证据，并重新提交审查。"
        )
    )
    impact = (
        "规则未满足，可能直接影响该环节设计成立性、规范符合性与审查闭环。"
        if judgment == "not_satisfied"
        else (
            "存在未证实关键主张，当前无法确认该环节是否真实满足设计审查要求。"
            if claim_present is True
            else "证据不足，当前无法确认该环节是否满足设计审查要求。"
        )
    )
    return {
        "stage": stage_key,
        "stage_label": stage_label,
        "discipline": group_key,
        "rule_id": rule_id,
        "rule_text": rule_text,
        "judgment": judgment,
        "severity": severity,
        "description": description,
        "basis": "；".join(part for part in basis_parts if part),
        "impact": impact,
        "recommendation": recommendation,
        "related_finding_ids": related_ids,
        "evidence_ids": evidence_ids,
        "source_support_status": support_status,
        **trace_fields,
    }


def build_rule_rid_candidates(review_data: dict[str, Any], findings: list[dict]) -> list[dict]:
    """Extract RID candidates from AD/AC stage judgments and committee unit rule_results."""
    candidates: list[dict] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    unit_bundle_map, evidence_map, rule_result_map = build_trace_context(review_data)
    findings_by_id = {
        f.get("finding_id", ""): f for f in findings if isinstance(f, dict) and f.get("finding_id")
    }

    for group_key, stage_labels in [("ad_group", _AD_STAGE_LABELS), ("ac_group", _AC_STAGE_LABELS)]:
        group_result = review_data.get(f"{group_key}_result", {}) or {}
        conclusion = group_result.get("conclusion", {}) or {}
        stage_judgments = conclusion.get("stage_rule_judgments", {}) or {}
        stage_coverage_rows = group_result.get("stage_coverage", []) or conclusion.get("stage_coverage", []) or []
        stage_coverage_map = {row.get("stage", ""): row for row in stage_coverage_rows if isinstance(row, dict)}

        for stage_key, items in stage_judgments.items():
            if not isinstance(items, list):
                continue
            stage_label = stage_labels.get(stage_key, stage_key)
            stage_unit_key = (
                _AD_STAGE_TO_UNIT_KEY.get(stage_key, f"ad_{stage_key}")
                if group_key == "ad_group"
                else _AC_STAGE_TO_UNIT_KEY.get(stage_key, f"ac_{stage_key}")
            )
            stage_blocking_count = int(stage_coverage_map.get(stage_key, {}).get("blocking_count", 0) or 0)
            for item in items:
                if not isinstance(item, dict):
                    continue
                candidate = _candidate_from_judgment_item(
                    group_key=group_key,
                    stage_key=stage_key,
                    stage_label=stage_label,
                    stage_unit_key=stage_unit_key,
                    item=item,
                    findings_by_id=findings_by_id,
                    stage_blocking_count=stage_blocking_count,
                    unit_bundle_map=unit_bundle_map,
                    evidence_map=evidence_map,
                    rule_result_map=rule_result_map,
                )
                if not candidate:
                    continue
                candidate_key = (group_key, stage_key, candidate["rule_id"], candidate["judgment"])
                if candidate_key in seen_keys:
                    continue
                seen_keys.add(candidate_key)
                candidates.append(candidate)

    for unit in review_data.get("unit_results", []) or []:
        if not isinstance(unit, dict):
            continue
        unit_key = str(unit.get("unit_key", "") or "")
        discipline = str(unit.get("discipline") or unit_key or "general")
        stage_label = str(unit.get("unit_name") or unit_key or discipline)
        for rule in unit.get("rule_results", []) or []:
            if not isinstance(rule, dict):
                continue
            judgment = rule_judgment_from_result(rule)
            if judgment not in ("not_satisfied", "insufficient_evidence"):
                continue
            item = {
                "rule_id": rule.get("rule_id", ""),
                "rule_text": rule.get("rule_desc") or rule.get("rule_text") or "",
                "judgment": judgment,
                "rationale": rule.get("reasoning", ""),
                "evidence_ids": list(rule.get("evidence_refs") or []),
                "related_issue_ids": [],
                "claim_present": rule.get("claim_present"),
                "claim_sufficient": rule.get("claim_sufficient"),
                "rule_consistent": rule.get("rule_consistent"),
                "support_status": rule.get("support_status"),
            }
            candidate = _candidate_from_judgment_item(
                group_key=discipline,
                stage_key=unit_key,
                stage_label=stage_label,
                stage_unit_key=unit_key,
                item=item,
                findings_by_id=findings_by_id,
                stage_blocking_count=int(unit.get("is_blocked") or 0),
                unit_bundle_map=unit_bundle_map,
                evidence_map=evidence_map,
                rule_result_map=rule_result_map,
            )
            if not candidate:
                continue
            candidate_key = (discipline, unit_key, candidate["rule_id"], candidate["judgment"])
            if candidate_key in seen_keys:
                continue
            seen_keys.add(candidate_key)
            candidates.append(candidate)

    return candidates


def append_rule_candidate_rids(
    review_id: str,
    rid_items: list[dict],
    rule_rid_candidates: list[dict],
    finding_rid_map: dict[str, str],
) -> tuple[list[dict], int]:
    next_index = len(rid_items) + 1
    appended_count = 0
    for candidate in rule_rid_candidates:
        related_ids = candidate.get("related_finding_ids", []) or []
        if related_ids and any(fid in finding_rid_map for fid in related_ids):
            continue
        candidate_desc = candidate.get("description", "")
        if any(item.get("description") == candidate_desc for item in rid_items):
            continue
        rid_id = f"RID-{review_id or 'review'}-{next_index:03d}"
        next_index += 1
        rid_items.append(
            {
                "rid_id": rid_id,
                "rid": rid_id,
                "discipline": candidate.get("discipline", "ad_group"),
                "severity": candidate.get("severity", "minor"),
                "description": candidate_desc,
                "basis": candidate.get("basis", ""),
                "impact": candidate.get("impact", ""),
                "recommendation": candidate.get("recommendation", ""),
                "owner": "姿态确定设计组",
                "status": "open",
                "related_finding_id": related_ids[0] if related_ids else "",
                "related_finding_ids": related_ids,
                "source_type": "rule_judgment",
                "source_stage": candidate.get("stage", ""),
                "source_stage_label": candidate.get("stage_label", ""),
                "source_rule_id": candidate.get("rule_id", ""),
                "source_rule_judgment": candidate.get("judgment", ""),
                "source_support_status": candidate.get("source_support_status", ""),
                "source_section_ids": candidate.get("source_section_ids", []),
                "source_evidence_ids": candidate.get("source_evidence_ids", []),
                "source_block_ids": candidate.get("source_block_ids", []),
                "source_quote": candidate.get("source_quote", ""),
                "source_parameter_ids": candidate.get("source_parameter_ids", []),
                "source_trace_link_ids": candidate.get("source_trace_link_ids", []),
                "rule_source_refs": candidate.get("rule_source_refs", []),
            }
        )
        for fid in related_ids:
            finding_rid_map[fid] = rid_id
        appended_count += 1
    return rid_items, appended_count


def detect_expert_opinion_conflicts(unit_results: list[dict]) -> list[dict[str, Any]]:
    """Detect conflicting expert judgments over the same rule or source evidence."""
    observations_by_key: dict[str, list[dict[str, Any]]] = {}

    def add_observation(key: str, obs: dict[str, Any]) -> None:
        if key:
            observations_by_key.setdefault(key, []).append(obs)

    for unit in unit_results or []:
        if not isinstance(unit, dict):
            continue
        unit_key = str(unit.get("unit_key", "") or "")
        agent_id = str(unit.get("agent_id", "") or unit_key)
        for rule in unit.get("rule_results", []) or []:
            if not isinstance(rule, dict):
                continue
            judgment = rule_judgment_from_result(rule)
            if judgment not in {"satisfied", "not_satisfied"}:
                continue
            rule_id = str(rule.get("rule_id", "") or "")
            evidence_ids = rule_source_evidence_ids(rule)
            obs = {
                "unit_key": unit_key,
                "agent_id": agent_id,
                "rule_id": rule_id,
                "judgment": judgment,
                "reasoning": str(rule.get("reasoning", "") or "")[:220],
                "evidence_refs": evidence_ids,
                "execution_status": str(rule.get("execution_status", "") or ""),
                "verification_method": str(rule.get("verification_method", "") or ""),
            }
            score, score_breakdown = arbitration_score(unit, rule)
            obs["arbitration_score"] = score
            obs["score_breakdown"] = score_breakdown
            if rule_id:
                add_observation(f"rule:{rule_id}", obs)
            for evidence_id in evidence_ids:
                add_observation(f"evidence:{evidence_id}", obs)

    conflicts: list[dict[str, Any]] = []
    for key, observations in observations_by_key.items():
        judgments = {item["judgment"] for item in observations}
        agents = {item["agent_id"] for item in observations if item.get("agent_id")}
        if not {"satisfied", "not_satisfied"}.issubset(judgments):
            continue
        if len(agents) < 2 and key.startswith("evidence:"):
            continue
        ranked = sorted(
            observations,
            key=lambda item: (
                float(item.get("arbitration_score", 0.0) or 0.0),
                1 if item.get("execution_status") == "deterministic_checked" else 0,
            ),
            reverse=True,
        )
        top = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else {}
        score_gap = float(top.get("arbitration_score", 0.0) or 0.0) - float(
            runner_up.get("arbitration_score", 0.0) or 0.0
        )
        deterministic_winner = top.get("execution_status") == "deterministic_checked"
        can_recommend = deterministic_winner or score_gap >= _ARBITRATION_SCORE_GAP
        recommended_resolution = (
            {
                "selected_judgment": top.get("judgment", ""),
                "selected_agent_id": top.get("agent_id", ""),
                "selected_unit_key": top.get("unit_key", ""),
                "arbitration_score": top.get("arbitration_score", 0.0),
                "basis": (
                    "采信确定性工具/预检结果。"
                    if deterministic_winner
                    else "采信证据完整度、工具可信度和任务相关性综合评分更高的一侧。"
                ),
            }
            if can_recommend
            else {}
        )
        conflicts.append(
            {
                "conflict_id": f"conflict-{len(conflicts) + 1:03d}",
                "conflict_key": key,
                "conflict_type": "same_rule_opposite_judgment"
                if key.startswith("rule:")
                else "same_evidence_opposite_judgment",
                "summary": "同一规则存在相反判定"
                if key.startswith("rule:")
                else "同一证据被不同专家作出相反判定",
                "observations": ranked[:8],
                "recommended_resolution": recommended_resolution,
                "requires_arbitration": not can_recommend,
            }
        )
    return conflicts


def summarize_review_risk_categories(unit_results: list[dict]) -> dict[str, int]:
    summary = {
        "missing_claim_count": 0,
        "rule_inconsistent_count": 0,
        "unverified_claim_count": 0,
    }
    for unit in unit_results or []:
        for rule in unit.get("rule_results", []) or []:
            if not isinstance(rule, dict):
                continue
            judgment = str(rule.get("judgment", "") or rule_judgment_from_result(rule)).strip().lower()
            claim_present = rule.get("claim_present", None)
            claim_sufficient = rule.get("claim_sufficient", None)
            rule_consistent = rule.get("rule_consistent", None)
            support_status = str(rule.get("support_status", "") or "").strip().lower()
            if judgment == "not_satisfied" and claim_present is False:
                summary["missing_claim_count"] += 1
            elif judgment == "not_satisfied" and rule_consistent is False:
                summary["rule_inconsistent_count"] += 1
            elif judgment == "insufficient_evidence" and claim_present is True and (
                support_status in {"none", "weak"} or claim_sufficient is False
            ):
                summary["unverified_claim_count"] += 1
    return summary


def merge_editorial_rid_items(
    review_id: str,
    llm_rid_items: list[dict],
    rule_rid_candidates: list[dict],
    findings: list[dict],
    evidence_map: dict[str, dict],
) -> tuple[list[dict], dict[str, str], int]:
    rid_items: list[dict] = []
    finding_rid_map: dict[str, str] = {}
    finding_by_id = {
        f.get("finding_id", ""): f for f in findings if isinstance(f, dict) and f.get("finding_id")
    }
    rule_candidate_by_key = {
        (candidate.get("stage", ""), candidate.get("rule_id", "")): candidate for candidate in rule_rid_candidates
    }

    for index, lr in enumerate(llm_rid_items or [], start=1):
        rid_id = lr.get("rid_id") or lr.get("rid") or f"RID-{review_id or 'review'}-{index:03d}"
        related_ids = _as_str_list(lr.get("related_finding_ids") or lr.get("related_finding_id"))
        rule_trace_source = rule_candidate_by_key.get((lr.get("source_stage", ""), lr.get("source_rule_id", "")), {})
        finding_trace_source: dict[str, Any] = {}
        for related_id in related_ids:
            finding_trace_source = collect_finding_trace_fields(finding_by_id.get(related_id, {}), evidence_map)
            if any(
                finding_trace_source.get(key)
                for key in (
                    "source_section_ids",
                    "source_evidence_ids",
                    "source_block_ids",
                    "source_quote",
                    "source_parameter_ids",
                    "source_trace_link_ids",
                    "rule_source_refs",
                )
            ):
                break
        rid_items.append(
            {
                "rid_id": rid_id,
                "rid": rid_id,
                "discipline": lr.get("discipline", ""),
                "severity": lr.get("severity", "minor"),
                "description": lr.get("description", ""),
                "basis": lr.get("basis", ""),
                "impact": lr.get("impact", ""),
                "recommendation": lr.get("recommendation", ""),
                "owner": lr.get("owner") or f"{lr.get('discipline', '')} 设计组",
                "status": lr.get("status", "open"),
                "related_finding_id": related_ids[0] if related_ids else "",
                "related_finding_ids": related_ids,
                "source_type": lr.get("source_type", "finding_merged"),
                "source_stage": lr.get("source_stage", ""),
                "source_stage_label": lr.get("source_stage_label", ""),
                "source_rule_id": lr.get("source_rule_id", ""),
                "source_rule_judgment": lr.get("source_rule_judgment", ""),
                "source_support_status": lr.get("source_support_status", ""),
                "source_section_ids": lr.get("source_section_ids", [])
                or rule_trace_source.get("source_section_ids", [])
                or finding_trace_source.get("source_section_ids", []),
                "source_evidence_ids": lr.get("source_evidence_ids", [])
                or rule_trace_source.get("source_evidence_ids", [])
                or finding_trace_source.get("source_evidence_ids", []),
                "source_block_ids": lr.get("source_block_ids", [])
                or rule_trace_source.get("source_block_ids", [])
                or finding_trace_source.get("source_block_ids", []),
                "source_quote": lr.get("source_quote", "")
                or rule_trace_source.get("source_quote", "")
                or finding_trace_source.get("source_quote", ""),
                "source_parameter_ids": lr.get("source_parameter_ids", [])
                or rule_trace_source.get("source_parameter_ids", [])
                or finding_trace_source.get("source_parameter_ids", []),
                "source_trace_link_ids": lr.get("source_trace_link_ids", [])
                or rule_trace_source.get("source_trace_link_ids", [])
                or finding_trace_source.get("source_trace_link_ids", []),
                "rule_source_refs": lr.get("rule_source_refs", [])
                or rule_trace_source.get("rule_source_refs", [])
                or finding_trace_source.get("rule_source_refs", []),
            }
        )
        for fid in related_ids:
            finding_rid_map[fid] = rid_id

    rid_items, appended_count = append_rule_candidate_rids(
        review_id=review_id,
        rid_items=rid_items,
        rule_rid_candidates=rule_rid_candidates,
        finding_rid_map=finding_rid_map,
    )
    for finding in findings:
        fid = finding.get("finding_id", "")
        if fid in finding_rid_map:
            finding["related_rid_id"] = finding_rid_map[fid]
    return rid_items, finding_rid_map, appended_count


def summarize_unit_results(unit_results: list[dict]) -> dict[str, Any]:
    """Summarize committee unit review execution and rule judgment counts."""
    summary = {
        "total": len(unit_results or []),
        "placeholder": 0,
        "blocked": 0,
        "completed": 0,
        "rule_result_count": 0,
        "failed_rule_count": 0,
        "insufficient_rule_count": 0,
        "not_checked_rule_count": 0,
    }
    for item in unit_results or []:
        status = str(item.get("status", "")).lower()
        if status == "placeholder":
            summary["placeholder"] += 1
        elif status == "blocked" or item.get("is_blocked"):
            summary["blocked"] += 1
        else:
            summary["completed"] += 1

        for rule in item.get("rule_results", []) or []:
            if not isinstance(rule, dict):
                continue
            summary["rule_result_count"] += 1
            judgment = str(rule.get("judgment", "") or rule_judgment_from_result(rule)).strip().lower()
            if judgment == "not_checked":
                summary["not_checked_rule_count"] += 1
            elif judgment == "not_satisfied":
                summary["failed_rule_count"] += 1
            elif judgment == "insufficient_evidence":
                summary["insufficient_rule_count"] += 1
            elif "passed" in rule and not rule.get("passed", False):
                if rule.get("evidence_refs"):
                    summary["failed_rule_count"] += 1
                else:
                    summary["insufficient_rule_count"] += 1
    return summary


_STAGE_LABELS = {
    "req_err": "需求确认与误差分解",
    "timing": "采集时序设计",
    "install": "安装指向设计与可用性分析",
    "algorithm": "姿态确定算法设计",
    "ad_req_err": "需求确认与误差分解",
    "ad_timing": "采集时序设计",
    "ad_install": "安装指向设计与可用性分析",
    "ad_algorithm": "姿态确定算法设计",
    "ad_simulation": "数学仿真与结果分析",
    "thruster_layout": "推力器布局",
    "other_actuator_layout": "其他执行机构布局",
    "control_law": "控制律设计",
    "control_params": "姿控参数设计",
    "maneuver_law": "操纵律设计",
    "unloading_law": "卸载律设计",
    "ac_simulation": "姿控仿真",
    "ac_req_err": "需求确认与误差分解",
    "ac_thruster_layout": "推力器布局",
    "ac_other_actuator_layout": "其他执行机构布局",
    "ac_control_law": "控制律设计",
    "ac_control_params": "姿控参数设计",
    "ac_maneuver_law": "操纵律设计",
    "ac_unloading_law": "卸载律设计",
    "ac_simulation": "姿控仿真",
    "fdir": "FDIR",
    "interface": "接口协调",
    "verification": "验证审查",
    "general": "综合",
}


def build_rule_coverage_summary(unit_results: list[dict]) -> dict[str, dict]:
    """Per-unit rule pass/fail/insufficient counts for editorial minutes."""
    rule_coverage_summary: dict[str, dict] = {}
    for unit in unit_results or []:
        if not isinstance(unit, dict):
            continue
        unit_key = str(unit.get("unit_key", "") or unit.get("unit_name", ""))
        unit_label = _STAGE_LABELS.get(unit_key, unit_key)
        rules = unit.get("rule_results", []) or []
        total = len(rules)
        passed = 0
        failed = 0
        insufficient = 0
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            judgment = rule_judgment_from_result(rule)
            if judgment == "satisfied" or rule.get("passed") is True:
                passed += 1
            elif judgment == "insufficient_evidence" or (
                rule.get("passed") is False and not rule.get("evidence_refs")
            ):
                insufficient += 1
            elif judgment == "not_satisfied" or rule.get("passed") is False:
                failed += 1
        rule_coverage_summary[unit_label] = {
            "total_rules": total,
            "passed": passed,
            "failed": failed,
            "insufficient_evidence": insufficient,
            "pass_rate": f"{passed}/{total}" if total else "N/A",
        }
    return rule_coverage_summary


def build_section_rid_map(
    rid_items: list[dict],
    *,
    section_tree: dict[str, Any] | None = None,
) -> dict[str, list]:
    sections_by_id = {
        str(section.get("section_id", "")): section
        for section in ((section_tree or {}).get("sections") or [])
        if isinstance(section, dict) and section.get("section_id")
    }
    section_rid_map: dict[str, list] = {}
    for rid in rid_items or []:
        if not isinstance(rid, dict):
            continue
        source_section_ids = rid.get("source_section_ids", []) or []
        if not source_section_ids:
            disc = rid.get("discipline", "general") or "general"
            stage = rid.get("source_stage", "")
            source_section_ids = [f"stage:{stage or disc}"]
        for section_id in source_section_ids:
            section = sections_by_id.get(section_id, {})
            fallback_label = _STAGE_LABELS.get(str(section_id).replace("stage:", ""), str(section_id))
            label = section.get("title") or fallback_label
            group_key = f"{label} ({section_id})" if section and section_id else label
            section_rid_map.setdefault(group_key, []).append(
                {
                    "rid_id": rid.get("rid_id", ""),
                    "severity": rid.get("severity", "minor"),
                    "description": str(rid.get("description", ""))[:120],
                    "source_rule_id": rid.get("source_rule_id", ""),
                    "source_evidence_ids": rid.get("source_evidence_ids", []),
                    "source_quote": str(rid.get("source_quote", ""))[:180],
                    "prior_cycle_status": rid.get("prior_cycle_status", ""),
                }
            )
    return section_rid_map


def annotate_rid_prior_cycle_status(
    rid_items: list[dict],
    review_focus: dict[str, Any] | None,
) -> tuple[list[dict], dict[str, Any]]:
    """Annotate current-cycle RIDs with prior-cycle close/reopen/continue status."""
    if not review_focus or not isinstance(review_focus, dict):
        return list(rid_items or []), {}

    claimed_resolved_ids = {
        str(rid_id) for rid_id in (review_focus.get("claimed_resolved_rid_ids") or []) if rid_id
    }
    focus_ids = {str(rid_id) for rid_id in (review_focus.get("focus_rid_ids") or []) if rid_id}
    prior_rid_map: dict[str, dict] = {}
    for key in ("claimed_resolved_rids", "severe_open_rids", "open_rids"):
        for item in review_focus.get(key, []) or []:
            if isinstance(item, dict) and item.get("rid_id"):
                prior_rid_map[str(item["rid_id"])] = item

    severe_ids = {
        str(item.get("rid_id"))
        for item in (review_focus.get("severe_open_rids") or [])
        if isinstance(item, dict) and item.get("rid_id")
    }
    severe_ids |= focus_ids

    summary = {
        "current_cycle": review_focus.get("current_cycle"),
        "previous_cycle": review_focus.get("previous_cycle"),
        "change_summary": review_focus.get("change_summary", ""),
        "new_count": 0,
        "continued_count": 0,
        "reopened_count": 0,
        "verified_closed_candidates": [],
        "claimed_resolved_rid_ids": sorted(claimed_resolved_ids),
        "focus_rid_ids": sorted(focus_ids),
    }
    current_ids = {str(item.get("rid_id") or item.get("rid") or "") for item in rid_items or []}
    summary["verified_closed_candidates"] = sorted(claimed_resolved_ids - current_ids)

    annotated: list[dict] = []
    for rid in rid_items or []:
        if not isinstance(rid, dict):
            continue
        item = dict(rid)
        rid_id = str(item.get("rid_id") or item.get("rid") or "")
        prior = prior_rid_map.get(rid_id)

        if rid_id in claimed_resolved_ids:
            item["prior_cycle_status"] = "claimed_resolved_still_open"
            item["prior_cycle_rid_id"] = rid_id
            summary["reopened_count"] += 1
        elif rid_id in severe_ids or (
            prior and str(prior.get("severity", "")).lower() in ("critical", "major")
        ):
            item["prior_cycle_status"] = "continued"
            item["prior_cycle_rid_id"] = rid_id
            summary["continued_count"] += 1
        elif prior:
            item["prior_cycle_status"] = "continued"
            item["prior_cycle_rid_id"] = rid_id
            summary["continued_count"] += 1
        else:
            item["prior_cycle_status"] = "new"
            summary["new_count"] += 1
        annotated.append(item)
    return annotated, summary


def build_editorial_minutes_struct(
    *,
    review_id: str,
    product_model: str,
    review_phase: str,
    rid_items: list[dict],
    discipline_reviews: dict[str, Any],
    unit_results: list[dict],
    editorial_result: dict[str, Any],
    section_tree: dict[str, Any] | None,
    traceability_matrix_summary: dict[str, Any] | None,
    evidences: list[dict] | None,
    appended_rule_count: int,
    generated_at: str,
    prior_cycle_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build source-equivalent rich editorial minutes structure."""
    rid_severity_count: dict[str, int] = {}
    for rid in rid_items or []:
        severity = str(rid.get("severity", "minor"))
        rid_severity_count[severity] = rid_severity_count.get(severity, 0) + 1

    insufficient_evidences = [
        ev for ev in (evidences or []) if isinstance(ev, dict) and ev.get("evidence_insufficient")
    ]
    unit_review_summary = summarize_unit_results(unit_results)
    section_rid_map = build_section_rid_map(rid_items, section_tree=section_tree)
    rule_coverage_summary = build_rule_coverage_summary(unit_results)
    prior_cycle_summary = prior_cycle_summary or {}

    follow_up_items = [
        f"共 {len(rid_items)} 条审查清单，其中 {rid_severity_count.get('major', 0)} 条 major 需限期关闭",
    ]
    if appended_rule_count:
        follow_up_items.append(f"另有 {appended_rule_count} 条由规则判定直接提升的整改项需优先闭环")
    if prior_cycle_summary.get("verified_closed_candidates"):
        follow_up_items.append(
            f"声明已整改且本轮未再现的 RID {len(prior_cycle_summary['verified_closed_candidates'])} 条，建议总师确认关闭"
        )

    return {
        "review_id": review_id,
        "product_model": product_model,
        "review_phase": review_phase,
        "committee_members": [
            "GNC 总师",
            "质量师",
            "合稿师",
            "姿态控制专家",
            "轨道控制专家",
            "控制律专家",
            "FDIR 专家",
            "接口协调专家",
            "验证审查专家",
        ],
        "discipline_summaries": {
            key: (value.get("summary", "") if isinstance(value, dict) else "")
            for key, value in (discipline_reviews or {}).items()
        },
        "unit_review_summary": unit_review_summary,
        "rid_summary": rid_severity_count,
        "section_rid_map": section_rid_map,
        "rule_coverage_summary": rule_coverage_summary,
        "traceability_matrix_summary": traceability_matrix_summary or {},
        "prior_cycle_summary": prior_cycle_summary,
        "residual_risks": editorial_result.get("residual_risks", []) or [],
        "cross_discipline_issues": editorial_result.get("cross_discipline_issues", []) or [],
        "evidence_insufficient_summary": (
            f"{len(insufficient_evidences)} 条知识依据不足"
            if insufficient_evidences
            else "全部知识依据充分"
        ),
        "conclusion_draft": editorial_result.get("conclusion_draft", ""),
        "follow_up_items": follow_up_items,
        "generated_at": generated_at,
    }


def apply_chief_arbitration(
    decision: dict[str, Any],
    *,
    expert_conflicts: list[dict[str, Any]],
    committee_conflicts: list[dict[str, Any]] | None = None,
    failures: dict[str, str] | None = None,
) -> dict[str, Any]:
    merged = dict(decision)
    arbitration_items = list(merged.get("arbitration_items", []) or [])
    unresolved = [item for item in expert_conflicts if item.get("requires_arbitration")]
    if unresolved or expert_conflicts:
        merged["conflict_analysis"] = expert_conflicts
    if unresolved:
        merged["requires_arbitration"] = True
        arbitration_items.extend(
            f"{item.get('conflict_id')}: {item.get('summary')} ({item.get('conflict_key')})"
            for item in unresolved
            if item.get("conflict_id")
        )
    if committee_conflicts:
        if any(item.get("requires_arbitration") for item in committee_conflicts):
            merged["requires_arbitration"] = True
            arbitration_items.extend(
                f"{item.get('conflict_id')}: {item.get('summary')} ({item.get('conflict_key')})"
                for item in committee_conflicts
                if item.get("requires_arbitration")
            )
    if failures:
        merged["requires_arbitration"] = True
        arbitration_items.extend(f"{agent_key}: {error}" for agent_key, error in failures.items())
    merged["arbitration_items"] = list(dict.fromkeys(arbitration_items))
    if expert_conflicts and not merged.get("conflict_resolutions"):
        merged["conflict_resolutions"] = [
            (
                f"{item.get('conflict_id')}: "
                f"{item.get('recommended_resolution', {}).get('basis') or '已识别专家相左意见，需按确定性预检、直接文档证据、标准依据顺序裁决。'}"
            )
            for item in expert_conflicts
        ]
    return merged


__all__ = [
    "annotate_rid_prior_cycle_status",
    "append_rule_candidate_rids",
    "apply_chief_arbitration",
    "arbitration_score",
    "build_editorial_minutes_struct",
    "build_rule_coverage_summary",
    "build_rule_rid_candidates",
    "build_section_rid_map",
    "build_trace_context",
    "collect_finding_trace_fields",
    "collect_rule_trace_fields",
    "confidence_score",
    "detect_expert_opinion_conflicts",
    "evidence_completeness_score",
    "merge_editorial_rid_items",
    "rule_judgment_from_result",
    "rule_source_evidence_ids",
    "summarize_review_risk_categories",
    "summarize_unit_results",
    "task_relevance_score",
    "tool_trust_score",
]
