"""Unified execution graph: single source for route tools and executable skills."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from data_agent.super_agent.execution_plan import ParsingPlan
from data_agent.super_agent.schemas import (
    SuperAgentReviewMode,
    SuperAgentRoute,
    SuperAgentRouteDecision,
    SuperAgentRun,
)

SkipPredicate = Callable[[SuperAgentRun, SuperAgentRouteDecision, ParsingPlan | None], bool]


@dataclass(frozen=True)
class ExecutionNodeSpec:
    id: str
    wizard_step: int | None = None
    depends_on: tuple[str, ...] = ()
    category: str = "skill"
    skip_when: SkipPredicate | None = None


def _skip_bootstrap_unless_plan(_run: SuperAgentRun, _decision: SuperAgentRouteDecision, plan: ParsingPlan | None) -> bool:
    return not bool(plan and plan.bootstrap_review_plus)


def _skip_unless_hybrid(_run: SuperAgentRun, decision: SuperAgentRouteDecision, _plan: ParsingPlan | None) -> bool:
    return decision.route != SuperAgentRoute.HYBRID


_NODE_SPECS: dict[str, ExecutionNodeSpec] = {
    "bootstrap_review_plus_task": ExecutionNodeSpec(
        id="bootstrap_review_plus_task",
        wizard_step=4,
        category="skill",
        skip_when=_skip_bootstrap_unless_plan,
    ),
    "structure_materials": ExecutionNodeSpec(
        id="structure_materials",
        wizard_step=3,
        depends_on=("bootstrap_review_plus_task",),
        category="skill",
    ),
    "run_review_plus": ExecutionNodeSpec(
        id="run_review_plus",
        wizard_step=4,
        depends_on=("structure_materials",),
        category="skill",
    ),
    "run_gnc_review": ExecutionNodeSpec(
        id="run_gnc_review",
        wizard_step=4,
        depends_on=("structure_materials",),
        category="skill",
    ),
    "smart_review_committee": ExecutionNodeSpec(
        id="smart_review_committee",
        wizard_step=4,
        depends_on=("structure_materials",),
        category="skill",
    ),
    "gnc_committee_review": ExecutionNodeSpec(
        id="gnc_committee_review",
        wizard_step=4,
        depends_on=("run_gnc_review",),
        category="gnc_extra",
        skip_when=_skip_unless_hybrid,
    ),
    "gnc_cross_document_consistency": ExecutionNodeSpec(
        id="gnc_cross_document_consistency",
        wizard_step=4,
        depends_on=("run_gnc_review",),
        category="gnc_extra",
        skip_when=_skip_unless_hybrid,
    ),
    "collect_traces": ExecutionNodeSpec(
        id="collect_traces",
        wizard_step=5,
        category="infra",
    ),
    "evaluate_quality": ExecutionNodeSpec(
        id="evaluate_quality",
        wizard_step=5,
        depends_on=("collect_traces",),
        category="infra",
    ),
}

_ROUTE_SEQUENCES: dict[SuperAgentRoute, tuple[str, ...]] = {
    SuperAgentRoute.REVIEW_PLUS: (
        "bootstrap_review_plus_task",
        "structure_materials",
        "run_review_plus",
        "collect_traces",
        "evaluate_quality",
    ),
    SuperAgentRoute.GNC_REVIEW: (
        "run_gnc_review",
        "collect_traces",
        "evaluate_quality",
    ),
    SuperAgentRoute.GNC_REVIEW_ONLY: (
        "run_gnc_review",
        "collect_traces",
        "evaluate_quality",
    ),
    SuperAgentRoute.HYBRID: (
        "structure_materials",
        "run_review_plus",
        "run_gnc_review",
        "gnc_committee_review",
        "gnc_cross_document_consistency",
        "collect_traces",
        "evaluate_quality",
    ),
    SuperAgentRoute.SMART: (
        "bootstrap_review_plus_task",
        "structure_materials",
        "run_gnc_review",
        "run_review_plus",
        "smart_review_committee",
        "collect_traces",
        "evaluate_quality",
    ),
    SuperAgentRoute.STRUCTURE_ONLY: (
        "structure_materials",
        "collect_traces",
        "evaluate_quality",
    ),
}


@dataclass
class ExecutionNode:
    spec: ExecutionNodeSpec
    skipped: bool = False
    skip_reason: str = ""


def _smart_plan_for_run(run: SuperAgentRun, decision: SuperAgentRouteDecision) -> set[str]:
    from data_agent.super_agent.phases.document_review.smart_orchestrator import (
        active_smart_skill_ids,
        resolve_smart_review_plan,
    )

    plan = resolve_smart_review_plan(run, decision)
    return active_smart_skill_ids(plan)


def _review_mode_skill_filter(
    node_id: str,
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision,
) -> tuple[bool, str]:
    route = decision.route
    review_mode = run.review_mode

    if route == SuperAgentRoute.SMART:
        active = _smart_plan_for_run(run, decision)
        if node_id not in active:
            return True, f"smart dispatch path excludes {node_id}"
        return False, ""

    if review_mode == SuperAgentReviewMode.FULL:
        if node_id == "run_review_plus" and route not in {SuperAgentRoute.REVIEW_PLUS, SuperAgentRoute.HYBRID}:
            return True, "route does not require review_plus"
        if node_id == "run_gnc_review" and route not in {
            SuperAgentRoute.GNC_REVIEW,
            SuperAgentRoute.GNC_REVIEW_ONLY,
            SuperAgentRoute.HYBRID,
        }:
            return True, "route does not require gnc_review"
        if node_id == "structure_materials" and route != SuperAgentRoute.STRUCTURE_ONLY:
            if route in {SuperAgentRoute.REVIEW_PLUS, SuperAgentRoute.GNC_REVIEW, SuperAgentRoute.GNC_REVIEW_ONLY}:
                return True, "structure deferred to review skill"
        return False, ""

    if review_mode in {SuperAgentReviewMode.SINGLE_DOC, SuperAgentReviewMode.MULTI_DOC}:
        if node_id == "run_gnc_review" and route not in {
            SuperAgentRoute.GNC_REVIEW,
            SuperAgentRoute.GNC_REVIEW_ONLY,
            SuperAgentRoute.HYBRID,
        }:
            return True, "review_mode gnc-only"
        if node_id == "run_review_plus" and route != SuperAgentRoute.REVIEW_PLUS:
            return True, "review_mode not review_plus"
        if node_id == "structure_materials" and route != SuperAgentRoute.STRUCTURE_ONLY:
            return True, "review_mode skips standalone structure"
        return False, ""

    if node_id == "run_review_plus" and route not in {SuperAgentRoute.REVIEW_PLUS, SuperAgentRoute.HYBRID}:
        return True, "route does not require review_plus"
    if node_id == "run_gnc_review" and route not in {
        SuperAgentRoute.GNC_REVIEW,
        SuperAgentRoute.GNC_REVIEW_ONLY,
        SuperAgentRoute.HYBRID,
    }:
        return True, "route does not require gnc_review"
    return False, ""


def resolve_execution_graph(
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision,
    *,
    plan: ParsingPlan | None = None,
) -> list[ExecutionNode]:
    sequence = _ROUTE_SEQUENCES.get(decision.route, _ROUTE_SEQUENCES[SuperAgentRoute.STRUCTURE_ONLY])
    nodes: list[ExecutionNode] = []
    for node_id in sequence:
        spec = _NODE_SPECS[node_id]
        skipped = False
        reason = ""
        if spec.skip_when and spec.skip_when(run, decision, plan):
            skipped = True
            reason = "plan/route predicate"
        elif spec.category == "skill":
            skipped, reason = _review_mode_skill_filter(node_id, run, decision)
        nodes.append(ExecutionNode(spec=spec, skipped=skipped, skip_reason=reason))
    return nodes


def active_node_ids(
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision,
    *,
    plan: ParsingPlan | None = None,
    categories: set[str] | None = None,
) -> list[str]:
    graph = resolve_execution_graph(run, decision, plan=plan)
    result: list[str] = []
    for node in graph:
        if node.skipped:
            continue
        if categories is not None and node.spec.category not in categories:
            continue
        result.append(node.spec.id)
    return result


def tools_for_route(route: SuperAgentRoute) -> list[str]:
    """Required tools for a route decision (planning / route_decision.required_tools)."""
    return list(_ROUTE_SEQUENCES.get(route, _ROUTE_SEQUENCES[SuperAgentRoute.STRUCTURE_ONLY]))


def skills_for_execution(
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision,
    *,
    plan: ParsingPlan | None = None,
) -> list[str]:
    """Executable review skills for document_review phase (excludes infra/gnc_extra)."""
    skills = active_node_ids(run, decision, plan=plan, categories={"skill"})
    return skills or ["structure_materials"]


def skipped_tools_for_route(
    run: SuperAgentRun,
    decision: SuperAgentRouteDecision,
    *,
    plan: ParsingPlan | None = None,
) -> list[str]:
    return [node.spec.id for node in resolve_execution_graph(run, decision, plan=plan) if node.skipped]
