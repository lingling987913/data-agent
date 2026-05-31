"""
Review-Plus MVP workflow.

Registered as an independent workflow and kept physically isolated from the
existing GNC design review workflow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from agno.workflow import Step, StepInput, StepOutput, Workflow

from data_agent.review_plus.schemas import ReviewPlusMaterialRole, ReviewPlusStatus
from data_agent.review_plus.cross_document_utils import (
    material_version_baseline_meta,
    version_baseline_mismatch_summaries,
)
# WorkflowFactory optional
from data_agent.workflows.workflow_factory import WorkflowFactory

logger = logging.getLogger(__name__)

_REQ_ID_RE = re.compile(r"\bREQ-[A-Za-z0-9_-]+\b")
_DES_ID_RE = re.compile(r"\b(?:DES|DP|DSP)-[A-Za-z0-9_-]+\b")
_VER_ID_RE = re.compile(r"\b(?:VER|SIM|TEST|VT)-[A-Za-z0-9_-]+\b")
_ARTIFACT_ID_RE = re.compile(r"\b(?:REQ|DES|DP|DSP|VER|SIM|TEST|VT)-[A-Za-z0-9_-]+\b")
_METRIC_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_/\- ]{0,24}?)?"
    r"\s*(?P<comparator><=|>=|≤|≥|不大于|不小于|不超过|不少于|小于|大于)?\s*"
    r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mm/s|m/s|km/s|deg/s|rad/s|mHz|Hz|kPa|Pa|mW|kW|W|mN|N|km|mm|kg|g|deg|rad|°/s|°|ms|s|m|%)\b",
    re.IGNORECASE,
)
_TRACEABILITY_GAP_ITEM_TYPES = {
    "missing_design_closure",
    "missing_verification",
    "design_item_without_requirement_basis",
}


def _step_payload(step: str, **kwargs: Any) -> dict[str, Any]:
    return {"step": step, "timestamp": datetime.now().isoformat(), **kwargs}


def _extract_review_id(step_input: StepInput) -> str:
    raw = step_input.input
    if isinstance(raw, dict):
        return str(raw.get("review_id") or raw.get("review_plus_id") or "").strip()
    return str(raw or "").strip()


def _service():
    from data_agent.review_plus.service import get_review_plus_service

    return get_review_plus_service()


def _save_task(svc: Any, task: Any) -> None:
    task.updated_at = datetime.now().isoformat()
    if hasattr(svc, "_save_task"):
        svc._save_task(task)


def _iter_material_lines(task: Any, *, exclude_roles: set[str] | None = None) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    exclude = exclude_roles or set()
    for material in getattr(task, "materials", []) or []:
        if getattr(material, "included_in_formal_review", True) is False:
            continue
        role_val = material.role.value if isinstance(material.role, ReviewPlusMaterialRole) else str(material.role or "")
        if role_val in exclude:
            continue
        for index, raw in enumerate((getattr(material, "content", "") or "").splitlines(), start=1):
            text = raw.strip().strip("-* \t")
            if len(text) < 4:
                continue
            lines.append({
                "material_name": getattr(material, "name", ""),
                "line_no": index,
                "text": text,
                "evidence_id": f"ev:{getattr(material, 'name', '')}:line-{index}",
                "section_id": f"{getattr(material, 'name', '')}:line-{index}",
            })
    return lines


def _title_from_line(text: str, artifact_id: str) -> str:
    cleaned = _ARTIFACT_ID_RE.sub("", text or "").strip(" ：:-")
    return cleaned[:80] or artifact_id


def _extract_metric(text: str) -> dict[str, Any]:
    cleaned = _ARTIFACT_ID_RE.sub("", text or "")
    matches = list(_METRIC_RE.finditer(cleaned))
    if not matches:
        return {"metric_name": "", "comparator": "", "value": None, "unit": ""}
    match = matches[-1]
    metric_name = (match.group("name") or "").strip(" ：:,，;；")
    return {
        "metric_name": metric_name[-24:],
        "comparator": _normalize_comparator(match.group("comparator") or ""),
        "value": float(match.group("value")),
        "unit": (match.group("unit") or "").strip(),
    }


def _normalize_comparator(value: str) -> str:
    mapping = {
        "不大于": "<=",
        "不超过": "<=",
        "小于": "<",
        "≤": "<=",
        "不小于": ">=",
        "不少于": ">=",
        "大于": ">",
        "≥": ">=",
    }
    return mapping.get(value, value)


def _active_trace_links(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        link
        for link in result.get("trace_links") or []
        if link.get("status") != "rejected"
    ]


def _build_review_plus_traceability_result(task: Any) -> dict[str, Any]:
    _EXCLUDE_TRACE = {ReviewPlusMaterialRole.REVIEW_RULE.value, ReviewPlusMaterialRole.CHECKLIST.value}
    lines = _iter_material_lines(task, exclude_roles=_EXCLUDE_TRACE)
    requirements: dict[str, dict[str, Any]] = {}
    design_items: dict[str, dict[str, Any]] = {}
    verification_claims: dict[str, dict[str, Any]] = {}
    recent_requirements: dict[str, tuple[int, list[str]]] = {}
    recent_designs: dict[str, tuple[int, list[str]]] = {}

    for line in lines:
        text = line["text"]
        material_name = line["material_name"]
        explicit_req_ids = _REQ_ID_RE.findall(text)
        explicit_des_ids = _DES_ID_RE.findall(text)
        ver_ids = _VER_ID_RE.findall(text)
        context_req_ids = (
            recent_requirements.get(material_name, (0, []))[1]
            if line["line_no"] - recent_requirements.get(material_name, (0, []))[0] <= 5
            else []
        )
        context_des_ids = (
            recent_designs.get(material_name, (0, []))[1]
            if line["line_no"] - recent_designs.get(material_name, (0, []))[0] <= 5
            else []
        )
        linked_req_ids = explicit_req_ids or context_req_ids
        linked_des_ids = explicit_des_ids or context_des_ids
        metric = _extract_metric(text)
        for req_id in explicit_req_ids:
            requirements.setdefault(req_id, {
                "requirement_id": req_id,
                "title": _title_from_line(text, req_id),
                "text": text,
                "requirement_level": "decomposed",
                "parent_requirement_ids": [rid for rid in explicit_req_ids if rid != req_id],
                "metric_name": metric["metric_name"],
                "comparator": metric["comparator"],
                "target_value": metric["value"],
                "unit": metric["unit"],
                "source_file_name": line["material_name"],
                "source_section_id": line["section_id"],
                "source_evidence_id": line["evidence_id"],
                "source_quote": text,
                "confidence": 0.9,
            })
        for des_id in explicit_des_ids:
            design_items.setdefault(des_id, {
                "design_item_id": des_id,
                "title": _title_from_line(text, des_id),
                "text": text,
                "satisfies_requirement_ids": linked_req_ids,
                "metric_name": metric["metric_name"],
                "observed_value": metric["value"],
                "unit": metric["unit"],
                "source_file_name": line["material_name"],
                "source_section_id": line["section_id"],
                "source_evidence_id": line["evidence_id"],
                "source_quote": text,
                "confidence": 0.88,
            })
        for ver_id in ver_ids:
            verification_claims.setdefault(ver_id, {
                "verification_id": ver_id,
                "title": _title_from_line(text, ver_id),
                "method": "simulation" if ver_id.startswith("SIM-") else "test" if ver_id.startswith("TEST-") else "verification",
                "verifies_requirement_ids": linked_req_ids,
                "verifies_design_item_ids": linked_des_ids,
                "status": "completed",
                "metric_name": metric["metric_name"],
                "observed_value": metric["value"],
                "unit": metric["unit"],
                "source_file_name": line["material_name"],
                "source_section_id": line["section_id"],
                "source_evidence_id": line["evidence_id"],
                "source_quote": text,
                "confidence": 0.86,
            })
        if explicit_req_ids:
            recent_requirements[material_name] = (line["line_no"], explicit_req_ids)
        if explicit_des_ids:
            recent_designs[material_name] = (line["line_no"], explicit_des_ids)

    links = _build_review_plus_trace_links(requirements, design_items, verification_claims)
    review_items = _build_traceability_gap_items(requirements, design_items, verification_claims, links)
    result = {
        "review_id": getattr(task, "review_plus_id", ""),
        "materials": [
            {
                "name": getattr(material, "name", ""),
                "file_type": getattr(material, "file_type", ""),
                "role": getattr(getattr(material, "role", ""), "value", getattr(material, "role", "")),
                "document_version": getattr(material, "document_version", ""),
                "baseline_id": getattr(material, "baseline_id", ""),
                "included_in_formal_review": getattr(material, "included_in_formal_review", True),
            }
            for material in getattr(task, "materials", []) or []
        ],
        "requirements": list(requirements.values()),
        "design_items": list(design_items.values()),
        "verification_claims": list(verification_claims.values()),
        "trace_links": links,
        "matrix_rows": [],
        "review_items": review_items,
        "summary": {},
    }
    _refresh_traceability_views(result)
    return result


def _build_review_plus_trace_links(
    requirements: dict[str, dict[str, Any]],
    design_items: dict[str, dict[str, Any]],
    verification_claims: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source_id: str, target_id: str, link_type: str, quote: str, evidence_id: str, confidence: float) -> None:
        key = (source_id, target_id, link_type)
        if not source_id or not target_id or key in seen:
            return
        seen.add(key)
        links.append({
            "link_id": f"rp-{link_type}-{len(links) + 1}",
            "source_id": source_id,
            "target_id": target_id,
            "link_type": link_type,
            "status": "candidate",
            "confidence": round(confidence, 3),
            "evidence_ids": [evidence_id] if evidence_id else [],
            "source_quote": quote,
        })

    for req in requirements.values():
        for parent_id in req.get("parent_requirement_ids") or []:
            add(parent_id, req["requirement_id"], "decomposes", req["source_quote"], req["source_evidence_id"], 0.9)
    for item in design_items.values():
        for req_id in item.get("satisfies_requirement_ids") or []:
            add(req_id, item["design_item_id"], "satisfies", item["source_quote"], item["source_evidence_id"], 0.9)
    for claim in verification_claims.values():
        for req_id in claim.get("verifies_requirement_ids") or []:
            add(req_id, claim["verification_id"], "verifies", claim["source_quote"], claim["source_evidence_id"], 0.9)
        for design_id in claim.get("verifies_design_item_ids") or []:
            add(design_id, claim["verification_id"], "verifies", claim["source_quote"], claim["source_evidence_id"], 0.85)
    return links


def _build_traceability_gap_items(
    requirements: dict[str, dict[str, Any]],
    design_items: dict[str, dict[str, Any]],
    verification_claims: dict[str, dict[str, Any]],
    links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    design_by_req = defaultdict(list)
    ver_by_req = defaultdict(list)
    linked_design_ids: set[str] = set()
    for link in links:
        if link["link_type"] == "satisfies":
            design_by_req[link["source_id"]].append(link["target_id"])
            linked_design_ids.add(link["target_id"])
        elif link["link_type"] == "verifies" and link["source_id"] in requirements:
            ver_by_req[link["source_id"]].append(link["target_id"])

    items: list[dict[str, Any]] = []

    def add(item_type: str, artifact_id: str, title: str, description: str, quote: str) -> None:
        items.append({
            "review_item_id": f"rp-{item_type}-{len(items) + 1}",
            "item_type": item_type,
            "severity": "major" if item_type != "design_item_without_requirement_basis" else "minor",
            "title": title,
            "description": description,
            "recommendation": "补充跨文档引用关系、证据或人工确认追溯链路。",
            "source_artifact_ids": [artifact_id],
            "target_artifact_ids": [],
            "evidence_ids": [],
            "source_quote": quote,
            "status": "open",
        })

    for req_id, req in requirements.items():
        if not design_by_req.get(req_id):
            add("missing_design_closure", req_id, "设计闭合不足", f"需求 {req_id} 未发现明确设计实现项。", req["source_quote"])
        if not ver_by_req.get(req_id):
            add("missing_verification", req_id, "验证覆盖不足", f"需求 {req_id} 未发现明确验证依据。", req["source_quote"])
    for design_id, item in design_items.items():
        if design_id not in linked_design_ids:
            add(
                "design_item_without_requirement_basis",
                design_id,
                "设计项缺少上游需求依据",
                f"设计项 {design_id} 未显式关联上游需求。",
                item["source_quote"],
            )
    return items


def _refresh_traceability_views(result: dict[str, Any]) -> None:
    active_links = _active_trace_links(result)
    requirements = {item["requirement_id"]: item for item in result.get("requirements") or []}
    designs = {item["design_item_id"]: item for item in result.get("design_items") or []}
    verifications = {item["verification_id"]: item for item in result.get("verification_claims") or []}
    design_by_req = defaultdict(list)
    ver_by_req = defaultdict(list)
    ver_by_design = defaultdict(list)
    for link in active_links:
        if link.get("link_type") == "satisfies":
            design_by_req[link.get("source_id")].append(link.get("target_id"))
        elif link.get("link_type") == "verifies":
            if link.get("source_id") in requirements:
                ver_by_req[link.get("source_id")].append(link.get("target_id"))
            elif link.get("source_id") in designs:
                ver_by_design[link.get("source_id")].append(link.get("target_id"))

    rows: list[dict[str, Any]] = []
    for req_id, req in requirements.items():
        design_ids = design_by_req.get(req_id) or [""]
        for design_id in design_ids:
            verification_ids = ver_by_req.get(req_id) or ver_by_design.get(design_id) or [""]
            for verification_id in verification_ids:
                rows.append({
                    "requirement": req,
                    "design_item": designs.get(design_id),
                    "verification_claim": verifications.get(verification_id),
                    "closure_status": "closed" if design_id and verification_id else "gap",
                })
    result["matrix_rows"] = rows

    req_count = len(requirements)
    req_with_design = {req_id for req_id, ids in design_by_req.items() if ids and req_id in requirements}
    req_with_ver = {req_id for req_id, ids in ver_by_req.items() if ids and req_id in requirements}
    # 传递闭合：REQ→DES→VER 也算 REQ 被验证覆盖
    for req_id in req_with_design:
        if req_id in req_with_ver:
            continue
        for des_id in design_by_req.get(req_id, []):
            if ver_by_design.get(des_id):
                req_with_ver.add(req_id)
                break
    result["summary"] = {
        "requirement_count": req_count,
        "design_item_count": len(designs),
        "verification_claim_count": len(verifications),
        "trace_link_count": len(active_links),
        "review_item_count": len(result.get("review_items") or []),
        "design_closed_count": len(req_with_design),
        "verified_count": len(req_with_ver),
        "fully_closed_requirement_count": len(req_with_design & req_with_ver),
        "closure_gap_count": max(req_count - len(req_with_design & req_with_ver), 0),
        "design_closure_coverage": round(len(req_with_design) / req_count, 4) if req_count else 0.0,
        "verification_coverage": round(len(req_with_ver) / req_count, 4) if req_count else 0.0,
        "generated_at": datetime.now().isoformat(),
        "ruleset_version": "review-plus-traceability-2026-05-18",
    }


def _replace_traceability_gap_items(result: dict[str, Any]) -> None:
    requirements = {item["requirement_id"]: item for item in result.get("requirements") or []}
    designs = {item["design_item_id"]: item for item in result.get("design_items") or []}
    verifications = {item["verification_id"]: item for item in result.get("verification_claims") or []}
    preserved = [
        item
        for item in result.get("review_items") or []
        if item.get("item_type") not in _TRACEABILITY_GAP_ITEM_TYPES
    ]
    result["review_items"] = [
        *preserved,
        *_build_traceability_gap_items(requirements, designs, verifications, _active_trace_links(result)),
    ]


def _metric_key(metric: dict[str, Any]) -> str:
    name = str(metric.get("metric_name") or "").strip().lower()
    return name


def _collect_material_metrics(task: Any) -> list[dict[str, Any]]:
    _EXCLUDE_METRICS = {ReviewPlusMaterialRole.REVIEW_RULE.value, ReviewPlusMaterialRole.CHECKLIST.value}
    metrics: list[dict[str, Any]] = []
    for line in _iter_material_lines(task, exclude_roles=_EXCLUDE_METRICS):
        cleaned = _ARTIFACT_ID_RE.sub("", line["text"])
        for match in _METRIC_RE.finditer(cleaned):
            metrics.append({
                "metric_name": (match.group("name") or "").strip(" ：:,，;；")[-24:],
                "value": float(match.group("value")),
                "unit": (match.group("unit") or "").strip(),
                "material_name": line["material_name"],
                "line_no": line["line_no"],
                "source_quote": line["text"],
                "evidence_id": line["evidence_id"],
            })
    return metrics


def _build_cross_document_items(task: Any) -> list[dict[str, Any]]:
    result = task.traceability_result or _build_review_plus_traceability_result(task)
    items: list[dict[str, Any]] = []  # 每次重新生成，不继承旧 review_items
    metrics_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in _collect_material_metrics(task):
        key = _metric_key(metric)
        if key:
            metrics_by_key[key].append(metric)

    def add(item_type: str, severity: str, title: str, description: str, source_quotes: list[str]) -> None:
        items.append({
            "review_item_id": f"rp-cross-{item_type}-{len(items) + 1}",
            "item_type": item_type,
            "severity": severity,
            "title": title,
            "description": description,
            "impact": "跨文档口径不一致会削弱审查结论的可追溯性和可验证性。",
            "recommendation": "统一指标、单位、引用关系或版本基线，并补充修订说明。",
            "source_artifact_ids": [],
            "target_artifact_ids": [],
            "evidence_ids": [],
            "source_quote": "\n".join(source_quotes[:3]),
            "status": "open",
        })

    for key, metrics in metrics_by_key.items():
        by_material = {metric["material_name"] for metric in metrics}
        if len(by_material) < 2:
            continue
        units = {metric["unit"] for metric in metrics if metric["unit"]}
        label = key or "同名指标"
        if len(units) > 1:
            add("metric_unit_mismatch", "major", "跨文档指标单位不一致", f"指标 {label} 在多个材料中使用不同单位: {', '.join(sorted(units))}。", [m["source_quote"] for m in metrics])
        for unit in sorted(units):
            unit_metrics = [metric for metric in metrics if metric["unit"] == unit]
            values = {metric["value"] for metric in unit_metrics}
            if len(values) > 1:
                add("metric_value_mismatch", "critical", "跨文档指标数值不一致", f"指标 {label} 在单位 {unit} 下出现不同数值: {', '.join(str(v) for v in sorted(values))}。", [m["source_quote"] for m in unit_metrics])

    material_meta = material_version_baseline_meta(task)
    versions, baselines = version_baseline_mismatch_summaries(task)
    if len(versions) > 1:
        add("baseline_version_mismatch", "major", "跨文档版本不一致", f"送审材料存在多个版本号: {', '.join(sorted(versions))}。", [str(item) for item in material_meta])
    if len(baselines) > 1:
        add("baseline_version_mismatch", "major", "跨文档基线不一致", f"送审材料存在多个基线标识: {', '.join(sorted(baselines))}。", [str(item) for item in material_meta])

    requirements = {item["requirement_id"] for item in result.get("requirements") or []}
    linked_requirements = {
        link.get("source_id")
        for link in _active_trace_links(result)
        if link.get("link_type") in {"satisfies", "verifies"}
    }
    for req_id in sorted(requirements - linked_requirements):
        add("missing_cross_document_reference", "major", "跨文档引用关系缺失", f"需求 {req_id} 未发现设计或验证文档引用。", [req_id])
    return items


def confirm_review_plus_trace_link(task: Any, link_id: str, user: str = "", rationale: str = "") -> dict[str, Any]:
    if not task.traceability_result:
        task.traceability_result = _build_review_plus_traceability_result(task)
    for link in task.traceability_result.get("trace_links") or []:
        if link.get("link_id") != link_id:
            continue
        link["status"] = "confirmed"
        link["confirmed_by"] = user or "human"
        link["confirmed_at"] = datetime.now().isoformat()
        link["rationale"] = rationale
        _replace_traceability_gap_items(task.traceability_result)
        _refresh_traceability_views(task.traceability_result)
        return task.traceability_result
    raise ValueError(f"Trace link not found: {link_id}")


def reject_review_plus_trace_link(task: Any, link_id: str, user: str = "", rationale: str = "") -> dict[str, Any]:
    if not task.traceability_result:
        task.traceability_result = _build_review_plus_traceability_result(task)
    for link in task.traceability_result.get("trace_links") or []:
        if link.get("link_id") != link_id:
            continue
        link["status"] = "rejected"
        link["rejected_by"] = user or "human"
        link["rejected_at"] = datetime.now().isoformat()
        link["rejection_reason"] = rationale
        _replace_traceability_gap_items(task.traceability_result)
        _refresh_traceability_views(task.traceability_result)
        return task.traceability_result
    raise ValueError(f"Trace link not found: {link_id}")


def _mark_limited_pass(svc: Any, review_id: str, warning: str) -> None:
    task = svc.get_review(review_id)
    if not task:
        return
    previous_status = task.status
    task.status = "limited_pass"
    task.updated_at = datetime.now().isoformat()
    svc.record_event(
        review_id,
        "review_limited",
        {
            "from_status": previous_status,
            "to_status": task.status,
            "warning": warning,
        },
    )


def execute_material_classification(review_id: str) -> dict[str, Any]:
    svc = _service()
    task = svc.classify_materials(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")
    return _step_payload(
        "material_classification",
        material_count=len(task.materials),
        roles=[
            {
                "name": material.name,
                "role": material.role.value if isinstance(material.role, ReviewPlusMaterialRole) else material.role,
                "confidence": material.role_confidence,
            }
            for material in task.materials
        ],
    )


def execute_scenario_detection(review_id: str) -> dict[str, Any]:
    from data_agent.review_plus.scenario_service import detect_review_plus_scenario

    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")
    result = detect_review_plus_scenario(task.materials)
    
    try:
        from data_agent.review_plus.agent_service import detect_scenario_with_agent, _agents_enabled
        if _agents_enabled():
            agent_result = detect_scenario_with_agent(task.materials, fallback=None)
            if agent_result is not None:
                result = agent_result
            else:
                svc.record_event(
                    review_id,
                    "agent_scenario_detection_failed_warning",
                    {"reason": "Agent scenario detection returned empty or fallback result"}
                )
    except Exception as exc:
        logger.warning("[ReviewPlus] Agent-based scenario detection bypassed: %s", exc)
        svc.record_event(
            review_id,
            "agent_scenario_detection_failed_warning",
            {"reason": str(exc)}
        )

    task.scenario = result.get("scenario", "")
    task.scenario_confidence = float(result.get("confidence") or 0.0)
    task.scenario_reason = result.get("reason", "")
    _save_task(svc, task)
    svc.update_status(
        review_id,
        ReviewPlusStatus.SCENARIO_DETECTED,
        event_type="scenario_detection_completed",
        payload=result,
    )
    return _step_payload("scenario_detection", **result)


def execute_rule_extraction(review_id: str) -> dict[str, Any]:
    from data_agent.review_plus.rule_extraction_service import extract_check_items

    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")

    svc.update_status(review_id, ReviewPlusStatus.RULE_EXTRACTING, event_type="rule_extraction_started")
    check_items = []
    for material in task.materials:
        role_value = material.role.value if isinstance(material.role, ReviewPlusMaterialRole) else material.role
        if role_value not in {
            ReviewPlusMaterialRole.REVIEW_RULE.value,
            ReviewPlusMaterialRole.CHECKLIST.value,
        }:
            continue
        deterministic_items = extract_check_items(
            file_path=material.file_path,
            material_name=material.name,
            content=material.content,
        )
        try:
            from data_agent.review_plus.agent_service import extract_check_items_with_agent, _agents_enabled
            if _agents_enabled():
                agent_items = extract_check_items_with_agent(material, deterministic_items)
                if agent_items:
                    deterministic_items = agent_items
                else:
                    svc.record_event(
                        review_id,
                        "agent_rule_extraction_failed_warning",
                        {"material_name": material.name, "reason": "Agent rule extraction returned empty or None"}
                    )
        except Exception as exc:
            logger.warning("[ReviewPlus] Agent-based rule extraction bypassed for %s: %s", material.name, exc)
            svc.record_event(
                review_id,
                "agent_rule_extraction_failed_warning",
                {"material_name": material.name, "reason": str(exc)}
            )

        for item in deterministic_items:
            item.source_role = role_value
        check_items.extend(deterministic_items)
    task.check_items = check_items
    task.updated_at = datetime.now().isoformat()
    if not check_items:
        raise ValueError("未识别到任何检查项，无法启动 Review-Plus multi-agent 审查")

    svc.update_status(
        review_id,
        ReviewPlusStatus.READY,
        event_type="rule_extraction_completed",
        payload={"check_item_count": len(check_items)},
    )
    return _step_payload("rule_extraction", check_item_count=len(check_items))


async def _structure_documents_async(review_id: str) -> dict[str, Any]:
    from data_agent.parsing.artifact_builder import (
        is_parse_artifact_complete,
        is_structure_artifact_complete,
    )
    from data_agent.parsing.parse_artifacts import (
        build_structure_artifact,
        merge_parse_and_structure,
    )

    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")
    parse_artifact = getattr(task, "parse_artifact", None) or {}
    if is_structure_artifact_complete(
        task.section_tree,
        task.evidence_pool,
        document_ir=getattr(task, "document_ir", None),
        parse_artifact=parse_artifact if isinstance(parse_artifact, dict) else None,
    ):
        stats = {
            "section_count": len((task.section_tree or {}).get("sections", [])),
            "evidence_count": len((task.evidence_pool or {}).get("evidences", [])),
            "chunk_count": len(task.parsed_documents or []),
            "reuse_source": "existing_parse_artifact",
        }
        svc.update_status(
            review_id,
            ReviewPlusStatus.STRUCTURING,
            event_type="document_structuring_reused",
            payload={"stats": stats, "warnings": []},
        )
        return _step_payload("document_structuring", stats=stats, warnings=[], reused=True)

    if not is_parse_artifact_complete(parse_artifact if isinstance(parse_artifact, dict) else None):
        execute_document_parsing(review_id)
        task = svc.get_review(review_id)
        if not task:
            raise ValueError(f"Review-Plus task not found after parsing: {review_id}")
        parse_artifact = getattr(task, "parse_artifact", None) or {}

    if is_parse_artifact_complete(parse_artifact if isinstance(parse_artifact, dict) else None):
        structure = build_structure_artifact(parse_artifact)
        merged = merge_parse_and_structure(parse_artifact, structure)
        task.section_tree = merged.section_tree
        task.evidence_pool = merged.evidence_pool
        task.document_ir = merged.document_ir
        task.parse_artifact = merged.model_dump(mode="json")
        task.updated_at = datetime.now().isoformat()
        _save_task(svc, task)
        stats = {
            "section_count": len((task.section_tree or {}).get("sections", [])),
            "evidence_count": len((task.evidence_pool or {}).get("evidences", [])),
            "chunk_count": len(task.parsed_documents or []),
            "reuse_source": "parse_artifact_structure_only",
        }
        svc.update_status(
            review_id,
            ReviewPlusStatus.STRUCTURING,
            event_type="document_structuring_from_parse_artifact",
            payload={"stats": stats, "warnings": list(structure.warnings or [])},
        )
        return _step_payload(
            "document_structuring",
            stats=stats,
            warnings=list(structure.warnings or []),
            reused=True,
        )

    raise ValueError("材料解析未完成，无法执行文档结构化")


def execute_document_parsing(review_id: str) -> dict[str, Any]:
    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")
    from data_agent.parsing.artifact_builder import is_parse_artifact_complete

    parse_artifact = getattr(task, "parse_artifact", None) or {}
    if isinstance(parse_artifact, dict) and is_parse_artifact_complete(parse_artifact):
        return _step_payload(
            "document_parsing",
            reused=True,
            batch_summary=parse_artifact.get("batch_summary") or {},
        )

    parsed_task = svc.parse_materials(review_id)
    if not parsed_task:
        raise ValueError(f"Review-Plus task not found: {review_id}")
    parse_artifact = getattr(parsed_task, "parse_artifact", None) or {}
    return _step_payload(
        "document_parsing",
        batch_summary=parse_artifact.get("batch_summary") or {} if isinstance(parse_artifact, dict) else {},
        warnings=list(parse_artifact.get("warnings") or []) if isinstance(parse_artifact, dict) else [],
    )


def execute_document_structuring(review_id: str) -> dict[str, Any]:
    return asyncio.run(_structure_documents_async(review_id))


def execute_chief_orchestration(review_id: str) -> dict[str, Any]:
    """总师动态组会：文档格式审查 + 专业 Agent 阵容规划。"""
    from data_agent.review_plus.specialist_orchestration_service import orchestrate_review_plus_specialists

    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")

    # 场景探针 (Semantic Scene Probe)
    has_pa = False
    for m in getattr(task, "materials", []) or []:
        name = (getattr(m, "name", "") or "").lower()
        content = (getattr(m, "content", "") or "")[:5000].lower()
        if any(kw in name for kw in ["产品保证", "蓬莱", "工作检查单", "质量保证", "检查单"]):
            has_pa = True
            break
        if any(kw in content for kw in ["质量特性", "符合性检查", "逻辑匹配", "一致性检查", "最坏情况", "最坏工况", "降额设计"]):
            has_pa = True
            break

    for item in getattr(task, "check_items", []) or []:
        title = (getattr(item, "title", "") or "").lower()
        req_text = (getattr(item, "requirement_text", "") or "").lower()
        desc = (getattr(item, "description", "") or "").lower()
        full_item_text = f"{title} {req_text} {desc}"
        if any(kw in full_item_text for kw in ["质量特性", "符合性检查", "逻辑匹配", "一致性检查", "最坏情况", "最坏工况", "降额设计", "产品保证"]):
            has_pa = True
            break
            
    if has_pa:
        task.scenario = "product_assurance_reliability_safety"

    result = orchestrate_review_plus_specialists(task)
    task.document_format_review = result["document_format_review"]
    task.chief_review_plan = result["chief_review_plan"]
    task.specialist_reviews = result["specialist_reviews"]
    _save_task(svc, task)
    selected_agents = task.chief_review_plan.get("selected_agents") or []
    format_findings = task.document_format_review.get("findings") or []
    svc.record_event(
        review_id,
        "chief_orchestration_completed",
        {
            "agent_count": len(selected_agents),
            "selected_agent_ids": [item.get("agent_id") for item in selected_agents],
            "document_format_finding_count": len(format_findings),
        },
    )
    return _step_payload(
        "chief_orchestration",
        agent_count=len(selected_agents),
        selected_agent_ids=[item.get("agent_id") for item in selected_agents],
        document_format_gate_status=task.document_format_review.get("gate_status", ""),
        document_format_finding_count=len(format_findings),
    )


def execute_rule_section_mapping(review_id: str) -> dict[str, Any]:
    """Step 4: 将检查项映射到文档章节。"""
    from data_agent.review_plus.evidence_mapping_service import map_check_items_to_evidence

    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")

    svc.update_status(review_id, ReviewPlusStatus.MAPPING, event_type="rule_section_mapping_started")

    mappings = map_check_items_to_evidence(task)
    mapping_agent_enabled = os.getenv("REVIEW_PLUS_AGENT_MAPPING_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not mapping_agent_enabled:
        svc.record_event(
            review_id,
            "agent_mapping_refinement_skipped",
            {"reason": "Agent mapping refinement is disabled; deterministic mapping is used"}
        )
    else:
        try:
            from data_agent.review_plus.agent_service import refine_mappings_with_agent, _agents_enabled
            if _agents_enabled():
                logger.info("[ReviewPlus] Agent-based mapping refinement started: review_id=%s", review_id)
                started_at = datetime.now()
                agent_mappings = refine_mappings_with_agent(task.check_items, mappings)
                elapsed_ms = int((datetime.now() - started_at).total_seconds() * 1000)
                logger.info("[ReviewPlus] Agent-based mapping refinement finished: review_id=%s elapsed_ms=%s", review_id, elapsed_ms)
                svc.record_event(
                    review_id,
                    "agent_mapping_refinement_completed",
                    {"elapsed_ms": elapsed_ms, "mapping_count": len(agent_mappings or [])}
                )
                if agent_mappings:
                    mappings = agent_mappings
                else:
                    svc.record_event(
                        review_id,
                        "agent_mapping_refinement_failed_warning",
                        {"reason": "Agent mapping refinement returned empty or None"}
                    )
        except Exception as exc:
            logger.warning("[ReviewPlus] Agent-based mapping refinement bypassed: %s", exc)
            svc.record_event(
                review_id,
                "agent_mapping_refinement_failed_warning",
                {"reason": str(exc)}
            )

    task.section_mappings = mappings
    task.updated_at = datetime.now().isoformat()

    mapped_count = sum(1 for m in mappings if m.section_ids)
    avg_confidence = (
        sum(m.confidence for m in mappings if m.section_ids) / mapped_count
        if mapped_count
        else 0.0
    )

    svc.update_status(
        review_id,
        ReviewPlusStatus.READY,
        event_type="rule_section_mapping_completed",
        payload={
            "mapped_count": mapped_count,
            "total_count": len(task.check_items),
            "avg_confidence": round(avg_confidence, 3),
        },
    )
    return _step_payload(
        "rule_section_mapping",
        mapped_count=mapped_count,
        total_count=len(task.check_items),
        avg_confidence=round(avg_confidence, 3),
    )


def execute_item_review(review_id: str) -> dict[str, Any]:
    """Step 5: Harness multi-agent 逐项符合性审查。"""
    from data_agent.review_plus.agent_harness import ReviewPlusAgentHarness

    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")

    if not task.check_items:
        raise ValueError("无检查项可审查")

    svc.update_status(review_id, ReviewPlusStatus.REVIEWING, event_type="item_review_started")

    harness_output = ReviewPlusAgentHarness().run(task)
    task.coverage_matrix = harness_output.coverage_matrix.model_dump(mode="json")
    task.agent_run_traces = [trace.model_dump(mode="json") for trace in harness_output.agent_run_traces]
    task.chief_review_plan = {
        **(task.chief_review_plan or {}),
        "harness_plan": harness_output.harness_plan.model_dump(mode="json"),
    }
    task.findings = harness_output.findings
    task.cross_document_review_items = list(harness_output.cross_document_items)
    task.updated_at = datetime.now().isoformat()

    from data_agent.review_plus.specialist_orchestration_service import refresh_specialist_reviews

    refresh_specialist_reviews(task)
    _save_task(svc, task)

    # 统计
    findings = task.findings
    satisfied = sum(1 for f in findings if f.judgment.value == "satisfied")
    not_satisfied = sum(1 for f in findings if f.judgment.value == "not_satisfied")
    insufficient = sum(1 for f in findings if f.judgment.value == "insufficient_evidence")
    not_checked = sum(1 for f in findings if f.judgment.value == "not_checked")
    critical = sum(1 for f in findings if f.severity.value == "critical")

    svc.update_status(
        review_id,
        ReviewPlusStatus.REPORTING,
        event_type="item_review_completed",
        payload={
            "finding_count": len(findings),
            "satisfied": satisfied,
            "not_satisfied": not_satisfied,
            "insufficient": insufficient,
            "not_checked": not_checked,
            "critical": critical,
            "agent_states": {
                trace.get("agent_id"): {
                    "status": "completed",
                    "duration_ms": trace.get("elapsed_ms") or 0,
                    "findings_found": len([f for f in findings if f.check_item_id in (trace.get("check_item_ids") or [])]),
                }
                for trace in task.agent_run_traces
            },
            "findings_summary": [
                {
                    "finding_id": f.finding_id,
                    "title": f.title,
                    "judgment": f.judgment.value,
                    "severity": f.severity.value,
                }
                for f in findings[:15]
            ]
        },
    )
    return _step_payload(
        "item_review",
        finding_count=len(findings),
        satisfied=satisfied,
        not_satisfied=not_satisfied,
        insufficient=insufficient,
        not_checked=not_checked,
        critical=critical,
    )


def execute_traceability(review_id: str) -> dict[str, Any]:
    """构建需求闭环追溯矩阵。"""
    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")

    svc.update_status(review_id, ReviewPlusStatus.TRACEABILITY_BUILDING, event_type="traceability_started")
    from data_agent.review_plus.traceability_p0_adapter import build_review_plus_traceability_result

    task.traceability_result = build_review_plus_traceability_result(task)
    traceability_gap_items = list(task.traceability_result.get("review_items") or [])
    existing_cross_items = list(task.cross_document_review_items or [])
    task.cross_document_review_items = [
        *existing_cross_items,
        *traceability_gap_items,
    ]
    from data_agent.review_plus.specialist_orchestration_service import refresh_specialist_reviews

    refresh_specialist_reviews(task)
    _save_task(svc, task)
    summary = task.traceability_result.get("summary") or {}
    svc.update_status(
        review_id,
        ReviewPlusStatus.READY,
        event_type="traceability_completed",
        payload=summary,
    )
    return _step_payload(
        "traceability",
        requirement_count=summary.get("requirement_count", 0),
        design_item_count=summary.get("design_item_count", 0),
        verification_claim_count=summary.get("verification_claim_count", 0),
        trace_link_count=summary.get("trace_link_count", 0),
        design_closure_coverage=summary.get("design_closure_coverage", 0.0),
        verification_coverage=summary.get("verification_coverage", 0.0),
    )


def execute_cross_document_review(review_id: str) -> dict[str, Any]:
    """跨文档一致性审查。"""
    from data_agent.review_plus.evidence_mapping_service import build_semantic_cross_document_items

    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")
    if not task.traceability_result:
        from data_agent.review_plus.traceability_p0_adapter import build_review_plus_traceability_result

        task.traceability_result = build_review_plus_traceability_result(task)

    p0_typed_items = list(task.traceability_result.get("review_items") or [])
    supplemental_cross_items = []
    for item in [
        *_build_cross_document_items(task),
        *build_semantic_cross_document_items(task),
    ]:
        item.setdefault("method", "deterministic" if str(item.get("review_item_id", "")).startswith("rp-cross-") else "semantic")
        item.setdefault("detection_method", item.get("method", "semantic"))
        supplemental_cross_items.append(item)

    deterministic_cross_items = list(supplemental_cross_items)

    try:
        from data_agent.review_plus.agent_service import build_cross_document_items_with_agent, _agents_enabled
        if _agents_enabled():
            agent_cross_items = build_cross_document_items_with_agent(task, deterministic_cross_items)
            if agent_cross_items:
                deterministic_cross_items = agent_cross_items
            else:
                svc.record_event(
                    review_id,
                    "agent_cross_document_review_failed_warning",
                    {"reason": "Agent cross document review returned empty or None"}
                )
    except Exception as exc:
        logger.warning("[ReviewPlus] Agent-based cross document review bypassed: %s", exc)
        svc.record_event(
            review_id,
            "agent_cross_document_review_failed_warning",
            {"reason": str(exc)}
        )

    task.cross_document_review_items = [
        *p0_typed_items,
        *list(task.cross_document_review_items or []),
        *deterministic_cross_items,
    ]
    deduped_cross_items: list[dict[str, Any]] = []
    seen_cross_item_keys: set[tuple[str, str, str]] = set()
    for item in task.cross_document_review_items:
        key = (
            str(item.get("item_type", "")),
            str(item.get("title", "")),
            str(item.get("description", "")),
        )
        if key in seen_cross_item_keys:
            continue
        seen_cross_item_keys.add(key)
        deduped_cross_items.append(item)
    task.cross_document_review_items = deduped_cross_items
    # 保留 P0 typed items，追加语义/agent 补充项（避免覆盖源等价 review_items）
    preserved_p0_items = [
        item
        for item in (task.traceability_result.get("review_items") or [])
        if str(item.get("review_item_id", "")).startswith("p0-")
    ]
    task.traceability_result["review_items"] = [
        *preserved_p0_items,
        *task.cross_document_review_items,
    ]
    _refresh_traceability_views(task.traceability_result)
    from data_agent.review_plus.specialist_orchestration_service import refresh_specialist_reviews

    refresh_specialist_reviews(task)
    _save_task(svc, task)
    severity_counts = defaultdict(int)
    for item in task.cross_document_review_items:
        severity_counts[item.get("severity", "unknown")] += 1
    svc.record_event(
        review_id,
        "cross_document_review_completed",
        {
            "review_item_count": len(task.cross_document_review_items),
            "severity_counts": dict(severity_counts),
        },
    )
    return _step_payload(
        "cross_document_review",
        review_item_count=len(task.cross_document_review_items),
        severity_counts=dict(severity_counts),
    )


def execute_report_composition(review_id: str) -> dict[str, Any]:
    """Step 6: 归并 findings 生成审查报告。

    复用 GNC review 的 editorial_synthesis 模式：
      - 统计汇总
      - 归并 findings
      - 生成结论
    """
    from data_agent.review_plus.schemas import ReviewPlusReport
    from data_agent.review_plus.report_service import build_review_plus_markdown, persist_review_plus_markdown

    svc = _service()
    task = svc.get_review(review_id)
    if not task:
        raise ValueError(f"Review-Plus task not found: {review_id}")

    if not task.check_items:
        raise ValueError("未识别到任何检查项，无法生成审查报告")
    if not task.coverage_matrix:
        raise ValueError("缺少 multi-agent 覆盖矩阵，无法生成审查报告")

    svc.update_status(review_id, ReviewPlusStatus.REPORTING, event_type="report_composition_started")

    findings = task.findings
    check_items_by_id = {item.check_item_id: item for item in task.check_items}

    # ── 先构造确定性底稿，再交给 Review-Plus 合稿师 Agent 复核增强 ──
    satisfied = [f for f in findings if f.judgment.value == "satisfied"]
    not_satisfied = [f for f in findings if f.judgment.value == "not_satisfied"]
    insufficient = [f for f in findings if f.judgment.value == "insufficient_evidence"]
    not_checked = [f for f in findings if f.judgment.value == "not_checked"]
    critical = [f for f in findings if f.severity.value == "critical"]
    cross_document_items = list(task.cross_document_review_items or [])
    cross_critical = [item for item in cross_document_items if item.get("severity") == "critical"]
    cross_major = [item for item in cross_document_items if item.get("severity") == "major"]

    # 结论生成
    if critical or cross_critical:
        conclusion = (
            f"审查发现 {len(critical) + len(cross_critical)} 条关键问题，"
            f"共 {len(not_satisfied)} 条不满足项、{len(cross_document_items)} 条多文档审查问题，建议整改后重新审查。"
        )
    elif not_satisfied:
        conclusion = (
            f"审查发现 {len(not_satisfied)} 条不满足项（无关键问题），"
            f"建议针对性整改。"
        )
    elif cross_major:
        conclusion = (
            f"审查发现 {len(cross_major)} 条主要多文档一致性或印证关系问题，"
            "建议补充引用关系和支撑证据后再闭环。"
        )
    elif insufficient:
        conclusion = (
            f"审查发现 {len(insufficient)} 条证据不足项，"
            f"建议补充材料后重新审查。"
        )
    elif not_checked:
        conclusion = f"审查有 {len(not_checked)} 条未能完成审查，建议排查原因后重新执行。"
    else:
        conclusion = "所有检查项均满足要求，审查通过。"

    # 摘要
    total = len(task.check_items) or len(findings)
    summary_parts = [
        f"本次审查共 {total} 条检查项。",
        f"满足: {len(satisfied)}",
        f"不满足: {len(not_satisfied)}",
        f"证据不足: {len(insufficient)}",
        f"未检查: {len(not_checked)}",
        f"多文档问题: {len(cross_document_items)}",
    ]
    summary = "\n".join(summary_parts)

    # 残余风险
    residual_risks = []
    if insufficient:
        residual_risks.append(
            f"有 {len(insufficient)} 条检查项证据不足，可能存在未发现的问题。"
        )
    if not_checked:
        residual_risks.append(
            f"有 {len(not_checked)} 条检查项未完成审查，审查覆盖不完整。"
        )
    low_conf = [f for f in findings if f.confidence < 0.5 and f.judgment.value != "satisfied"]
    if low_conf:
        residual_risks.append(
            f"有 {len(low_conf)} 条审查结论置信度低于 0.5，建议人工复核。"
        )
    if cross_document_items:
        residual_risks.append(
            f"有 {len(cross_document_items)} 条多文档一致性或印证关系问题需要闭环。"
        )

    # 交叉引用：检查同一检查项多次出现的 findings
    cross_refs: list[dict[str, Any]] = []
    # （当前 MVP 每个检查项只有一条 finding，交叉引用为空）

    deterministic_report = ReviewPlusReport(
        total_check_items=total,
        satisfied_count=len(satisfied),
        not_satisfied_count=len(not_satisfied),
        insufficient_evidence_count=len(insufficient),
        not_checked_count=len(not_checked),
        critical_count=len(critical),
        findings=findings,
        conclusion=conclusion,
        summary=summary,
        residual_risks=residual_risks,
        cross_references=cross_refs,
        cross_document_items=cross_document_items,
    )

    from data_agent.review_plus.chief_comprehensive_review_service import run_chief_comprehensive_review

    chief_comprehensive = run_chief_comprehensive_review(task, deterministic_report)
    deterministic_report = deterministic_report.model_copy(
        update={"chief_comprehensive_review": chief_comprehensive},
    )
    if chief_comprehensive.overall_assessment and chief_comprehensive.status in {"ok", "degraded"}:
        deterministic_report.conclusion = chief_comprehensive.overall_assessment
    if chief_comprehensive.key_risks:
        merged_risks = list(dict.fromkeys([*deterministic_report.residual_risks, *chief_comprehensive.key_risks]))
        deterministic_report.residual_risks = merged_risks[:12]
    svc.record_event(
        review_id,
        "chief_comprehensive_review_completed",
        {
            "status": chief_comprehensive.status,
            "method": chief_comprehensive.method,
            "conclusion_count": len(chief_comprehensive.engineering_conclusions),
            "degraded": chief_comprehensive.degraded,
            "release_recommendation": chief_comprehensive.release_recommendation,
        },
    )

    report = deterministic_report
    try:
        from data_agent.review_plus.agent_service import compose_report_with_agent, _agents_enabled
        if _agents_enabled():
            agent_report = compose_report_with_agent(task, deterministic_report)
            if agent_report:
                report = agent_report
            else:
                svc.record_event(
                    review_id,
                    "agent_report_composition_failed_warning",
                    {"reason": "Agent report composition returned empty or None"}
                )
    except Exception as exc:
        logger.warning("[ReviewPlus] Agent-based report composition bypassed: %s", exc)
        svc.record_event(
            review_id,
            "agent_report_composition_failed_warning",
            {"reason": str(exc)}
        )

    task.report = report
    report.markdown = build_review_plus_markdown(task)
    task.report_markdown = report.markdown
    task.report_file_path = persist_review_plus_markdown(task)
    task.updated_at = datetime.now().isoformat()

    svc.update_status(
        review_id,
        ReviewPlusStatus.COMPLETED,
        event_type="report_composition_completed",
        payload={
            "report_id": report.report_id,
            "total": report.total_check_items,
            "satisfied": report.satisfied_count,
            "not_satisfied": report.not_satisfied_count,
            "critical": report.critical_count,
            "coverage_matrix": task.coverage_matrix.get("summary", {}),
        },
    )
    return _step_payload(
        "report_composition",
        report_id=report.report_id,
        total=report.total_check_items,
        satisfied=report.satisfied_count,
        not_satisfied=report.not_satisfied_count,
        critical=report.critical_count,
        conclusion=conclusion,
    )


def material_classification_step(step_input: StepInput) -> StepOutput:
    result = execute_material_classification(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def scenario_detection_step(step_input: StepInput) -> StepOutput:
    result = execute_scenario_detection(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def rule_extraction_step(step_input: StepInput) -> StepOutput:
    result = execute_rule_extraction(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def document_parsing_step(step_input: StepInput) -> StepOutput:
    result = execute_document_parsing(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def document_structuring_step(step_input: StepInput) -> StepOutput:
    result = execute_document_structuring(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def chief_orchestration_step(step_input: StepInput) -> StepOutput:
    result = execute_chief_orchestration(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def rule_section_mapping_step(step_input: StepInput) -> StepOutput:
    result = execute_rule_section_mapping(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def item_review_step(step_input: StepInput) -> StepOutput:
    result = execute_item_review(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def traceability_step(step_input: StepInput) -> StepOutput:
    result = execute_traceability(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def cross_document_review_step(step_input: StepInput) -> StepOutput:
    result = execute_cross_document_review(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def report_composition_step(step_input: StepInput) -> StepOutput:
    result = execute_report_composition(_extract_review_id(step_input))
    return StepOutput(content=json.dumps(result, ensure_ascii=False))


def run_review_plus_workflow(review_id: str) -> dict[str, Any]:
    """Run the MVP workflow deterministically for service/background use."""
    logger.info("[ReviewPlus] Running workflow for task: %s", review_id)
    svc = _service()
    steps = [
        ("material_classification", execute_material_classification),
        ("scenario_detection", execute_scenario_detection),
        ("document_parsing", execute_document_parsing),
        ("document_structuring", execute_document_structuring),
        ("chief_orchestration", execute_chief_orchestration),
        ("rule_extraction", execute_rule_extraction),
        ("rule_section_mapping", execute_rule_section_mapping),
        ("item_review", execute_item_review),
        ("traceability", execute_traceability),
        ("cross_document_review", execute_cross_document_review),
        ("report_composition", execute_report_composition),
    ]
    outputs = []
    for step_name, executor in steps:
        try:
            output = executor(review_id)
            outputs.append(output)
        except Exception as exc:
            logger.exception("[ReviewPlus] Workflow failed at step %s: %s", step_name, exc)
            agent_id = getattr(exc, "agent_id", "")
            error_code = getattr(exc, "error_code", "workflow_step_failed")
            agent_run_traces = [
                trace.model_dump(mode="json") if hasattr(trace, "model_dump") else trace
                for trace in (getattr(exc, "agent_run_traces", []) or [])
            ]
            if agent_run_traces:
                task = svc.get_review(review_id)
                if task:
                    task.agent_run_traces = agent_run_traces
                    _save_task(svc, task)
            svc.update_status(
                review_id,
                ReviewPlusStatus.FAILED,
                event_type="workflow_failed",
                payload={
                    "failed_step": step_name,
                    "agent_id": agent_id,
                    "error_code": error_code,
                    "error_message": str(exc),
                },
            )
            return {
                "review_id": review_id,
                "outputs": outputs,
                "failed_step": step_name,
                "agent_id": agent_id,
                "error_code": error_code,
                "error": str(exc),
            }
    return {"review_id": review_id, "outputs": outputs}


@WorkflowFactory.register(
    "aero:review_plus_workflow",
    name="Review-Plus 审查链路",
    description="Review-Plus MVP: 材料分类 → 文档结构化 → 检查项抽取 → 映射/审查/报告占位",
    domain="aero",
    steps=[
        "material_classification",
        "scenario_detection",
        "document_parsing",
        "document_structuring",
        "chief_orchestration",
        "rule_extraction",
        "rule_section_mapping",
        "item_review",
        "traceability",
        "cross_document_review",
        "report_composition",
    ],
)
def get_review_plus_workflow(
    model_id: str = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    debug_mode: bool = True,
    **kwargs,
) -> Workflow:
    return Workflow(
        id="aero:review_plus_workflow",
        name="Review-Plus 审查链路",
        description="独立 Review-Plus MVP 审查工作流",
        steps=[
            Step(
                name="material_classification",
                executor=material_classification_step,
                description="材料角色分类",
            ),
            Step(
                name="scenario_detection",
                executor=scenario_detection_step,
                description="审查场景识别",
            ),
            Step(
                name="document_parsing",
                executor=document_parsing_step,
                description="Step 3 材料解析（parse-only artifact）",
            ),
            Step(
                name="document_structuring",
                executor=document_structuring_step,
                description="结构化待审文档并生成章节树/证据池",
            ),
            Step(
                name="chief_orchestration",
                executor=chief_orchestration_step,
                description="总师动态组会并规划专业 Agent 阵容",
            ),
            Step(
                name="rule_extraction",
                executor=rule_extraction_step,
                description="从审查规则材料抽取检查项",
            ),
            Step(
                name="rule_section_mapping",
                executor=rule_section_mapping_step,
                description="检查项到文档章节映射占位",
            ),
            Step(
                name="item_review",
                executor=item_review_step,
                description="逐项审查占位",
            ),
            Step(
                name="traceability",
                executor=traceability_step,
                description="需求闭环追溯矩阵构建",
            ),
            Step(
                name="cross_document_review",
                executor=cross_document_review_step,
                description="跨文档一致性审查",
            ),
            Step(
                name="report_composition",
                executor=report_composition_step,
                description="审查报告生成占位",
            ),
        ],
        session_id=session_id,
        user_id=user_id,
    )


__all__ = [
    "get_review_plus_workflow",
    "run_review_plus_workflow",
    "material_classification_step",
    "scenario_detection_step",
    "rule_extraction_step",
    "document_parsing_step",
    "document_structuring_step",
    "chief_orchestration_step",
    "rule_section_mapping_step",
    "item_review_step",
    "traceability_step",
    "cross_document_review_step",
    "execute_scenario_detection",
    "execute_chief_orchestration",
    "execute_traceability",
    "execute_cross_document_review",
    "confirm_review_plus_trace_link",
    "reject_review_plus_trace_link",
    "report_composition_step",
]
