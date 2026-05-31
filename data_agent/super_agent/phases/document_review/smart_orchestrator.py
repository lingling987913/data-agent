"""Smart review dispatch: route SMART runs to GNC / Review-Plus / committee paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data_agent.super_agent import helpers
from data_agent.super_agent.execution_plan import materials_hint_review_plus_from_roles
from data_agent.super_agent.objective_policy import (
    has_custom_objective,
    objective_implies_gnc,
    objective_suppresses_gnc,
)
from data_agent.core.domain_registry import resolve_domain_id, route_signals_for_domain
from data_agent.core.task_spec import TaskSpec, task_specs_from_dicts, task_specs_to_dicts
from data_agent.super_agent.schemas import (
    SuperAgentReviewMode,
    SuperAgentRoute,
    SuperAgentRouteDecision,
    SuperAgentRun,
)


@dataclass(frozen=True)
class SmartReviewPlan:
    primary_path: str  # gnc | review_plus | smart_committee | structure_only
    specialist_ids: list[str] = field(default_factory=list)
    bootstrap_review_plus: bool = False
    reasons: list[str] = field(default_factory=list)
    chief_review_plan: dict[str, Any] | None = None
    degradation_summary: list[str] = field(default_factory=list)
    task_specs: tuple[TaskSpec, ...] = field(default_factory=tuple)


def smart_plan_to_dict(plan: SmartReviewPlan) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "primary_path": plan.primary_path,
        "specialist_ids": list(plan.specialist_ids),
        "bootstrap_review_plus": plan.bootstrap_review_plus,
        "reasons": list(plan.reasons),
        "degradation_summary": list(plan.degradation_summary),
    }
    if plan.chief_review_plan:
        payload["chief_review_plan"] = dict(plan.chief_review_plan)
    if plan.task_specs:
        payload["task_specs"] = task_specs_to_dicts(list(plan.task_specs))
    return payload


def smart_plan_from_dict(payload: dict[str, Any] | None) -> SmartReviewPlan | None:
    if not isinstance(payload, dict) or not payload.get("primary_path"):
        return None
    chief = payload.get("chief_review_plan")
    specs = task_specs_from_dicts(payload.get("task_specs"))
    return SmartReviewPlan(
        primary_path=str(payload.get("primary_path") or "smart_committee"),
        specialist_ids=[str(item) for item in payload.get("specialist_ids") or []],
        bootstrap_review_plus=bool(payload.get("bootstrap_review_plus")),
        reasons=[str(item) for item in payload.get("reasons") or []],
        chief_review_plan=dict(chief) if isinstance(chief, dict) else None,
        degradation_summary=[str(item) for item in payload.get("degradation_summary") or []],
        task_specs=tuple(specs),
    )


def _is_smart_plan_complete(plan: SmartReviewPlan) -> bool:
    if not plan.primary_path:
        return False
    if plan.primary_path == "smart_committee":
        chief = plan.chief_review_plan
        has_chief = isinstance(chief, dict) and bool(chief.get("selected_agents"))
        has_specs = bool(plan.task_specs)
        return has_chief or has_specs
    return True


def _corpus_hint(run: SuperAgentRun, classification: dict[str, Any]) -> str:
    parts = [
        run.objective or "",
        str(classification.get("domain") or ""),
        str(classification.get("doc_type") or ""),
    ]
    for item in classification.get("material_roles") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("file_name") or item.get("filename") or item.get("name") or ""))
    for material in run.materials:
        parts.append(str(material.name or ""))
    return " ".join(parts).lower()


def _document_count(run: SuperAgentRun, classification: dict[str, Any]) -> int:
    roles = classification.get("material_roles") or []
    if roles:
        return len(roles)
    if run.materials:
        return len(run.materials)
    parsed = (run.structured_bundle.parse_artifact or {}).get("parsed_documents") or []
    return len(parsed) or 1


def _domain_id_from_classification(classification: dict[str, Any]) -> str:
    return resolve_domain_id(classification)


def _wants_gnc(corpus: str, *, review_plus_ready: bool, domain_id: str = "aerospace_review") -> bool:
    signals = route_signals_for_domain(domain_id)
    strong_tokens = tuple(signals.get("gnc_strong") or ())
    weak_tokens = tuple(signals.get("gnc_weak") or ())
    strong = any(token in corpus for token in strong_tokens)
    weak = any(token in corpus for token in weak_tokens)
    return strong or (weak and not review_plus_ready)


def _recommended_gnc_route(classification: dict[str, Any]) -> bool:
    routes = {
        str(classification.get("recommended_route") or "").strip().lower(),
        str(classification.get("final_recommended_route") or "").strip().lower(),
    }
    post_parse = classification.get("post_parse_route")
    if isinstance(post_parse, dict):
        routes.add(str(post_parse.get("suggested_route") or "").strip().lower())
        routes.add(str(post_parse.get("effective_route") or "").strip().lower())
    return bool(routes & {"gnc_review", "gnc_review_only"})


def _wants_review_plus_package(
    run: SuperAgentRun,
    classification: dict[str, Any],
    slot_status: dict[str, Any],
) -> bool:
    if not slot_status.get("review_plus_ready"):
        return False
    recommended = str(classification.get("recommended_route") or "").strip().lower()
    if recommended == "review_plus":
        return True
    if run.requested_route == SuperAgentRoute.REVIEW_PLUS:
        return True
    roles = {
        str(item.get("role") or "")
        for item in classification.get("material_roles") or []
        if isinstance(item, dict)
    }
    return materials_hint_review_plus_from_roles(roles)


def _review_plus_skip_reasons(
    run: SuperAgentRun,
    classification: dict[str, Any],
    slot_status: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if run.requested_route == SuperAgentRoute.SMART:
        reasons.append("用户/路由选择 SMART，由智能调度决定具体执行路径。")
    if not slot_status.get("review_plus_ready"):
        missing = slot_status.get("missing_roles") or slot_status.get("missing_slots") or []
        if missing:
            reasons.append(f"Review-Plus 槽位不完整，缺失: {', '.join(str(item) for item in missing)}。")
        else:
            reasons.append("Review-Plus 材料槽位不完整，未满足文件组审查条件。")
    elif not _wants_review_plus_package(run, classification, slot_status):
        reasons.append("槽位虽可用，但未命中 Review-Plus 路由/材料组合条件。")
    if not run.source_review_id:
        reasons.append("尚无 source_review_id，无法直接复用已有 Review-Plus 任务。")
    return reasons


def _gnc_skip_reasons(
    run: SuperAgentRun,
    classification: dict[str, Any],
    *,
    corpus: str,
    review_plus_ready: bool,
    wants_gnc: bool,
) -> list[str]:
    reasons: list[str] = []
    if not _recommended_gnc_route(classification):
        recommended = str(classification.get("recommended_route") or "").strip().lower()
        reasons.append(f"分类推荐路由为 {recommended or 'smart'}，非 gnc_review。")
    if not wants_gnc:
        reasons.append("语料/领域未命中 GNC 强/弱关键词。")
    gnc_mode = run.review_mode in {SuperAgentReviewMode.SINGLE_DOC, SuperAgentReviewMode.MULTI_DOC}
    if not gnc_mode and run.review_mode != SuperAgentReviewMode.FULL:
        reasons.append(f"review_mode={run.review_mode.value} 未指向 GNC 专项审查。")
    if review_plus_ready and not wants_gnc:
        reasons.append("Review-Plus 槽位已就绪且未命中 GNC 关键词，优先文件组审查。")
    return reasons


def _collect_corpus_text(
    run: SuperAgentRun,
    classification: dict[str, Any],
    materials: list[dict[str, Any]] | None = None,
) -> str:
    parts: list[str] = [run.objective or ""]
    parse_artifact = run.structured_bundle.parse_artifact or {}
    if not parse_artifact and isinstance(run.parse_preview, dict):
        parse_artifact = dict(run.parse_preview.get("parse_artifact") or {})
    for item in parse_artifact.get("parsed_documents") or []:
        if not isinstance(item, dict):
            continue
        document = item.get("document") if isinstance(item.get("document"), dict) else {}
        blocks = document.get("blocks") or []
        text = "\n".join(str(block.get("text") or "") for block in blocks if block.get("text"))
        if text.strip():
            parts.append(text[:5000])
    for material in run.structured_bundle.materials:
        if isinstance(material, dict):
            parts.append(str(material.get("content") or "")[:5000])
    for material in materials or []:
        parts.append(str(material.get("content") or "")[:5000])
    for material in run.materials:
        parts.append(str(material.content or material.content_preview or "")[:5000])
    for item in classification.get("material_roles") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("content_preview") or "")[:2000])
    section_tree = parse_artifact.get("section_tree") or run.structured_bundle.section_tree or {}
    for section in (section_tree.get("sections") or []) if isinstance(section_tree, dict) else []:
        if isinstance(section, dict):
            parts.append(str(section.get("text") or section.get("content") or "")[:2000])
    evidence_pool = parse_artifact.get("evidence_pool") or run.structured_bundle.evidence_pool or {}
    for evidence in (evidence_pool.get("evidences") or []) if isinstance(evidence_pool, dict) else []:
        if isinstance(evidence, dict):
            parts.append(str(evidence.get("excerpt") or evidence.get("quote") or evidence.get("text") or "")[:2000])
    return "\n".join(part for part in parts if part.strip())


def _materials_for_committee(run: SuperAgentRun, classification: dict[str, Any]) -> list[dict[str, Any]]:
    materials = [dict(item) for item in run.structured_bundle.materials if isinstance(item, dict)]
    if any(str(item.get("content") or "").strip() for item in materials):
        return materials
    result: list[dict[str, Any]] = []
    for item in classification.get("material_roles") or []:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "name": str(item.get("file_name") or item.get("filename") or item.get("name") or ""),
                "role": str(item.get("role") or "unknown"),
                "content": str(item.get("content_preview") or ""),
            }
        )
    if any(str(item.get("content") or "").strip() for item in result):
        return result
    for material in run.materials:
        result.append(
            {
                "name": material.name,
                "role": material.role or "subject_document",
                "content": material.content or material.content_preview or "",
            }
        )
    if any(str(item.get("content") or "").strip() for item in result):
        return result
    from data_agent.super_agent.phases.document_review.gnc import GncMixin

    return GncMixin()._gnc_materials_from_parse_artifact(run) or result


def committee_materials_for_run(
    run: SuperAgentRun,
    classification: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload = classification if isinstance(classification, dict) else {}
    if not payload and isinstance(run.classification, dict):
        payload = run.classification
    return _materials_for_committee(run, payload)


def committee_corpus_text_for_run(
    run: SuperAgentRun,
    classification: dict[str, Any] | None = None,
    materials: list[dict[str, Any]] | None = None,
) -> str:
    payload = classification if isinstance(classification, dict) else {}
    if not payload and isinstance(run.classification, dict):
        payload = run.classification
    mat = materials if materials is not None else committee_materials_for_run(run, payload)
    return _collect_corpus_text(run, payload, mat)


def _structure_context_for_run(run: SuperAgentRun) -> tuple[dict[str, Any], dict[str, Any]]:
    parse_artifact = run.structured_bundle.parse_artifact or {}
    if not parse_artifact and isinstance(run.parse_preview, dict):
        parse_artifact = dict(run.parse_preview.get("parse_artifact") or {})
    section_tree = parse_artifact.get("section_tree") or run.structured_bundle.section_tree or {}
    evidence_pool = parse_artifact.get("evidence_pool") or run.structured_bundle.evidence_pool or {}
    return (
        dict(section_tree) if isinstance(section_tree, dict) else {},
        dict(evidence_pool) if isinstance(evidence_pool, dict) else {},
    )


def _adaptive_router_notes(classification: dict[str, Any]) -> tuple[Any | None, list[str]]:
    from data_agent.core.adaptive_router import adaptive_route_from_classification

    adaptive = adaptive_route_from_classification(classification)
    if not adaptive or adaptive.source == "error":
        return None, []
    notes = [f"adaptive_router source={adaptive.source} confidence={adaptive.confidence:.2f}"]
    notes.extend(adaptive.guardrail_corrections)
    return adaptive, notes


def _smart_plan_from_adaptive_router(
    run: SuperAgentRun,
    classification: dict[str, Any],
    adaptive: Any,
    *,
    slot_status: dict[str, Any],
    rp_skip: list[str],
    gnc_skip: list[str],
    router_notes: list[str],
) -> SmartReviewPlan | None:
    from data_agent.core.task_spec import task_specs_from_dicts

    path = str(adaptive.primary_path or "").strip().lower()
    domain_id = str(adaptive.domain_id or _domain_id_from_classification(classification))

    if path == "structure_only":
        return SmartReviewPlan(
            primary_path="structure_only",
            reasons=["adaptive_router 指定 structure_only。"],
            degradation_summary=[*router_notes, *rp_skip, *gnc_skip, "adaptive_router → structure_only"],
        )

    if path == "review_plus" and bool(slot_status.get("review_plus_ready")):
        return SmartReviewPlan(
            primary_path="review_plus",
            bootstrap_review_plus=not bool(run.source_review_id),
            reasons=["adaptive_router 指定 Review-Plus 且槽位就绪。"],
            degradation_summary=[*router_notes, *gnc_skip, "adaptive_router → review_plus"],
        )

    if path == "gnc":
        return SmartReviewPlan(
            primary_path="gnc",
            reasons=["adaptive_router 指定 GNC 专项审查。"],
            degradation_summary=[*router_notes, *rp_skip, "adaptive_router → gnc"],
        )

    if path != "smart_committee":
        return None

    committee_materials = _materials_for_committee(run, classification)
    corpus_text = _collect_corpus_text(run, classification, committee_materials)
    review_plus_ready = bool(slot_status.get("review_plus_ready"))
    bootstrap = bool(committee_materials) and not review_plus_ready and not run.source_review_id

    task_specs = tuple(task_specs_from_dicts(adaptive.task_specs)) if adaptive.task_specs else tuple()
    specialist_ids = list(adaptive.selected_capabilities.specialist_ids or [])
    chief_plan: dict[str, Any] | None = None

    if not task_specs or not specialist_ids:
        from data_agent.review_plus.specialist_orchestration_service import plan_review_committee_from_context
        from data_agent.core.committee_planner import plan_smart_committee_tasks

        chief_plan = plan_review_committee_from_context(
            material_roles=classification.get("material_roles") or [],
            corpus_text=corpus_text,
            objective=run.objective or "",
            materials=committee_materials,
            domain_id=domain_id,
        )
        if not specialist_ids:
            specialist_ids = [
                str(item.get("agent_id") or "")
                for item in chief_plan.get("selected_agents") or []
                if item.get("agent_id")
            ]
        if not task_specs:
            task_specs = tuple(
                plan_smart_committee_tasks(
                    domain_id,
                    classification,
                    run.objective or "",
                    corpus_text,
                    chief_plan=chief_plan,
                )
            )

    reasons = ["adaptive_router 指定 smart_committee 总师委员会审查。"]
    if bootstrap:
        reasons.append("将 bootstrap 轻量 Review-Plus 任务以承载 specialist orchestration。")

    return SmartReviewPlan(
        primary_path="smart_committee",
        specialist_ids=specialist_ids,
        bootstrap_review_plus=bootstrap,
        reasons=reasons,
        chief_review_plan=chief_plan,
        degradation_summary=[
            *router_notes,
            *rp_skip,
            *gnc_skip,
            "adaptive_router → smart_committee",
        ],
        task_specs=task_specs,
    )


def dispatch_smart_review(
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision | None = None,
) -> SmartReviewPlan:
    """Decide which established workflow SMART should delegate to."""
    classification = dict(run.classification) if isinstance(run.classification, dict) else {}
    if decision and isinstance(decision.classification, dict) and decision.classification:
        classification = {**classification, **decision.classification}

    adaptive, router_notes = _adaptive_router_notes(classification)
    if adaptive and adaptive.domain_id:
        classification = {**classification, "domain_id": adaptive.domain_id}

    domain_id = _domain_id_from_classification(classification)
    slot_status = helpers.compute_review_plus_slot_status(classification.get("material_roles") or [])
    corpus = _corpus_hint(run, classification)
    doc_count = _document_count(run, classification)
    review_plus_ready = bool(slot_status.get("review_plus_ready"))
    recommended = str(classification.get("recommended_route") or "").strip().lower()
    rp_skip = _review_plus_skip_reasons(run, classification, slot_status)
    recommended_gnc = _recommended_gnc_route(classification)
    wants_gnc = (
        _wants_gnc(corpus, review_plus_ready=review_plus_ready, domain_id=domain_id)
        or recommended_gnc
    )
    custom_objective = has_custom_objective(run)
    objective_gnc = objective_implies_gnc(run.objective, domain_id=domain_id) if custom_objective else False
    suppress_corpus_gnc = objective_suppresses_gnc(run.objective, domain_id=domain_id)
    if objective_gnc:
        wants_gnc = True
    elif suppress_corpus_gnc and (recommended_gnc or wants_gnc):
        router_notes = [
            *router_notes,
            "用户自定义审查目标未表达 GNC 专项意图，不因正文关键词走 GNC 专项。",
        ]
        recommended_gnc = False
        wants_gnc = False
    gnc_skip = _gnc_skip_reasons(
        run,
        classification,
        corpus=corpus,
        review_plus_ready=review_plus_ready,
        wants_gnc=wants_gnc,
    )

    if not run.materials and not classification.get("material_roles") and not run.structured_bundle.parse_artifact:
        degradation = [
            *router_notes,
            *rp_skip,
            *gnc_skip,
            "尚未识别可审查材料，仅执行结构化。",
        ]
        return SmartReviewPlan(
            primary_path="structure_only",
            reasons=["尚未识别可审查材料，仅执行结构化。"],
            degradation_summary=degradation,
        )

    if adaptive:
        adaptive_plan = _smart_plan_from_adaptive_router(
            run,
            classification,
            adaptive,
            slot_status=slot_status,
            rp_skip=rp_skip,
            gnc_skip=gnc_skip,
            router_notes=router_notes,
        )
        if adaptive_plan is not None:
            return adaptive_plan

    if _wants_review_plus_package(run, classification, slot_status):
        degradation = [
            *gnc_skip,
            "材料槽位齐全，选择 Review-Plus 文件组审查。",
        ]
        return SmartReviewPlan(
            primary_path="review_plus",
            bootstrap_review_plus=not bool(run.source_review_id),
            reasons=["材料槽位齐全，优先走已成体系的文件组审查（Review-Plus）。"],
            degradation_summary=degradation,
        )

    gnc_mode = run.review_mode in {SuperAgentReviewMode.SINGLE_DOC, SuperAgentReviewMode.MULTI_DOC}
    if recommended_gnc and wants_gnc:
        degradation = [
            *rp_skip,
            "分类推荐 GNC 审查且命中 GNC/控制领域关键词。",
        ]
        return SmartReviewPlan(
            primary_path="gnc",
            reasons=["分类推荐 GNC 审查且命中 GNC/控制领域关键词。"],
            degradation_summary=degradation,
        )
    if gnc_mode and wants_gnc:
        degradation = [
            *rp_skip,
            f"review_mode={run.review_mode.value} 且命中 GNC 关键词。",
        ]
        return SmartReviewPlan(
            primary_path="gnc",
            reasons=[f"review_mode={run.review_mode.value} 且命中 GNC 关键词。"],
            degradation_summary=degradation,
        )
    if doc_count == 1 and wants_gnc:
        degradation = [
            *rp_skip,
            "单文档且命中 GNC 强/弱关键词，选择 GNC 专项审查。",
        ]
        return SmartReviewPlan(
            primary_path="gnc",
            reasons=["单文档且命中 GNC 强/弱关键词，走 GNC 专项审查。"],
            degradation_summary=degradation,
        )

    from data_agent.review_plus.specialist_orchestration_service import plan_review_committee_from_context

    committee_materials = _materials_for_committee(run, classification)
    corpus_text = _collect_corpus_text(run, classification, committee_materials)
    chief_plan = plan_review_committee_from_context(
        material_roles=classification.get("material_roles") or [],
        corpus_text=corpus_text,
        objective=run.objective or "",
        materials=committee_materials,
        domain_id=domain_id,
    )
    specialist_ids = [
        str(item.get("agent_id") or "")
        for item in chief_plan.get("selected_agents") or []
        if item.get("agent_id")
    ]

    bootstrap = bool(committee_materials) and not review_plus_ready and not run.source_review_id
    reasons = ["槽位不完整或未命中 GNC/文件组条件，走智能总师调度 + 有限 specialist 审查。"]
    if bootstrap:
        reasons.append("将 bootstrap 轻量 Review-Plus 任务以承载 specialist orchestration。")

    from data_agent.core.committee_planner import plan_smart_committee_tasks

    task_specs = plan_smart_committee_tasks(
        domain_id,
        classification,
        run.objective or "",
        corpus_text,
        chief_plan=chief_plan,
    )

    degradation = [
        *router_notes,
        *rp_skip,
        *gnc_skip,
        "未满足 Review-Plus / GNC 条件，选择 smart_committee 总师委员会审查。",
    ]
    return SmartReviewPlan(
        primary_path="smart_committee",
        specialist_ids=specialist_ids,
        bootstrap_review_plus=bootstrap,
        reasons=reasons,
        chief_review_plan=chief_plan,
        degradation_summary=degradation,
        task_specs=tuple(task_specs),
    )


def attach_smart_review_plan(run: SuperAgentRun, plan: SmartReviewPlan) -> None:
    payload = smart_plan_to_dict(plan)
    if not isinstance(run.classification, dict):
        run.classification = {}
    run.classification["smart_review_plan"] = payload

    review_plan = run.classification.get("review_plan")
    if isinstance(review_plan, dict):
        run.classification["review_plan"] = {
            **review_plan,
            "smart_primary_path": plan.primary_path,
            "smart_specialist_ids": list(plan.specialist_ids),
            "smart_dispatch_reasons": list(plan.reasons),
            "smart_review_plan": payload,
            "degradation_summary": list(plan.degradation_summary),
        }

    artifact = run.phase_artifacts.get("classify_and_route")
    if isinstance(artifact, dict):
        classification = dict(artifact.get("classification") or run.classification)
        classification["smart_review_plan"] = payload
        review_in_artifact = classification.get("review_plan")
        if isinstance(review_in_artifact, dict):
            classification["review_plan"] = {
                **review_in_artifact,
                "smart_primary_path": plan.primary_path,
                "smart_specialist_ids": list(plan.specialist_ids),
                "smart_dispatch_reasons": list(plan.reasons),
                "smart_review_plan": payload,
                "degradation_summary": list(plan.degradation_summary),
            }
        run.phase_artifacts["classify_and_route"] = {
            **artifact,
            "classification": classification,
        }


def get_smart_review_plan(run: SuperAgentRun) -> SmartReviewPlan | None:
    if not isinstance(run.classification, dict):
        return None
    return smart_plan_from_dict(run.classification.get("smart_review_plan"))


def resolve_smart_review_plan(
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision | None = None,
    *,
    force_refresh: bool = False,
) -> SmartReviewPlan:
    if not force_refresh:
        existing = get_smart_review_plan(run)
        if existing and _is_smart_plan_complete(existing):
            return existing
    plan = dispatch_smart_review(run, decision)
    attach_smart_review_plan(run, plan)
    return plan


def record_smart_degradation(run: SuperAgentRun, plan: SmartReviewPlan) -> None:
    if not plan.degradation_summary:
        return
    existing = list(run.trace_report.degradation_summary or [])
    for item in plan.degradation_summary:
        if item not in existing:
            existing.append(item)
    run.trace_report.degradation_summary = existing


def active_smart_skill_ids(plan: SmartReviewPlan) -> set[str]:
    if plan.primary_path == "structure_only":
        return {"structure_materials"}
    if plan.primary_path == "gnc":
        return {"structure_materials", "run_gnc_review"}
    if plan.primary_path == "review_plus":
        skills = {"structure_materials", "run_review_plus"}
        if plan.bootstrap_review_plus:
            skills.add("bootstrap_review_plus_task")
        return skills
    if plan.primary_path == "smart_committee":
        skills = {"structure_materials", "smart_review_committee"}
        if plan.bootstrap_review_plus:
            skills.add("bootstrap_review_plus_task")
        return skills
    return {"structure_materials"}


__all__ = [
    "SmartReviewPlan",
    "active_smart_skill_ids",
    "attach_smart_review_plan",
    "committee_corpus_text_for_run",
    "committee_materials_for_run",
    "dispatch_smart_review",
    "get_smart_review_plan",
    "record_smart_degradation",
    "resolve_smart_review_plan",
    "smart_plan_from_dict",
    "smart_plan_to_dict",
]
