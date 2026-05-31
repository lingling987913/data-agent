"""Route → parsing plan and skill execution mapping for Super Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    SuperAgentInputMode,
    SuperAgentReviewMode,
    SuperAgentRoute,
    SuperAgentRouteDecision,
    SuperAgentRun,
)


@dataclass(frozen=True)
class ParsingPlan:
    bootstrap_review_plus: bool = False
    run_structure_parse: bool = False
    reuse_review_plus_parse: bool = False


_REVIEW_PLUS_ROLES = frozenset({
    "review_rule",
    "checklist",
    "task_book",
    "subject_report",
    "subject_document",
    "supporting_attachment",
})


def materials_hint_review_plus(materials: list) -> bool:
    roles: set[str] = set()
    for item in materials:
        role = getattr(item, "role", None) or (item.get("role") if isinstance(item, dict) else "")
        if role:
            roles.add(str(role))
    return materials_hint_review_plus_from_roles(roles)


def _materials_hint_review_plus(materials: list) -> bool:
    return materials_hint_review_plus(materials)


def materials_hint_review_plus_from_roles(roles: set[str]) -> bool:
    has_rule = bool(roles & {"review_rule", "checklist"})
    has_task = "task_book" in roles
    has_subject = bool(roles & {"subject_report", "subject_document", "supporting_attachment"})
    return has_rule and has_task and has_subject


def material_roles_payload_hint_review_plus(material_roles: list) -> bool:
    roles: set[str] = set()
    for item in material_roles:
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip()
            if role:
                roles.add(role)
    return materials_hint_review_plus_from_roles(roles)


def _is_upload(run: SuperAgentRun, request: CreateSuperAgentRunRequest | None) -> bool:
    if run.input_mode == SuperAgentInputMode.UPLOAD:
        return True
    return request is not None and request.input_mode == SuperAgentInputMode.UPLOAD


def resolve_parsing_plan(
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision,
    *,
    request: CreateSuperAgentRunRequest | None = None,
) -> ParsingPlan:
    route = decision.route
    is_upload = _is_upload(run, request)
    has_review_plus = bool(run.source_review_id)
    material_list = list(request.materials if request else run.materials)
    has_materials = bool(material_list)

    smart_bootstrap = False
    if route == SuperAgentRoute.SMART:
        from data_agent.super_agent.phases.document_review.smart_orchestrator import (
            resolve_smart_review_plan,
        )

        smart_plan = resolve_smart_review_plan(run, decision)
        smart_bootstrap = smart_plan.bootstrap_review_plus

    needs_review_plus_slots = (
        route in {SuperAgentRoute.REVIEW_PLUS, SuperAgentRoute.HYBRID}
        or run.requested_route == SuperAgentRoute.REVIEW_PLUS
        or smart_bootstrap
        or _materials_hint_review_plus(material_list)
    )

    if run.input_mode == SuperAgentInputMode.EXISTING_REVIEW_PLUS and has_review_plus:
        return ParsingPlan(reuse_review_plus_parse=True)

    bootstrap = (
        is_upload
        and has_materials
        and not has_review_plus
        and (
            (run.review_mode == SuperAgentReviewMode.FULL and needs_review_plus_slots)
            or (route == SuperAgentRoute.SMART and smart_bootstrap)
        )
    )
    if bootstrap:
        return ParsingPlan(bootstrap_review_plus=True, reuse_review_plus_parse=True)

    needs_structure = route in {
        SuperAgentRoute.STRUCTURE_ONLY,
        SuperAgentRoute.SMART,
        SuperAgentRoute.GNC_REVIEW,
        SuperAgentRoute.GNC_REVIEW_ONLY,
        SuperAgentRoute.HYBRID,
    } or run.review_mode in {SuperAgentReviewMode.SINGLE_DOC, SuperAgentReviewMode.MULTI_DOC}

    if needs_structure and (is_upload or has_materials):
        return ParsingPlan(run_structure_parse=True)

    return ParsingPlan()


def skills_for_execution(
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision,
    *,
    plan: ParsingPlan | None = None,
) -> list[str]:
    from data_agent.super_agent.execution_graph import skills_for_execution as _graph_skills

    return _graph_skills(run, decision, plan=plan)


_CLASSIFICATION_ROUTE_MAP = {
    "review_plus": SuperAgentRoute.REVIEW_PLUS,
    "gnc_review": SuperAgentRoute.GNC_REVIEW_ONLY,
    "hybrid": SuperAgentRoute.HYBRID,
    "smart": SuperAgentRoute.SMART,
    "parse_only": SuperAgentRoute.SMART,
    "structure_only": SuperAgentRoute.STRUCTURE_ONLY,
}


def review_mode_selection_from_run(run: SuperAgentRun) -> str:
    classification = run.classification if isinstance(run.classification, dict) else {}
    stored = str(classification.get("review_mode_selection") or "").strip().lower()
    if stored in {"smart", "standard", "specialized"}:
        return stored
    if run.requested_route == SuperAgentRoute.REVIEW_PLUS:
        return "standard"
    if run.requested_route in {SuperAgentRoute.GNC_REVIEW_ONLY, SuperAgentRoute.GNC_REVIEW}:
        return "specialized"
    return "smart"


def requested_route_from_review_mode_selection(
    selection: str,
    *,
    classification: dict[str, Any] | None = None,
) -> SuperAgentRoute:
    normalized = str(selection or "smart").strip().lower()
    if normalized == "standard":
        return SuperAgentRoute.REVIEW_PLUS
    if normalized == "specialized":
        return SuperAgentRoute.GNC_REVIEW_ONLY
    recommended = str((classification or {}).get("recommended_route") or "smart").strip().lower()
    return _CLASSIFICATION_ROUTE_MAP.get(recommended, SuperAgentRoute.SMART)


def _default_processing_mode_from_classification(
    classification: dict[str, Any],
    *,
    fallback: str = "OPTIMAL",
) -> str:
    modes: list[str] = []
    for item in classification.get("material_roles") or []:
        if not isinstance(item, dict):
            continue
        mode = str(item.get("recommended_processing_mode") or "").strip()
        if mode:
            modes.append(mode)
    if not modes:
        return fallback or "OPTIMAL"
    if "OPTIMAL" in modes:
        return "OPTIMAL"
    return modes[0]


def build_parse_plan(
    run: SuperAgentRun,
    classification: dict[str, Any],
    *,
    processing_mode_override: str | None = None,
) -> dict[str, Any]:
    from data_agent.services.task_classifier import resolve_parsing_tier

    default_mode = (
        processing_mode_override
        or run.processing_mode
        or _default_processing_mode_from_classification(classification)
    )
    parser_default = "auto"
    if default_mode and default_mode.upper() != "OPTIMAL":
        from data_agent.agents.format_guard.mode_policy import resolve_parser_type

        first_name = ""
        for material in run.materials:
            first_name = str(material.name or "").strip()
            if first_name:
                break
        if not first_name:
            for item in classification.get("material_roles") or []:
                if isinstance(item, dict):
                    first_name = str(item.get("file_name") or "").strip()
                    if first_name:
                        break
        parser_default = resolve_parser_type(first_name or "material.txt", default_mode)

    files: list[dict[str, Any]] = []
    for item in classification.get("material_roles") or []:
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file_name") or item.get("filename") or item.get("name") or "")
        role = str(item.get("role") or "")
        tier = resolve_parsing_tier(role, file_name, default_parser_type=parser_default)
        tier_name = str(item.get("recommended_parsing_tier") or tier.get("tier") or "standard").lower()
        processing_mode = str(
            item.get("recommended_processing_mode") or tier.get("processing_mode") or default_mode
        )
        if tier_name == "lite":
            processing_mode = "HIGH_SPEED"
        files.append(
            {
                "file_name": file_name,
                "role": role,
                "parsing_tier": tier_name,
                "parser_type": str(item.get("recommended_parser_type") or tier.get("parser_type") or parser_default),
                "processing_mode": processing_mode,
            }
        )

    return {
        "default_processing_mode": default_mode,
        "default_parser_type": parser_default,
        "files": files,
        "source": "classify_and_route",
    }


def build_review_plan(
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision,
    parsing_plan: ParsingPlan,
    *,
    classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from data_agent.super_agent import helpers
    from data_agent.super_agent.phases.document_review.smart_orchestrator import (
        resolve_smart_review_plan,
        smart_plan_to_dict,
    )

    payload = classification if isinstance(classification, dict) else {}
    if not payload and isinstance(run.classification, dict):
        payload = run.classification
    slot_status = helpers.compute_review_plus_slot_status(payload.get("material_roles") or [])
    selection = review_mode_selection_from_run(run)

    smart_plan_payload: dict[str, Any] = {}
    smart_degradation: list[str] = []
    execution_skills: list[str] = []
    task_board_preview: dict[str, Any] = {}
    if decision.route == SuperAgentRoute.SMART:
        smart_plan = resolve_smart_review_plan(run, decision)
        smart_plan_payload = smart_plan_to_dict(smart_plan)
        smart_degradation = list(smart_plan.degradation_summary)
        execution_skills = skills_for_execution(run, decision, plan=parsing_plan)
        if smart_plan.primary_path == "smart_committee":
            from data_agent.core.task_board import (
                build_smart_committee_task_board,
                build_task_board_from_specs,
            )

            chief_plan = smart_plan.chief_review_plan or {}
            if smart_plan.task_specs:
                preview_board = build_task_board_from_specs(list(smart_plan.task_specs))
            else:
                preview_board = build_smart_committee_task_board(
                    chief_plan,
                    specialist_ids=list(smart_plan.specialist_ids),
                )
            preview_summary = preview_board.summary()
            task_spec_ids = [spec.task_id for spec in smart_plan.task_specs] if smart_plan.task_specs else []
            task_board_preview = {
                "execution_model": "task_board_subagents",
                "task_count": preview_summary.get("task_count", 0),
                "task_spec_count": len(smart_plan.task_specs),
                "task_spec_ids": task_spec_ids,
                "specialist_ids": list(preview_summary.get("specialist_ids") or []),
                "status_counts": dict(preview_summary.get("status_counts") or {}),
            }
            domain_id = ""
            route_signal_hits: list[str] = []
            if smart_plan.task_specs:
                first_input = smart_plan.task_specs[0].input_summary or {}
                domain_id = str(first_input.get("domain_id") or "")
                route_signal_hits = list(first_input.get("route_signal_hits") or [])
            if domain_id:
                task_board_preview["domain_id"] = domain_id
            if route_signal_hits:
                task_board_preview["route_signal_hits"] = route_signal_hits

    adaptive_router_summary: dict[str, Any] = {}
    adaptive_raw = payload.get("adaptive_router")
    if isinstance(adaptive_raw, dict):
        adaptive_router_summary = {
            "source": adaptive_raw.get("source"),
            "domain_id": adaptive_raw.get("domain_id"),
            "route": adaptive_raw.get("route"),
            "primary_path": adaptive_raw.get("primary_path"),
            "confidence": adaptive_raw.get("confidence"),
            "guardrail_corrections": list(adaptive_raw.get("guardrail_corrections") or []),
            "risk_flags": list(adaptive_raw.get("risk_flags") or []),
        }

    downgrade_reasons: list[str] = []
    recommended = str(payload.get("recommended_route") or "").strip().lower()
    if decision.route == SuperAgentRoute.SMART and recommended == "review_plus":
        downgrade_reasons.append("材料槽位不完整，已从文件组审查降级为智能审查")
    for reason in decision.reasons:
        if "降级" in reason and reason not in downgrade_reasons:
            downgrade_reasons.append(reason)

    return {
        "route": decision.route.value,
        "recommended_route": recommended,
        "review_mode_selection": selection,
        "required_tools": list(decision.required_tools),
        "skipped_tools": list(decision.skipped_tools),
        "bootstrap_review_plus": parsing_plan.bootstrap_review_plus,
        "run_structure_parse": parsing_plan.run_structure_parse,
        "reuse_review_plus_parse": parsing_plan.reuse_review_plus_parse,
        "confidence": decision.confidence,
        "reasons": list(decision.reasons),
        "downgrade_reasons": downgrade_reasons,
        "slot_status": slot_status,
        "review_plus_ready": bool(slot_status.get("review_plus_ready")),
        "gnc_review_id": decision.gnc_review_id or "",
        "smart_primary_path": smart_plan_payload.get("primary_path", ""),
        "smart_specialist_ids": list(smart_plan_payload.get("specialist_ids") or []),
        "smart_dispatch_reasons": list(smart_plan_payload.get("reasons") or []),
        "smart_review_plan": smart_plan_payload,
        "degradation_summary": smart_degradation,
        "execution_skills": execution_skills,
        "task_board_preview": task_board_preview,
        "smart_task_board_summary": task_board_preview,
        "adaptive_router": adaptive_router_summary,
    }


def compute_execution_plan_preview(
    run: SuperAgentRun,
    classification: dict[str, Any],
    decision: SuperAgentRouteDecision,
    *,
    request: CreateSuperAgentRunRequest | None = None,
    processing_mode_override: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    parsing_plan = resolve_parsing_plan(run, decision, request=request)
    parse_plan = build_parse_plan(
        run,
        classification,
        processing_mode_override=processing_mode_override,
    )
    review_plan = build_review_plan(run, decision, parsing_plan, classification=classification)
    return parse_plan, review_plan
