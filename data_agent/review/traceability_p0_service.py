"""P0 requirement closure traceability service.

This service is intentionally deterministic. It extracts explicit IDs and
typed relationships from controlled review-package text and generates a
read-only closure matrix plus P0 cross-document review items.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from data_agent.review.p0_schemas import (
    CrossDocumentReviewItem,
    DesignImplementationItem,
    MaterialItem,
    RequirementNode,
    RequirementTraceLink,
    ReviewTask,
    TraceabilityResult,
    VerificationClaim,
)
from data_agent.review.cross_document_review_service import generate_cross_document_review_items
from data_agent.review.cross_document_evidence_aggregator import attach_cross_document_evidence_chains
from data_agent.review.cross_document_object_registry import build_cross_document_object_registry
from data_agent.review.material_role_service import infer_material_role
from data_agent.review.package_gatekeeping_service import traceability_gate_payload
from data_agent.review.trace_link_utils import active_trace_links
from data_agent.review.p0_shared_constants import (
    P0_GATEKEEPING_ROLE_LABELS,
    REQ_RE,
    DES_RE,
    VER_RE,
    material_summary as build_material_summary,
)
from data_agent.review.traceability_text_utils import (
    condition_tags,
    infer_pass_fail,
    infer_verification_method,
    normalize_comparator,
)
from data_agent.review.unit_normalization_service import normalize_unit
_NUMBER_RE = re.compile(
    r"(?P<comparator><=|>=|≤|≥|不大于|不小于|小于|大于|不超过|不少于)?\s*"
    r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mm/s|m/s|km/s|deg/s|rad/s|mHz|Hz|kPa|Pa|mW|kW|W|mN|N|km|mm|kg|g|deg|rad|°/s|°|ms|s|m|%)?",
    re.IGNORECASE,
)


def suggest_roles_for_task(task: ReviewTask) -> bool:
    """Fill role suggestions for materials that do not have a role yet."""
    changed = False
    for material in task.materials.materials if task.materials else []:
        if material.document_role:
            continue
        suggestion = infer_material_role(material.name, material.content, material.file_type)
        material.document_role = suggestion.document_role
        material.role_confidence = suggestion.confidence
        material.role_reason = suggestion.reason
        changed = True
    return changed


def build_traceability_result(task: ReviewTask) -> TraceabilityResult:
    suggest_roles_for_task(task)
    materials = [m for m in (task.materials.materials if task.materials else []) if m.included_in_formal_review]
    gate = _build_gate(task, materials)

    requirements = _extract_requirements(materials)
    design_items = _extract_design_items(materials)
    verification_claims = _extract_verification_claims(materials)
    object_registry = build_cross_document_object_registry(materials, requirements, design_items, verification_claims)
    links = _build_links(requirements, design_items, verification_claims, object_registry)
    review_items = generate_cross_document_review_items(requirements, design_items, verification_claims, links, materials)
    evidence_chains = attach_cross_document_evidence_chains(
        review_items,
        requirements,
        design_items,
        verification_claims,
        links,
        object_registry,
    )
    matrix_rows = _build_matrix_rows(requirements, design_items, verification_claims, links, review_items)
    summary = _build_summary(requirements, design_items, verification_claims, links, review_items, gate)

    return TraceabilityResult(
        review_id=task.review_id,
        gate_status=gate["gate_status"],
        gate_summary=gate["gate_summary"],
        blocking_reasons=gate["blocking_reasons"],
        limited_scope=gate["limited_scope"],
        missing_materials=gate["missing_materials"],
        parsing_failed_materials=gate["parsing_failed_materials"],
        formal_materials_cache=[material.model_dump(mode="json") for material in materials],
        materials=[_material_summary(m) for m in materials],
        requirements=requirements,
        design_items=design_items,
        verification_claims=verification_claims,
        trace_links=links,
        object_registry=object_registry,
        evidence_chains=evidence_chains,
        matrix_rows=matrix_rows,
        review_items=review_items,
        summary=summary,
    )


def confirm_trace_link(
    result: dict[str, Any],
    link_id: str,
    user: str = "",
    rationale: str = "",
    materials: list[MaterialItem] | None = None,
) -> dict[str, Any]:
    return _update_trace_link(result, link_id, status="confirmed", user=user, rationale=rationale, materials=materials)


def reject_trace_link(
    result: dict[str, Any],
    link_id: str,
    user: str = "",
    rationale: str = "",
    materials: list[MaterialItem] | None = None,
) -> dict[str, Any]:
    return _update_trace_link(result, link_id, status="rejected", user=user, rationale=rationale, materials=materials)


def _update_trace_link(
    result: dict[str, Any],
    link_id: str,
    status: str,
    user: str,
    rationale: str,
    materials: list[MaterialItem] | None = None,
) -> dict[str, Any]:
    links = result.get("trace_links") or []
    for link in links:
        if link.get("link_id") != link_id:
            continue
        link["status"] = status
        if status == "confirmed":
            link["confirmed_by"] = user or "human"
            link["confirmed_at"] = datetime.now().isoformat()
            link["rationale"] = rationale
        elif status == "rejected":
            link["rejected_by"] = user or "human"
            link["rejected_at"] = datetime.now().isoformat()
            link["rejection_reason"] = rationale
        return _recompute_traceability_derived_views(result, materials=materials)
    raise ValueError(f"Trace link not found: {link_id}")


_MATERIAL_DERIVED_REVIEW_ITEM_TYPES = frozenset({"baseline_version_mismatch"})


def _resolve_formal_materials(
    result: dict[str, Any],
    materials: list[MaterialItem] | None,
) -> list[MaterialItem]:
    if materials is not None:
        return [material for material in materials if material.included_in_formal_review]

    cached = result.get("formal_materials_cache") or []
    if cached:
        return [
            MaterialItem.model_validate(item)
            for item in cached
            if item.get("included_in_formal_review", True)
        ]

    summaries = result.get("materials") or []
    if summaries:
        return [
            MaterialItem(
                name=str(item.get("name") or ""),
                file_type=str(item.get("file_type") or ""),
                document_role=str(item.get("document_role") or ""),
                document_version=str(item.get("document_version") or ""),
                baseline_id=str(item.get("baseline_id") or ""),
                included_in_formal_review=bool(item.get("included_in_formal_review", True)),
                role_confirmed=bool(item.get("role_confirmed", False)),
            )
            for item in summaries
            if item.get("included_in_formal_review", True)
        ]
    return []


def _preserve_material_derived_review_items(
    previous_items: list[dict[str, Any]],
    review_items: list[CrossDocumentReviewItem],
) -> list[CrossDocumentReviewItem]:
    preserved = [
        CrossDocumentReviewItem.model_validate(item)
        for item in previous_items
        if item.get("item_type") in _MATERIAL_DERIVED_REVIEW_ITEM_TYPES
    ]
    if not preserved:
        return review_items
    non_material_items = [
        item for item in review_items if item.item_type not in _MATERIAL_DERIVED_REVIEW_ITEM_TYPES
    ]
    return [*preserved, *non_material_items]


def _recompute_traceability_derived_views(
    result: dict[str, Any],
    materials: list[MaterialItem] | None = None,
) -> dict[str, Any]:
    """Recompute matrix, review items, evidence chains, and summary after link changes."""
    requirements = [RequirementNode.model_validate(item) for item in result.get("requirements") or []]
    design_items = [DesignImplementationItem.model_validate(item) for item in result.get("design_items") or []]
    verification_claims = [VerificationClaim.model_validate(item) for item in result.get("verification_claims") or []]
    links = [RequirementTraceLink.model_validate(item) for item in result.get("trace_links") or []]
    object_registry = result.get("object_registry") or {}
    formal_materials = _resolve_formal_materials(result, materials)
    previous_review_items = list(result.get("review_items") or [])
    gate = {"gate_status": result.get("gate_status") or (result.get("summary") or {}).get("gate_status", "blocked")}

    review_items = generate_cross_document_review_items(
        requirements,
        design_items,
        verification_claims,
        links,
        formal_materials,
    )
    if not formal_materials:
        review_items = _preserve_material_derived_review_items(previous_review_items, review_items)
    evidence_chains = attach_cross_document_evidence_chains(
        review_items,
        requirements,
        design_items,
        verification_claims,
        links,
        object_registry,
    )
    matrix_rows = _build_matrix_rows(requirements, design_items, verification_claims, links, review_items)
    summary = _build_summary(requirements, design_items, verification_claims, links, review_items, gate)

    result["review_items"] = [item.model_dump(mode="json") for item in review_items]
    result["evidence_chains"] = evidence_chains
    result["matrix_rows"] = matrix_rows
    result["summary"] = summary
    if formal_materials and not result.get("formal_materials_cache"):
        result["formal_materials_cache"] = [
            material.model_dump(mode="json") for material in formal_materials
        ]
    return result


def _build_gate(task: ReviewTask, materials: list[MaterialItem]) -> dict[str, Any]:
    return traceability_gate_payload(task)


def _extract_requirements(materials: list[MaterialItem]) -> list[RequirementNode]:
    result: list[RequirementNode] = []
    seen: set[str] = set()
    for material in materials:
        if material.document_role not in ("top_requirement", "decomposed_requirement"):
            continue
        level = "top" if material.document_role == "top_requirement" else "decomposed"
        for index, line in enumerate(_iter_candidate_lines(material.content)):
            req_ids = REQ_RE.findall(line)
            if not req_ids:
                continue
            req_id = req_ids[0]
            if req_id in seen:
                continue
            seen.add(req_id)
            metric = _extract_metric(line, value_role="requirement")
            parents = [rid for rid in req_ids[1:] if rid != req_id]
            result.append(RequirementNode(
                requirement_id=req_id,
                external_req_id=req_id,
                title=_title_from_line(line, req_id),
                text=line,
                requirement_level=level,
                parent_requirement_ids=parents,
                metric_id=metric["metric_id"],
                metric_name=metric["metric_name"],
                comparator=metric["comparator"],
                target_value=metric["value"],
                unit=metric["unit"],
                condition_tags=condition_tags(line),
                source_file_name=material.name,
                source_section_id=f"{material.name}:line-{index + 1}",
                source_evidence_id=f"ev:{material.name}:line-{index + 1}",
                source_quote=line,
                confidence=0.9,
            ))
    return result


def _extract_design_items(materials: list[MaterialItem]) -> list[DesignImplementationItem]:
    result: list[DesignImplementationItem] = []
    seen: set[str] = set()
    for material in materials:
        if material.document_role not in ("design_solution", "interface_control"):
            continue
        for index, line in enumerate(_iter_candidate_lines(material.content)):
            design_ids = DES_RE.findall(line)
            if not design_ids:
                continue
            design_id = design_ids[0]
            if design_id in seen:
                continue
            seen.add(design_id)
            metric = _extract_metric(line, value_role="observed")
            result.append(DesignImplementationItem(
                design_item_id=design_id,
                title=_title_from_line(line, design_id),
                text=line,
                item_type=_infer_design_type(line),
                satisfies_requirement_ids=REQ_RE.findall(line),
                metric_id=metric["metric_id"],
                observed_value=metric["value"],
                unit=metric["unit"],
                source_file_name=material.name,
                source_section_id=f"{material.name}:line-{index + 1}",
                source_evidence_id=f"ev:{material.name}:line-{index + 1}",
                source_quote=line,
                confidence=0.88,
            ))
    return result


def _extract_verification_claims(materials: list[MaterialItem]) -> list[VerificationClaim]:
    result: list[VerificationClaim] = []
    seen: set[str] = set()
    for material in materials:
        if material.document_role not in ("simulation_report", "verification_plan", "verification_result"):
            continue
        for index, line in enumerate(_iter_candidate_lines(material.content)):
            ver_ids = VER_RE.findall(line)
            if not ver_ids and not REQ_RE.search(line):
                continue
            ver_id = ver_ids[0] if ver_ids else f"VER-{material.name}-{index + 1}"
            if ver_id in seen:
                continue
            seen.add(ver_id)
            metric = _extract_metric(line, value_role="observed")
            result.append(VerificationClaim(
                verification_id=ver_id,
                title=_title_from_line(line, ver_id),
                method=infer_verification_method(line, material.document_role),
                verifies_requirement_ids=REQ_RE.findall(line),
                verifies_design_item_ids=DES_RE.findall(line),
                status="completed" if material.document_role in ("simulation_report", "verification_result") else "planned",
                pass_fail=infer_pass_fail(line),
                metric_id=metric["metric_id"],
                observed_value=metric["value"],
                unit=metric["unit"],
                source_file_name=material.name,
                source_section_id=f"{material.name}:line-{index + 1}",
                source_evidence_id=f"ev:{material.name}:line-{index + 1}",
                source_quote=line,
                confidence=0.86,
            ))
    return result


def _build_links(
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
    object_registry: dict[str, Any] | None = None,
) -> list[RequirementTraceLink]:
    links: list[RequirementTraceLink] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source: str, target: str, link_type: str, quote: str, evidence_id: str, confidence: float):
        key = (source, target, link_type)
        if not source or not target or key in seen:
            return
        seen.add(key)
        links.append(RequirementTraceLink(
            link_id=f"p0-{link_type}-{len(links) + 1}",
            source_id=source,
            target_id=target,
            link_type=link_type,
            status="candidate",
            confidence=confidence,
            evidence_ids=[evidence_id] if evidence_id else [],
            source_quote=quote,
        ))

    for req in requirements:
        for parent in req.parent_requirement_ids:
            add(parent, req.requirement_id, "decomposes", req.source_quote, req.source_evidence_id, 0.92)
    top_requirements = [req for req in requirements if req.requirement_level == "top"]
    decomposed_requirements = [req for req in requirements if req.requirement_level == "decomposed"]
    for top in top_requirements:
        for child in decomposed_requirements:
            if child.parent_requirement_ids:
                continue
            score = _artifact_similarity(top, child)
            if score >= 0.72:
                add(top.requirement_id, child.requirement_id, "decomposes", child.source_quote, child.source_evidence_id, score)
    for item in design_items:
        for req_id in item.satisfies_requirement_ids:
            add(req_id, item.design_item_id, "satisfies", item.source_quote, item.source_evidence_id, 0.9)
    for req in decomposed_requirements:
        for item in design_items:
            if item.satisfies_requirement_ids:
                continue
            score = _artifact_similarity(req, item)
            if score >= 0.68 and not _looks_like_unallocated_design(item):
                add(req.requirement_id, item.design_item_id, "satisfies", item.source_quote, item.source_evidence_id, score)
    for claim in verification_claims:
        for req_id in claim.verifies_requirement_ids:
            add(req_id, claim.verification_id, "verifies", claim.source_quote, claim.source_evidence_id, 0.9)
        for design_id in claim.verifies_design_item_ids:
            add(design_id, claim.verification_id, "verifies", claim.source_quote, claim.source_evidence_id, 0.85)
    for ref in (object_registry or {}).get("references", []):
        source_id = ref.get("source_id", "")
        target_id = ref.get("target_id", "")
        relation_type = ref.get("relation_type", "")
        source_type = ref.get("source_type", "")
        evidence_id = (ref.get("evidence_ids") or [""])[0]
        if relation_type == "decomposes" and source_type == "requirement":
            add(target_id, source_id, "decomposes", "", evidence_id, 0.9)
        elif relation_type == "references_requirement" and source_type == "requirement":
            add(source_id, target_id, "references_requirement", "", evidence_id, 0.88)
        elif relation_type == "satisfies" and source_type == "design_item":
            add(target_id, source_id, "satisfies", "", evidence_id, 0.9)
        elif relation_type == "verifies" and source_type == "verification_claim":
            add(target_id, source_id, "verifies", "", evidence_id, 0.88)
    return links


def _build_matrix_rows(
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
    links: list[RequirementTraceLink],
    review_items: list[CrossDocumentReviewItem],
) -> list[dict[str, Any]]:
    req_by_id = {item.requirement_id: item for item in requirements}
    design_by_id = {item.design_item_id: item for item in design_items}
    ver_by_id = {item.verification_id: item for item in verification_claims}
    children = defaultdict(list)
    designs = defaultdict(list)
    verifications = defaultdict(list)
    issues = defaultdict(list)

    for link in active_trace_links(links):
        if link.link_type == "decomposes":
            children[link.source_id].append(link.target_id)
        elif link.link_type == "satisfies":
            designs[link.source_id].append(link.target_id)
        elif link.link_type == "verifies":
            verifications[link.source_id].append(link.target_id)
    for item in review_items:
        for artifact_id in item.source_artifact_ids + item.target_artifact_ids:
            issues[artifact_id].append(item.review_item_id)

    rows: list[dict[str, Any]] = []
    top_requirements = [req for req in requirements if req.requirement_level == "top"] or requirements
    for top in top_requirements:
        child_ids = children.get(top.requirement_id) or [""]
        for child_id in child_ids:
            child = req_by_id.get(child_id)
            design_ids = designs.get(child_id) if child_id else []
            if not design_ids:
                design_ids = [""]
            for design_id in design_ids:
                verification_ids = verifications.get(child_id) or verifications.get(design_id) or [""]
                for verification_id in verification_ids:
                    issue_ids = list(dict.fromkeys(
                        issues.get(top.requirement_id, [])
                        + issues.get(child_id, [])
                        + issues.get(design_id, [])
                        + issues.get(verification_id, [])
                    ))
                    rows.append({
                        "top_requirement": top.model_dump(),
                        "decomposed_requirement": child.model_dump() if child else None,
                        "design_item": design_by_id[design_id].model_dump() if design_id in design_by_id else None,
                        "verification_claim": ver_by_id[verification_id].model_dump() if verification_id in ver_by_id else None,
                        "source_documents": _row_source_documents(
                            top,
                            child,
                            design_by_id.get(design_id),
                            ver_by_id.get(verification_id),
                        ),
                        "closure_status": _closure_status(child_id, design_id, verification_id, issue_ids),
                        "review_item_ids": issue_ids,
                    })
    return rows


def _row_source_documents(
    top_requirement: RequirementNode | None,
    decomposed_requirement: RequirementNode | None,
    design_item: DesignImplementationItem | None,
    verification_claim: VerificationClaim | None,
) -> dict[str, str]:
    return {
        "top_requirement": top_requirement.source_file_name if top_requirement else "",
        "decomposed_requirement": decomposed_requirement.source_file_name if decomposed_requirement else "",
        "design_item": design_item.source_file_name if design_item else "",
        "verification_claim": verification_claim.source_file_name if verification_claim else "",
    }


def _build_summary(
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
    links: list[RequirementTraceLink],
    review_items: list[CrossDocumentReviewItem],
    gate: dict[str, Any],
) -> dict[str, Any]:
    active_links = active_trace_links(links)
    completed_verification_ids = {
        claim.verification_id
        for claim in verification_claims
        if claim.status == "completed"
    }
    top_count = sum(1 for req in requirements if req.requirement_level == "top")
    decomposed = [req for req in requirements if req.requirement_level == "decomposed"]
    decomposed_ids = {req.requirement_id for req in decomposed}
    top_with_children = {link.source_id for link in active_links if link.link_type == "decomposes"}
    req_with_design = {link.source_id for link in active_links if link.link_type == "satisfies"}
    req_with_ver = {
        link.source_id
        for link in active_links
        if link.link_type == "verifies"
        and link.source_id in decomposed_ids
        and link.target_id in completed_verification_ids
    }
    design_ids = {item.design_item_id for item in design_items}
    design_with_ver = {
        link.source_id
        for link in active_links
        if link.link_type == "verifies"
        and link.source_id in design_ids
        and link.target_id in completed_verification_ids
    }
    closed_requirement_ids = decomposed_ids & req_with_design & req_with_ver

    def ratio(count: int, total: int) -> float:
        return round(count / total, 4) if total else 0.0

    return {
        "requirement_count": len(requirements),
        "top_requirement_count": top_count,
        "decomposed_requirement_count": len(decomposed),
        "design_item_count": len(design_items),
        "verification_claim_count": len(verification_claims),
        "trace_link_count": len(active_links),
        "review_item_count": len(review_items),
        "critical_review_item_count": sum(1 for item in review_items if item.severity == "critical"),
        "decomposition_coverage": ratio(len(top_with_children), top_count),
        "design_closure_coverage": ratio(len(req_with_design & decomposed_ids), len(decomposed)),
        "verification_coverage": ratio(len(req_with_ver), len(decomposed)),
        "decomposed_count": len(top_with_children),
        "design_closed_count": len(req_with_design & decomposed_ids),
        "verified_count": len(req_with_ver),
        "fully_closed_requirement_count": len(closed_requirement_ids),
        "closure_gap_count": max(len(decomposed) - len(closed_requirement_ids), 0),
        "design_verification_coverage": ratio(len(design_with_ver), len(design_items)),
        "gate_status": gate["gate_status"],
        "generated_at": datetime.now().isoformat(),
        "ruleset_version": "traceability-p0-2026-05-14",
    }


def _iter_candidate_lines(content: str) -> list[str]:
    lines = []
    for raw in (content or "").splitlines():
        line = raw.strip().strip("-* \t")
        if len(line) >= 8:
            lines.append(line)
    return lines


def _extract_metric(text: str, value_role: str = "requirement") -> dict[str, Any]:
    metric_id, metric_name = _metric_name(text)
    cleaned = re.sub(r"\b(?:REQ|DES|SIM|VER|TEST)-[A-Za-z0-9_-]+\b", "", text or "")
    cleaned = cleaned.replace("`", "")
    is_result_text = "结果" in cleaned
    search_text = _metric_search_text(cleaned, value_role)
    matches = list(_NUMBER_RE.finditer(search_text))
    match_iter = matches if value_role == "observed" or is_result_text else list(reversed(matches))
    match = next((item for item in match_iter if item.group("unit")), None)
    if match is None:
        match = matches[-1] if matches and metric_id else None
    if not match:
        return {"metric_id": metric_id, "metric_name": metric_name, "comparator": "", "value": None, "unit": ""}
    comparator = normalize_comparator(match.group("comparator") or "")
    if not comparator:
        prefix = search_text[max(0, match.start() - 16):match.start()]
        for token in ("不大于", "不超过", "小于", "<=", "≤", "不小于", "不少于", "大于", ">=", "≥"):
            if token in prefix:
                comparator = normalize_comparator(token)
                break
    unit = _normalize_unit(match.group("unit") or "")
    return {
        "metric_id": metric_id,
        "metric_name": metric_name,
        "comparator": comparator,
        "value": float(match.group("value")),
        "unit": unit,
    }


def _metric_search_text(text: str, value_role: str) -> str:
    if value_role == "observed":
        for marker in ("结果", "实测", "测得", "达到", "为"):
            if marker in text:
                return text.split(marker, 1)[1]
        return text
    for marker in ("要求", "应", "需", "不大于", "不小于", "不超过", "不少于", "<=", ">=", "≤", "≥"):
        if marker in text:
            index = text.find(marker)
            return text[index:]
    return text


def _metric_name(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if any(token in text for token in ("姿态确定精度", "定姿误差", "确定精度")):
        return "attitude_determination_accuracy", "姿态确定精度"
    if any(token in text for token in ("机动时间", "姿态机动时间")):
        return "attitude_maneuver_time", "姿态机动时间"
    if any(token in text for token in ("角速度", "angular rate")):
        return "attitude_angular_rate", "姿态角速度"
    if any(token in text for token in ("安全模式", "安全姿态", "故障")):
        return "safe_mode_fault_response", "故障安全模式"
    if "interface" in lowered or "接口" in text:
        return "interface_constraint", "接口约束"
    return "", ""


def _artifact_similarity(source: RequirementNode, target: RequirementNode | DesignImplementationItem) -> float:
    score = 0.0
    if source.metric_id and getattr(target, "metric_id", "") and source.metric_id == getattr(target, "metric_id", ""):
        score += 0.52
    source_tags = set(source.condition_tags or [])
    target_tags = set(condition_tags(getattr(target, "text", "") or getattr(target, "source_quote", "")))
    if source_tags and target_tags:
        overlap = len(source_tags & target_tags) / max(len(source_tags), 1)
        score += min(0.22, overlap * 0.22)
    source_tokens = _semantic_tokens(source.text or source.source_quote)
    target_tokens = _semantic_tokens(getattr(target, "text", "") or getattr(target, "source_quote", ""))
    if source_tokens and target_tokens:
        overlap = len(source_tokens & target_tokens) / max(min(len(source_tokens), len(target_tokens)), 1)
        score += min(0.36, overlap * 0.36)
    if source.target_value is not None:
        observed = getattr(target, "observed_value", None)
        target_value = getattr(target, "target_value", None)
        comparable_value = observed if observed is not None else target_value
        if comparable_value is not None and abs(float(source.target_value) - float(comparable_value)) < 1e-9:
            score += 0.12
    return round(min(score, 0.95), 4)


def _looks_like_unallocated_design(item: DesignImplementationItem) -> bool:
    """Return true for design statements that need explicit upstream basis.

    P0 allows deterministic candidate links when a design item and requirement
    are strongly aligned, but a design statement that explicitly says it is
    "新增" and does not cite a requirement should remain open for engineer
    confirmation instead of being silently closed by token overlap.
    """
    text = f"{item.title} {item.text} {item.source_quote}"
    if item.satisfies_requirement_ids:
        return False
    return any(token in text for token in ("新增", "增设", "额外", "补充设计", "自适应"))


def _semantic_tokens(text: str) -> set[str]:
    sample = text or ""
    token_aliases = {
        "attitude": ("姿态", "attitude"),
        "determination": ("确定", "定姿", "estimation", "determination"),
        "accuracy": ("精度", "误差", "accuracy", "error"),
        "maneuver": ("机动", "maneuver", "slew"),
        "time": ("时间", "时长", "time", "duration"),
        "safe_mode": ("安全模式", "安全姿态", "safe mode"),
        "fault": ("故障", "失效", "fault", "failure"),
        "interface": ("接口", "interface", "icd"),
        "pointing": ("指向", "pointing"),
        "control": ("控制", "控制律", "control"),
        "filter": ("滤波", "filter"),
        "actuator": ("执行机构", "飞轮", "推力器", "actuator", "wheel", "thruster"),
    }
    lowered = sample.lower()
    return {
        token
        for token, aliases in token_aliases.items()
        if any(alias.lower() in lowered for alias in aliases)
    }


def _normalize_unit(value: str) -> str:
    return normalize_unit(value) or ""


def _title_from_line(line: str, artifact_id: str) -> str:
    title = line.replace("`", "").replace(artifact_id, "").strip(" ：:-。")
    return title[:80] if title else artifact_id


def _infer_design_type(text: str) -> str:
    if "算法" in text or "滤波" in text or "控制律" in text:
        return "algorithm"
    if "接口" in text:
        return "interface"
    if "参数" in text:
        return "parameter"
    return "design"


def _closure_status(child_id: str, design_id: str, verification_id: str, issue_ids: list[str]) -> str:
    if issue_ids:
        return "open_issue"
    if child_id and design_id and verification_id:
        return "candidate_closed"
    return "incomplete"


def _material_summary(material: MaterialItem) -> dict[str, Any]:
    summary = build_material_summary(material, role_labels=P0_GATEKEEPING_ROLE_LABELS)
    summary.update({
        "role_reason": material.role_reason,
        "parser_name": material.parser_name,
        "content_length": len(material.content or ""),
    })
    return summary
