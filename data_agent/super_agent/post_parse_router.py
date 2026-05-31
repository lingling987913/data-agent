"""Post-parse review route resolution (L2.5): decide final review mode after parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data_agent.review_plus.schemas import ReviewPlusMaterialRole
from data_agent.super_agent import helpers
from data_agent.super_agent.objective_policy import objective_suppresses_gnc
from data_agent.super_agent.route_policy import tools_for_route
from data_agent.super_agent.schemas import SuperAgentRoute, SuperAgentRouteDecision, SuperAgentRun

_GNC_STRONG_TOKENS = ("gnc", "姿态", "轨控", "卫星", "飞轮", "星敏", "陀螺")
_GNC_WEAK_TOKENS = ("导航", "控制")
_DESIGN_DOC_TOKENS = ("报告", "方案", "设计", "分析", "report", "design report", "analysis report")

_REVIEW_SLOT_ROLES = {
    ReviewPlusMaterialRole.REVIEW_RULE.value,
    ReviewPlusMaterialRole.CHECKLIST.value,
    ReviewPlusMaterialRole.TASK_BOOK.value,
}
_SUBJECT_ROLES = {
    ReviewPlusMaterialRole.SUBJECT_REPORT.value,
    ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
    ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT.value,
}

_ROUTE_TO_STR = {
    SuperAgentRoute.REVIEW_PLUS: "review_plus",
    SuperAgentRoute.GNC_REVIEW_ONLY: "gnc_review_only",
    SuperAgentRoute.GNC_REVIEW: "gnc_review",
    SuperAgentRoute.SMART: "smart",
    SuperAgentRoute.STRUCTURE_ONLY: "structure_only",
    SuperAgentRoute.HYBRID: "hybrid",
    SuperAgentRoute.AUTO: "auto",
}


@dataclass
class PostParseRouteResult:
    suggested_route: SuperAgentRoute
    effective_route: SuperAgentRoute
    confidence: float
    reasons: list[str] = field(default_factory=list)
    changed_from_initial: bool = False
    initial_route: str = ""
    user_override_active: bool = False
    parse_incomplete: bool = False
    source: str = "post_parse"

    @property
    def route_str(self) -> str:
        return _ROUTE_TO_STR.get(self.suggested_route, self.suggested_route.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "suggested_route": self.route_str,
            "effective_route": _ROUTE_TO_STR.get(self.effective_route, self.effective_route.value),
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "changed_from_initial": self.changed_from_initial,
            "initial_route": self.initial_route,
            "user_override_active": self.user_override_active,
            "parse_incomplete": self.parse_incomplete,
        }


def _normalize_route_token(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"gnc_review", "gnc_review_only"}:
        return "gnc_review_only"
    if normalized == "parse_only":
        return "smart"
    return normalized


def _collect_corpus(
    run: SuperAgentRun,
    preview: dict[str, Any],
    classification: dict[str, Any],
) -> str:
    parts: list[str] = [run.objective or ""]
    parts.append(str(classification.get("doc_type") or ""))
    parts.append(str(classification.get("domain") or ""))
    parts.append(str(classification.get("reason") or ""))

    for item in classification.get("material_roles") or []:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get("file_name") or ""))
        parts.append(str(item.get("role") or ""))
        parts.append(str(item.get("content_preview") or "")[:500])

    for item in preview.get("materials") or []:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get("file_name") or ""))
        parts.append(str(item.get("role") or ""))
        parts.append(str(item.get("content_preview") or "")[:1500])
        parts.append(str(item.get("content_markdown") or "")[:1500])
        for block in (item.get("blocks") or [])[:40]:
            if isinstance(block, dict):
                parts.append(str(block.get("content") or "")[:300])
                parts.append(str(block.get("markdown") or "")[:300])

    structure_summary = preview.get("structure_summary") if isinstance(preview.get("structure_summary"), dict) else {}
    for section in structure_summary.get("top_sections") or []:
        if isinstance(section, dict):
            parts.append(str(section.get("title") or ""))

    document_ir = preview.get("document_ir") if isinstance(preview.get("document_ir"), dict) else {}
    if document_ir:
        parts.append(str(document_ir)[:2000])

    parse_artifact = preview.get("parse_artifact") if isinstance(preview.get("parse_artifact"), dict) else {}
    if parse_artifact:
        parts.append(str(parse_artifact.get("batch_summary") or "")[:1000])

    return " ".join(part for part in parts if part).lower()


def _material_roles_from_preview(
    preview: dict[str, Any],
    classification: dict[str, Any],
) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (preview.get("materials"), classification.get("material_roles")):
        for item in source or []:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("file_name") or item.get("filename") or item.get("name") or "")
            if file_name in seen:
                continue
            seen.add(file_name)
            roles.append(item)
    return roles


def _parse_quality(preview: dict[str, Any]) -> tuple[bool, str]:
    summary = preview.get("summary") if isinstance(preview.get("summary"), dict) else {}
    material_count = int(summary.get("material_count") or 0)
    parsed_ok = int(summary.get("parsed_ok") or 0)
    structure_summary = preview.get("structure_summary") if isinstance(preview.get("structure_summary"), dict) else {}
    structure_ready = structure_summary.get("structure_ready")

    if material_count > 0 and parsed_ok < material_count:
        return True, "部分材料解析未完成"
    if structure_ready is False:
        return True, "结构化产物尚未就绪"
    return False, ""


def _suggest_route(
    *,
    run: SuperAgentRun,
    preview: dict[str, Any],
    classification: dict[str, Any],
    corpus: str,
    material_roles: list[dict[str, Any]],
) -> tuple[SuperAgentRoute, float, list[str]]:
    slot_status = helpers.compute_review_plus_slot_status(material_roles)
    role_set = {
        str(item.get("role") or "").strip().lower()
        for item in material_roles
        if isinstance(item, dict)
    }
    has_review_slots = bool(role_set & _REVIEW_SLOT_ROLES)
    has_subject = bool(role_set & _SUBJECT_ROLES)

    parse_incomplete, parse_reason = _parse_quality(preview)
    if parse_incomplete:
        return (
            SuperAgentRoute.STRUCTURE_ONLY,
            0.5,
            [f"解析后路由：{parse_reason}，建议先完成结构解析后再进入审查。"],
        )

    if slot_status["review_plus_ready"] or (has_review_slots and has_subject):
        return (
            SuperAgentRoute.REVIEW_PLUS,
            0.92,
            ["解析后确认材料包槽位完整，推荐文件组审查。"],
        )

    gnc_strong = any(token in corpus for token in _GNC_STRONG_TOKENS)
    gnc_weak = any(token in corpus for token in _GNC_WEAK_TOKENS)
    suppressed_gnc_reason: str | None = None
    if objective_suppresses_gnc(run.objective):
        if gnc_strong or gnc_weak:
            suppressed_gnc_reason = (
                "用户自定义审查目标未表达 GNC 专项意图，正文虽含 GNC 相关词但不推荐 GNC 专项。"
            )
        gnc_strong = False
        gnc_weak = False
    wants_gnc = gnc_strong or (gnc_weak and not has_review_slots)
    if wants_gnc and not slot_status["review_plus_ready"]:
        return (
            SuperAgentRoute.GNC_REVIEW_ONLY,
            0.88,
            ["解析后正文出现 GNC/姿态/轨控等强信号，推荐 GNC 专项审查。"],
        )

    design_doc = any(token in corpus for token in _DESIGN_DOC_TOKENS)
    if design_doc or len(material_roles) <= 1:
        reasons = ["解析后确认为单份设计/报告类文档，推荐智能审查。"]
        if suppressed_gnc_reason:
            reasons.insert(0, suppressed_gnc_reason)
        return (
            SuperAgentRoute.SMART,
            0.85,
            reasons,
        )

    reasons = ["解析后材料类型较综合，推荐智能审查自动匹配场景。"]
    if suppressed_gnc_reason:
        reasons.insert(0, suppressed_gnc_reason)
    return (
        SuperAgentRoute.SMART,
        0.8,
        reasons,
    )


def resolve_post_parse_route(
    run: SuperAgentRun,
    preview: dict[str, Any],
) -> PostParseRouteResult:
    classification = dict(preview.get("classification") or run.classification or {})
    initial_route = _normalize_route_token(
        str(classification.get("initial_recommended_route") or classification.get("recommended_route") or "smart")
    )

    material_roles = _material_roles_from_preview(preview, classification)
    corpus = _collect_corpus(run, preview, classification)
    suggested_route, confidence, reasons = _suggest_route(
        run=run,
        preview=preview,
        classification=classification,
        corpus=corpus,
        material_roles=material_roles,
    )

    suggested_str = _ROUTE_TO_STR.get(suggested_route, suggested_route.value)
    changed_from_initial = suggested_str != initial_route and _normalize_route_token(initial_route) != suggested_str

    user_override_active = run.requested_route != SuperAgentRoute.AUTO
    effective_route = run.requested_route if user_override_active else suggested_route
    if user_override_active and effective_route != suggested_route:
        effective_label = _ROUTE_TO_STR.get(effective_route, effective_route.value)
        reasons = [
            *reasons,
            f"用户已指定审查模式 {effective_label}，与解析后建议 {suggested_str} 不一致，将按用户选择执行。",
        ]

    parse_incomplete, _ = _parse_quality(preview)
    return PostParseRouteResult(
        suggested_route=suggested_route,
        effective_route=effective_route,
        confidence=confidence,
        reasons=reasons,
        changed_from_initial=changed_from_initial,
        initial_route=initial_route,
        user_override_active=user_override_active,
        parse_incomplete=parse_incomplete,
    )


def _refresh_review_plan(run: SuperAgentRun, decision: SuperAgentRouteDecision) -> None:
    from data_agent.super_agent.execution_plan import compute_execution_plan_preview
    from data_agent.super_agent.schemas import CreateSuperAgentRunRequest

    classification = dict(run.classification) if isinstance(run.classification, dict) else {}
    if not helpers._has_saved_classification(classification):
        return
    request = CreateSuperAgentRunRequest(
        name=run.name,
        objective=run.objective,
        processing_mode=run.processing_mode,
        input_mode=run.input_mode,
        source_review_id=run.source_review_id,
        requested_route=run.requested_route,
        review_mode=run.review_mode,
        materials=list(run.materials),
        classification=classification,
        execute=False,
    )

    parse_plan, review_plan = compute_execution_plan_preview(
        run,
        classification,
        decision,
        request=request,
        processing_mode_override=run.processing_mode,
    )
    classification["parse_plan"] = parse_plan
    classification["review_plan"] = review_plan
    run.classification = classification


def apply_post_parse_route(run: SuperAgentRun, preview: dict[str, Any]) -> dict[str, Any]:
    """Resolve post-parse route, persist on run + preview classification."""
    preview = dict(preview)
    result = resolve_post_parse_route(run, preview)

    classification = dict(preview.get("classification") or run.classification or {})
    if not classification.get("initial_recommended_route"):
        classification["initial_recommended_route"] = classification.get("recommended_route") or result.initial_route

    classification["final_recommended_route"] = result.route_str
    classification["route_decision_source"] = result.source
    classification["post_parse_route"] = result.to_dict()
    classification["recommended_route"] = result.route_str
    if result.reasons:
        classification["post_parse_reason"] = result.reasons[0]

    preview["classification"] = classification
    run.classification = classification

    decision = SuperAgentRouteDecision(
        route=result.effective_route,
        confidence=result.confidence,
        reasons=result.reasons,
        required_tools=tools_for_route(result.effective_route),
        classification=classification,
    )
    run.route_decision = decision
    _refresh_review_plan(run, decision)
    preview["classification"] = dict(run.classification)
    return preview


def ensure_post_parse_route_decision(run: SuperAgentRun) -> bool:
    """Ensure run has a post-parse route decision when parse preview exists."""
    classification = run.classification if isinstance(run.classification, dict) else {}
    if (
        run.route_decision is not None
        and classification.get("route_decision_source") == "post_parse"
    ):
        return True

    preview = run.parse_preview if isinstance(run.parse_preview, dict) else None
    if not preview:
        return False

    updated = apply_post_parse_route(run, preview)
    run.parse_preview = updated
    return True
