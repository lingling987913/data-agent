"""Chief orchestration and specialist review planning for Review-Plus.

This module turns Review-Plus from a single generic reviewer into a dynamic
review committee. It intentionally keeps deterministic planning as the primary
path so the workflow remains runnable without model access; LLM specialist
review can be layered on top of these auditable assignments.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from data_agent.review_plus.schemas import ReviewPlusMaterialRole
from data_agent.review_plus.text_utils import (
    all_review_text,
    dict_items,
    material_snapshot,
    role_value,
)


SPECIALIST_CATALOG: dict[str, dict[str, Any]] = {
    "document_format_reviewer": {
        "name": "文档格式与结构审查 Agent",
        "role": "审查送审材料格式、目录、章节、表格、版本和解析质量",
        "triggers": ["all"],
    },
    "requirements_traceability_reviewer": {
        "name": "需求追溯审查 Agent",
        "role": "审查任务书、需求、方案和验证材料之间的闭合关系",
        "triggers": ["任务书", "需求", "方案", "报告", "REQ", "DES", "SIM"],
    },
    "product_assurance_reviewer": {
        "name": "产品保证审查 Agent",
        "role": "审查检查单、产品保证要求、可靠性安全性过程符合性",
        "triggers": ["产品保证", "检查单", "可靠性", "安全性", "质量"],
    },
    "reliability_safety_reviewer": {
        "name": "可靠性安全性审查 Agent",
        "role": "审查可靠性、安全性、故障模式、单点失效和风险闭环",
        "triggers": ["可靠性", "安全性", "故障", "失效", "FMEA", "风险", "飞轮"],
    },
    "gnc_design_reviewer": {
        "name": "GNC 设计审查 Agent",
        "role": "审查制导导航控制方案、姿态/轨道控制闭环和系统级一致性",
        "triggers": ["GNC", "姿态", "轨道", "导航", "控制", "飞轮", "星敏", "陀螺"],
    },
    "attitude_control_reviewer": {
        "name": "姿态控制专业审查 Agent",
        "role": "审查控制律、执行机构、卸载、机动和姿态稳定性说明",
        "triggers": ["姿态控制", "控制律", "执行机构", "飞轮", "力矩", "卸载", "机动"],
    },
    "attitude_determination_reviewer": {
        "name": "姿态确定专业审查 Agent",
        "role": "审查姿态确定算法、传感器融合、星敏/陀螺配置和精度闭合",
        "triggers": ["姿态确定", "星敏", "陀螺", "滤波", "定姿", "测量"],
    },
    "verification_reviewer": {
        "name": "验证审查 Agent",
        "role": "审查验证矩阵、仿真/试验工况覆盖和结果支撑性",
        "triggers": ["验证", "仿真", "试验", "测试", "工况", "覆盖", "SIM", "TEST"],
    },
    "interface_reviewer": {
        "name": "接口一致性审查 Agent",
        "role": "审查接口、约束、输入输出、供电/通信/机械边界一致性",
        "triggers": ["接口", "ICD", "输入", "输出", "供电", "通信", "边界", "约束"],
    },
}


def _material_text(material: Any, max_chars: int = 6000) -> str:
    return material_snapshot(material, max_chars=max_chars)


def _all_review_text(task: Any, max_chars_per_material: int = 5000) -> str:
    return all_review_text(task, max_chars_per_material=max_chars_per_material)


def _sections_for_material(task: Any, material_name: str) -> list[dict[str, Any]]:
    sections = dict_items(getattr(task, "section_tree", {}), "sections")
    return [
        section for section in sections
        if str(section.get("source_file_name") or "") == material_name
    ]


def _evidences_for_material(task: Any, material_name: str) -> list[dict[str, Any]]:
    evidences = dict_items(getattr(task, "evidence_pool", {}), "evidences")
    return [
        evidence for evidence in evidences
        if str(evidence.get("source_file_name") or "") == material_name
    ]


def build_document_format_review(task: Any) -> dict[str, Any]:
    """Review document format/structure quality before technical review."""
    material_results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    total_sections = 0
    total_evidences = 0

    def add_finding(material_name: str, severity: str, title: str, description: str) -> None:
        findings.append({
            "finding_id": f"doc-format-{len(findings) + 1}",
            "material_name": material_name,
            "severity": severity,
            "title": title,
            "description": description,
            "recommendation": "补充可解析正文、目录/章节、版本基线或材料角色确认后重新审查。",
            "agent_id": "document_format_reviewer",
        })

    for material in getattr(task, "materials", []) or []:
        role = role_value(material)
        sections = _sections_for_material(task, getattr(material, "name", ""))
        evidences = _evidences_for_material(task, getattr(material, "name", ""))
        total_sections += len(sections)
        total_evidences += len(evidences)
        content = str(getattr(material, "content", "") or "")
        warnings = list(getattr(material, "warnings", []) or [])
        parse_status = str(getattr(material, "parse_status", "") or "")
        has_version = bool(getattr(material, "document_version", "") or re.search(r"\bV\d+(?:\.\d+)*\b|版本", content))
        has_baseline = bool(getattr(material, "baseline_id", "") or re.search(r"\bBL-[A-Za-z0-9_-]+\b|基线", content))
        has_toc_signal = bool(re.search(r"目录|第[一二三四五六七八九十]+章|\n\s*\d+(?:\.\d+)*\s+[\u4e00-\u9fffA-Za-z]", content))

        if parse_status == "failed" or not content.strip():
            add_finding(getattr(material, "name", ""), "critical", "材料解析失败或无正文", "该材料没有可用于审查的正文内容。")
        if role == ReviewPlusMaterialRole.UNKNOWN.value:
            add_finding(getattr(material, "name", ""), "major", "材料角色未确认", "该材料尚未明确在送审包中的业务角色。")
        if role not in {ReviewPlusMaterialRole.REVIEW_RULE.value, ReviewPlusMaterialRole.CHECKLIST.value}:
            if not sections and content.strip():
                add_finding(getattr(material, "name", ""), "major", "结构化章节缺失", "待审材料未形成可定位的章节结构。")
            if not evidences and content.strip():
                add_finding(getattr(material, "name", ""), "minor", "结构化证据池缺失", "待审材料未形成证据池，后续审查只能使用较粗粒度上下文。")
        if not has_version:
            add_finding(getattr(material, "name", ""), "minor", "版本标识缺失", "材料未识别到明确版本号。")
        if role in {
            ReviewPlusMaterialRole.TASK_BOOK.value,
            ReviewPlusMaterialRole.SUBJECT_REPORT.value,
            ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
        } and not has_baseline:
            add_finding(getattr(material, "name", ""), "minor", "基线标识缺失", "正式审查材料未识别到明确基线标识。")

        material_results.append({
            "material_name": getattr(material, "name", ""),
            "role": role,
            "parse_status": parse_status,
            "parser_name": getattr(material, "parser_name", ""),
            "section_count": len(sections),
            "evidence_count": len(evidences),
            "has_toc_signal": has_toc_signal,
            "has_version": has_version,
            "has_baseline": has_baseline,
            "warnings": warnings,
        })

    severity_counts = Counter(finding["severity"] for finding in findings)
    gate_status = "blocked" if severity_counts["critical"] else "limited" if findings else "passed"
    return {
        "agent_id": "document_format_reviewer",
        "agent_name": SPECIALIST_CATALOG["document_format_reviewer"]["name"],
        "gate_status": gate_status,
        "material_results": material_results,
        "findings": findings,
        "summary": {
            "material_count": len(material_results),
            "section_count": total_sections,
            "evidence_count": total_evidences,
            "finding_count": len(findings),
            "severity_counts": dict(severity_counts),
        },
    }


def _keyword_hits(text: str, triggers: list[str]) -> list[str]:
    lowered = text.lower()
    hits = []
    for trigger in triggers:
        if trigger == "all":
            continue
        if trigger.lower() in lowered:
            hits.append(trigger)
    return hits


def _format_reviewer_agent_id(catalog: dict[str, dict[str, Any]]) -> str | None:
    for candidate in ("document_format_reviewer", "document_consistency_reviewer"):
        if candidate in catalog:
            return candidate
    for agent_id, profile in catalog.items():
        if "all" in (profile.get("triggers") or []):
            return agent_id
    return None


def _required_specialist_ids(catalog: dict[str, dict[str, Any]], domain_id: str) -> list[str]:
    try:
        from data_agent.core.domain_registry import committee_defaults_for_domain

        configured = committee_defaults_for_domain(domain_id).get("required_specialists")
        if isinstance(configured, list) and configured:
            return [str(item) for item in configured if str(item) in catalog]
    except KeyError:
        pass
    legacy: list[str] = []
    for agent_id in (
        "document_format_reviewer",
        "requirements_traceability_reviewer",
        "requirement_alignment_reviewer",
    ):
        if agent_id in catalog:
            legacy.append(agent_id)
    return legacy


def _focus_questions_for_domain(domain_id: str) -> list[str]:
    try:
        from data_agent.core.domain_registry import committee_defaults_for_domain

        configured = committee_defaults_for_domain(domain_id).get("focus_questions")
        if isinstance(configured, list) and configured:
            return [str(item) for item in configured if str(item).strip()]
    except KeyError:
        pass
    return [
        "检查项是否均能在任务书、方案、报告或附件中找到可审计证据。",
        "任务书要求是否被方案设计和报告结论明确印证。",
        "指标数值、单位、版本和基线在多份文档之间是否一致。",
    ]


def _select_from_route_signals(
    text: str,
    catalog: dict[str, dict[str, Any]],
    domain_id: str,
    select: Any,
    *,
    skip_ids: set[str],
) -> None:
    try:
        from data_agent.core.domain_registry import route_signals_for_domain

        route_signals = route_signals_for_domain(domain_id)
    except KeyError:
        return

    matched_tokens: list[str] = []
    for tokens in route_signals.values():
        for token in tokens:
            if token.lower() in text.lower() and token not in matched_tokens:
                matched_tokens.append(token)
    if not matched_tokens:
        return

    for agent_id, profile in catalog.items():
        if agent_id in skip_ids:
            continue
        triggers = profile.get("triggers") or []
        if "all" in triggers:
            continue
        overlap = [
            token
            for token in matched_tokens
            if any(
                token.lower() in str(trigger).lower() or str(trigger).lower() in token.lower()
                for trigger in triggers
            )
        ]
        if overlap:
            select(
                agent_id,
                f"路由信号辅助命中专业审查: {', '.join(overlap[:6])}。",
                matched_signals=overlap,
            )
            skip_ids.add(agent_id)


def plan_review_committee_from_context(
    *,
    material_roles: list[Any] | None = None,
    corpus_text: str = "",
    objective: str = "",
    materials: list[Any] | None = None,
    document_format_review: dict[str, Any] | None = None,
    domain_id: str = "aerospace_review",
    specialist_catalog: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Domain-agnostic wrapper for chief committee planning (SMART + Review-Plus)."""
    from types import SimpleNamespace

    roles_from_payload: set[str] = set()
    for item in material_roles or []:
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip()
        else:
            role = str(item or "").strip()
        if role:
            roles_from_payload.add(role)

    mat_list: list[Any] = []
    for material in materials or []:
        if isinstance(material, dict):
            mat_list.append(
                SimpleNamespace(
                    name=str(material.get("name") or material.get("file_name") or ""),
                    content=str(material.get("content") or ""),
                    role=str(material.get("role") or "unknown"),
                    role_reason=str(material.get("role_reason") or ""),
                    included_in_formal_review=material.get("included_in_formal_review", True),
                    warnings=list(material.get("warnings") or []),
                    parse_status=str(material.get("parse_status") or "ok"),
                    document_version=str(material.get("document_version") or ""),
                    baseline_id=str(material.get("baseline_id") or ""),
                )
            )
        else:
            mat_list.append(material)

    text = str(corpus_text or "").strip()
    if not text:
        text = "\n".join(_material_text(material) for material in mat_list).strip()
    if text and mat_list and not any(str(getattr(m, "content", "") or "").strip() for m in mat_list):
        mat_list[0].content = text[:20000]
    elif text and not mat_list:
        mat_list.append(
            SimpleNamespace(
                name="corpus",
                content=text[:20000],
                role="subject_document",
                role_reason="",
                included_in_formal_review=True,
                warnings=[],
                parse_status="ok",
                document_version="",
                baseline_id="",
            )
        )

    task = SimpleNamespace(
        materials=mat_list,
        scenario=str(objective or ""),
        section_tree={},
        evidence_pool={},
        check_items=[],
        traceability_result={},
        cross_document_review_items=[],
        document_format_review=document_format_review or {},
    )
    catalog = specialist_catalog
    if catalog is None:
        try:
            from data_agent.core.domain_registry import specialist_catalog_for_domain

            catalog = specialist_catalog_for_domain(domain_id)
        except KeyError:
            catalog = SPECIALIST_CATALOG

    plan = plan_review_committee(
        task,
        document_format_review=document_format_review,
        specialist_catalog=catalog,
        domain_id=domain_id,
    )
    if roles_from_payload:
        summary = dict(plan.get("summary") or {})
        summary["material_roles"] = sorted(roles_from_payload)
        plan["summary"] = summary
    return plan


def plan_review_committee(
    task: Any,
    document_format_review: dict[str, Any] | None = None,
    *,
    specialist_catalog: dict[str, dict[str, Any]] | None = None,
    domain_id: str = "aerospace_review",
) -> dict[str, Any]:
    """Chief reviewer decides which specialist agents join this review."""
    catalog = specialist_catalog or SPECIALIST_CATALOG
    text = _all_review_text(task)
    material_roles = {
        role_value(material)
        for material in getattr(task, "materials", []) or []
    }
    selected: list[dict[str, Any]] = []

    def select(agent_id: str, reason: str, matched_signals: list[str] | None = None, required: bool = False) -> None:
        if any(item["agent_id"] == agent_id for item in selected):
            return
        profile = catalog.get(agent_id) or SPECIALIST_CATALOG.get(agent_id) or {}
        selected.append({
            "agent_id": agent_id,
            "agent_name": profile.get("name", agent_id),
            "role": profile.get("role", ""),
            "required": required,
            "reason": reason,
            "matched_signals": matched_signals or [],
        })

    format_id = _format_reviewer_agent_id(catalog)
    if format_id:
        select(
            format_id,
            "任何正式审查都必须先确认文档结构、解析质量和版本基线。",
            required=True,
        )

    for required_id in _required_specialist_ids(catalog, domain_id):
        if required_id == format_id:
            continue
        profile = catalog.get(required_id) or {}
        select(
            required_id,
            f"领域默认必选：{profile.get('role') or required_id}。",
            required=True,
        )

    if {
        ReviewPlusMaterialRole.REVIEW_RULE.value,
        ReviewPlusMaterialRole.CHECKLIST.value,
    } & material_roles and "product_assurance_reviewer" in catalog:
        select("product_assurance_reviewer", "材料包包含检查需求/检查单，需要产品保证视角审查规则符合性。", required=True)

    skip_ids = {item["agent_id"] for item in selected}
    for agent_id, profile in catalog.items():
        if agent_id in skip_ids:
            continue
        hits = _keyword_hits(text, profile.get("triggers") or [])
        if hits:
            select(agent_id, f"总师根据材料内容识别到专业信号: {', '.join(hits[:6])}。", matched_signals=hits)
            skip_ids.add(agent_id)

    _select_from_route_signals(text, catalog, domain_id, select, skip_ids=skip_ids)

    if (
        ReviewPlusMaterialRole.TASK_BOOK.value in material_roles
        and (
            ReviewPlusMaterialRole.SUBJECT_REPORT.value in material_roles
            or ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value in material_roles
        )
        and "verification_reviewer" in catalog
    ):
        select("verification_reviewer", "材料包包含任务书和被审报告/方案，需要验证覆盖与结果支撑性审查。")

    focus_questions = list(_focus_questions_for_domain(domain_id))
    if document_format_review and document_format_review.get("findings"):
        focus_questions.append("文档格式/结构问题是否影响后续技术审查结论可靠性。")

    return {
        "chief_agent_id": "review_plus_chief_coordinator",
        "chief_agent_name": "Review-Plus 总师调度 Agent",
        "scenario": getattr(task, "scenario", ""),
        "domain_id": domain_id,
        "selected_agents": selected,
        "focus_questions": focus_questions,
        "coordination_policy": {
            "document_format_first": True,
            "keyword_is_auxiliary": True,
            "llm_must_cite_source_quotes": True,
            "specialists_required_for_domain_claims": True,
        },
        "summary": {
            "agent_count": len(selected),
            "required_agent_count": sum(1 for item in selected if item.get("required")),
            "material_roles": sorted(role for role in material_roles if role),
            "domain_id": domain_id,
        },
    }


def ensure_document_format_review(task: Any) -> dict[str, Any]:
    """Build or reuse document format review findings for format gate specialists."""
    existing = getattr(task, "document_format_review", None)
    if isinstance(existing, dict) and existing.get("findings"):
        return existing
    review = build_document_format_review(task)
    setattr(task, "document_format_review", review)
    return review


def _traceability_review_items(task: Any) -> list[dict[str, Any]]:
    traceability = getattr(task, "traceability_result", None) or {}
    if not isinstance(traceability, dict):
        return []
    return [item for item in (traceability.get("review_items") or []) if isinstance(item, dict)]


def _cross_document_items(task: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in (getattr(task, "cross_document_review_items", None) or [])
        if isinstance(item, dict)
    ]


def _dedupe_review_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("review_item_id") or item.get("item_id") or item.get("finding_id") or ""),
            str(item.get("item_type") or ""),
            str(item.get("title") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _item_matches_traceability_specialist(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "").lower()
    if item_type.startswith(("missing_", "check_item_coverage", "baseline_version", "evidence_reference")):
        return True
    return any(token in item_type for token in ("trace", "reference", "consistency", "cross_document"))


def _item_matches_verification_specialist(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "").lower()
    title = str(item.get("title") or "")
    description = str(item.get("description") or "")
    haystack = f"{item_type} {title} {description}".lower()
    if "verification" in item_type:
        return True
    return any(keyword in haystack for keyword in ("验证", "工况", "试验", "测试", "仿真", "覆盖"))


def _collect_specialist_findings(task: Any, agent_id: str, agent: dict[str, Any]) -> list[dict[str, Any]]:
    check_items = getattr(task, "check_items", []) or []
    trace_items = _traceability_review_items(task)
    cross_items = _cross_document_items(task)
    combined_items = _dedupe_review_items([*trace_items, *cross_items])

    if agent_id in {"document_format_reviewer", "document_consistency_reviewer"}:
        return list(ensure_document_format_review(task).get("findings") or [])
    if agent_id in {"requirements_traceability_reviewer", "requirement_alignment_reviewer"}:
        return [item for item in combined_items if _item_matches_traceability_specialist(item)]
    if agent_id == "verification_reviewer":
        return [item for item in combined_items if _item_matches_verification_specialist(item)]
    if agent_id in {"product_assurance_reviewer", "reliability_safety_reviewer"}:
        return [
            {
                "review_item_id": f"{agent_id}-check-item-coverage",
                "item_type": "check_item_coverage",
                "severity": "major" if not check_items else "info",
                "title": "检查项覆盖情况",
                "description": f"本轮共识别 {len(check_items)} 条检查项，应由该专业结合证据逐项复核。",
                "recommendation": "检查项结论必须引用任务书、方案、报告或附件原文。",
            }
        ]
    hits = agent.get("matched_signals") or []
    return [
        {
            "review_item_id": f"{agent_id}-domain-assignment",
            "item_type": "specialist_assignment",
            "severity": "info",
            "title": "专业审查任务已分派",
            "description": f"总师基于 {', '.join(hits[:6]) or '材料角色'} 将该专业纳入本轮审查。",
            "recommendation": "后续应由该专业 Agent 基于结构化证据形成领域审查发现。",
        }
    ]


def run_specialist_reviews(task: Any, chief_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Run deterministic specialist pre-review summaries.

    This does not replace each specialist's LLM review; it creates explicit
    assignments and initial findings so the later LLM review is scoped by the
    chief's committee plan instead of a single generic reviewer.
    """
    selected = chief_plan.get("selected_agents") or []
    reviews: list[dict[str, Any]] = []

    for agent in selected:
        agent_id = agent.get("agent_id", "")
        findings = _collect_specialist_findings(task, agent_id, agent)

        reviews.append({
            "agent_id": agent_id,
            "agent_name": agent.get("agent_name", ""),
            "role": agent.get("role", ""),
            "status": "completed",
            "assignment_reason": agent.get("reason", ""),
            "finding_count": len(findings),
            "findings": findings,
        })

    return reviews


def refresh_specialist_reviews(task: Any) -> list[dict[str, Any]]:
    """Rebuild specialist review summaries from the latest task artifacts."""
    chief_plan = getattr(task, "chief_review_plan", None) or {}
    selected = chief_plan.get("selected_agents") or []
    if not selected:
        return list(getattr(task, "specialist_reviews", []) or [])
    refreshed = run_specialist_reviews(task, chief_plan)
    setattr(task, "specialist_reviews", refreshed)
    return refreshed


def orchestrate_review_plus_specialists(task: Any) -> dict[str, Any]:
    document_format_review = build_document_format_review(task)
    chief_plan = plan_review_committee(task, document_format_review=document_format_review)
    specialist_reviews = run_specialist_reviews(task, chief_plan)
    return {
        "document_format_review": document_format_review,
        "chief_review_plan": chief_plan,
        "specialist_reviews": specialist_reviews,
    }


__all__ = [
    "SPECIALIST_CATALOG",
    "build_document_format_review",
    "ensure_document_format_review",
    "refresh_specialist_reviews",
    "orchestrate_review_plus_specialists",
    "plan_review_committee",
    "plan_review_committee_from_context",
    "run_specialist_reviews",
]
