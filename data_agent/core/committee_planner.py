"""Deterministic committee TaskSpec planner (Hermes-style Decompose, no LLM)."""

from __future__ import annotations

from typing import Any

from data_agent.core.task_spec import (
    KIND_ARBITER_SUMMARY,
    KIND_FORMAT_GATE,
    KIND_SMART_SPECIALIST_REVIEW,
    TaskSpec,
    stable_task_id,
)

_GENERIC_DOMAIN_ID = "generic_document_review"
_DEFAULT_GENERIC_SPECIALIST_CAP = 3


def _format_reviewer_id(catalog: dict[str, dict[str, Any]]) -> str | None:
    for candidate in ("document_format_reviewer", "document_consistency_reviewer"):
        if candidate in catalog:
            return candidate
    for agent_id, profile in catalog.items():
        if "all" in (profile.get("triggers") or []):
            return agent_id
    return None


def _keyword_hits(text: str, triggers: list[str]) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for trigger in triggers:
        if trigger == "all":
            continue
        if trigger.lower() in lowered:
            hits.append(trigger)
    return hits


def _route_signal_hits(text: str, route_signals: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    matched: list[str] = []
    for tokens in route_signals.values():
        for token in tokens:
            if token.lower() in lowered and token not in matched:
                matched.append(token)
    return matched


def _specialist_ids_from_chief_plan(chief_plan: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    entries: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for item in chief_plan.get("selected_agents") or []:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agent_id") or "").strip()
        if agent_id and agent_id not in seen:
            seen.add(agent_id)
            entries.append((agent_id, item))
    return entries


def _generic_specialist_cap(defaults: dict[str, Any]) -> int:
    raw = defaults.get("max_specialists", _DEFAULT_GENERIC_SPECIALIST_CAP)
    try:
        cap = int(raw)
    except (TypeError, ValueError):
        cap = _DEFAULT_GENERIC_SPECIALIST_CAP
    return max(1, min(cap, 5))


def _cap_generic_specialists(
    entries: list[tuple[str, dict[str, Any]]],
    *,
    format_id: str | None,
    cap: int,
) -> list[tuple[str, dict[str, Any]]]:
    """Keep format baseline and at most ``cap`` additional specialist reviews."""
    if not entries:
        return entries

    format_entries = [item for item in entries if item[0] == format_id]
    others = [item for item in entries if item[0] != format_id]
    if len(others) <= cap:
        return [*format_entries, *others]

    def rank(entry: tuple[str, dict[str, Any]]) -> tuple[int, int]:
        meta = entry[1]
        if meta.get("required"):
            return (0, 0)
        signals = meta.get("matched_signals") or []
        return (1, -len(signals))

    others.sort(key=rank)
    return [*format_entries, *others[:cap]]


def _select_specialist_entries_without_chief(
    *,
    catalog: dict[str, dict[str, Any]],
    domain_id: str,
    text: str,
    route_signals: dict[str, list[str]],
) -> list[tuple[str, dict[str, Any]]]:
    from data_agent.core.domain_registry import committee_defaults_for_domain

    selected: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    is_generic = domain_id == _GENERIC_DOMAIN_ID

    def select(
        agent_id: str,
        reason: str,
        *,
        matched_signals: list[str] | None = None,
        required: bool = False,
    ) -> None:
        if agent_id in seen or agent_id not in catalog:
            return
        seen.add(agent_id)
        profile = catalog[agent_id]
        selected.append(
            (
                agent_id,
                {
                    "agent_id": agent_id,
                    "agent_name": profile.get("name", agent_id),
                    "reason": reason,
                    "matched_signals": matched_signals or [],
                    "required": required,
                },
            )
        )

    format_id = _format_reviewer_id(catalog)
    if format_id:
        select(format_id, "任何正式审查都必须先确认文档结构、解析质量和版本基线。", required=True)

    defaults = committee_defaults_for_domain(domain_id)
    required_ids = [str(item) for item in defaults.get("required_specialists") or []]
    if is_generic:
        baseline_ids = [
            item
            for item in required_ids
            if item != format_id and item in catalog
        ]
        if not baseline_ids and format_id:
            baseline_ids = [format_id]
        for baseline_id in baseline_ids[:1]:
            profile = catalog.get(baseline_id) or {}
            select(
                baseline_id,
                f"通用审查基线专家：{profile.get('role') or baseline_id}。",
                required=True,
            )
    else:
        for required_id in required_ids:
            if required_id == format_id:
                continue
            profile = catalog.get(required_id) or {}
            select(
                required_id,
                f"领域默认必选：{profile.get('role') or required_id}。",
                required=True,
            )

    for agent_id, profile in catalog.items():
        if agent_id in seen:
            continue
        hits = _keyword_hits(text, profile.get("triggers") or [])
        if hits:
            select(
                agent_id,
                f"语料/目标关键词命中: {', '.join(hits[:6])}。",
                matched_signals=hits,
            )

    matched_tokens = _route_signal_hits(text, route_signals)
    if matched_tokens:
        for agent_id, profile in catalog.items():
            if agent_id in seen:
                continue
            triggers = profile.get("triggers") or []
            if "all" in triggers:
                continue
            overlap = [
                token
                for token in matched_tokens
                if any(
                    token.lower() in str(trigger).lower()
                    or str(trigger).lower() in token.lower()
                    for trigger in triggers
                )
            ]
            if overlap:
                select(
                    agent_id,
                    f"路由信号辅助命中专业审查: {', '.join(overlap[:6])}。",
                    matched_signals=overlap,
                )

    if is_generic:
        cap = _generic_specialist_cap(defaults)
        return _cap_generic_specialists(selected, format_id=format_id, cap=cap)
    return selected


def append_arbiter_task_spec(
    specs: list[TaskSpec],
    *,
    objective: str = "",
    domain_id: str = "",
) -> list[TaskSpec]:
    """Ensure arbiter_summary TaskSpec depends on all specialist review tasks."""
    if any(spec.kind == KIND_ARBITER_SUMMARY for spec in specs):
        return specs

    specialist_task_ids = [
        spec.task_id
        for spec in specs
        if spec.kind == KIND_SMART_SPECIALIST_REVIEW
    ]
    if not specialist_task_ids:
        return specs

    arbiter_id = stable_task_id(KIND_ARBITER_SUMMARY, "committee")
    return [
        *specs,
        TaskSpec(
            task_id=arbiter_id,
            kind=KIND_ARBITER_SUMMARY,
            agent_id="smart_arbiter",
            specialist_id="smart_arbiter",
            title="总师综合评判",
            depends_on=specialist_task_ids,
            input_summary={
                "domain_id": domain_id,
                "objective": objective,
                "arbiter": True,
            },
            required_evidence=False,
            priority=100,
        ),
    ]


def _resolve_specialist_entries(
    *,
    catalog: dict[str, dict[str, Any]],
    domain_id: str,
    objective: str,
    corpus_text: str,
    chief_plan: dict[str, Any] | None,
    route_signals: dict[str, list[str]],
) -> list[tuple[str, dict[str, Any]]]:
    if chief_plan and chief_plan.get("selected_agents"):
        return _specialist_ids_from_chief_plan(chief_plan)
    text = "\n".join(part for part in (objective, corpus_text) if part).strip()
    return _select_specialist_entries_without_chief(
        catalog=catalog,
        domain_id=domain_id,
        text=text,
        route_signals=route_signals,
    )


def plan_smart_committee_tasks(
    domain_id: str,
    classification: dict[str, Any] | None,
    objective: str,
    corpus_text: str,
    chief_plan: dict[str, Any] | None = None,
    bootstrap_summary: dict[str, Any] | None = None,
) -> list[TaskSpec]:
    """Build stable TaskSpec DAG for SMART committee execution."""
    from data_agent.core.agent_profile import profile_for_specialist
    from data_agent.core.domain_registry import (
        route_signals_for_domain,
        specialist_catalog_for_domain,
    )

    catalog = specialist_catalog_for_domain(domain_id)
    route_signals = route_signals_for_domain(domain_id)
    classification = classification if isinstance(classification, dict) else {}
    bootstrap = dict(bootstrap_summary or {})
    text = "\n".join(part for part in (objective, corpus_text) if part).strip()
    global_route_hits = _route_signal_hits(text, route_signals)

    entries = _resolve_specialist_entries(
        catalog=catalog,
        domain_id=domain_id,
        objective=objective,
        corpus_text=corpus_text,
        chief_plan=chief_plan,
        route_signals=route_signals,
    )

    format_id = _format_reviewer_id(catalog)
    format_task_id: str | None = None
    specs: list[TaskSpec] = []

    ordered_ids = [agent_id for agent_id, _ in entries]
    if format_id and format_id in ordered_ids:
        entry = next(item for agent_id, item in entries if agent_id == format_id)
        format_task_id = stable_task_id(KIND_FORMAT_GATE, format_id)
        profile_summary: dict[str, Any] = {}
        try:
            profile_summary = profile_for_specialist(format_id, domain_id=domain_id).summary()
        except Exception:
            profile_summary = {"agent_id": format_id}

        specs.append(
            TaskSpec(
                task_id=format_task_id,
                kind=KIND_FORMAT_GATE,
                agent_id=format_id,
                specialist_id=format_id,
                title=str(entry.get("agent_name") or catalog.get(format_id, {}).get("name") or format_id),
                depends_on=[],
                input_summary={
                    "specialist_id": format_id,
                    "domain_id": domain_id,
                    "objective": objective,
                    "assignment_reason": str(entry.get("reason") or ""),
                    "bootstrap_summary": bootstrap,
                    "route_signal_hits": global_route_hits,
                    "matched_signals": list(entry.get("matched_signals") or []),
                },
                required_evidence=True,
                profile=profile_summary,
                priority=0,
            )
        )

    for agent_id, entry in entries:
        if agent_id == format_id and format_task_id:
            continue

        profile_summary = {}
        try:
            profile_summary = profile_for_specialist(agent_id, domain_id=domain_id).summary()
        except Exception:
            profile_summary = {"agent_id": agent_id}

        matched = list(entry.get("matched_signals") or [])
        depends_on = [format_task_id] if format_task_id else []

        specs.append(
            TaskSpec(
                task_id=stable_task_id(KIND_SMART_SPECIALIST_REVIEW, agent_id),
                kind=KIND_SMART_SPECIALIST_REVIEW,
                agent_id=agent_id,
                specialist_id=agent_id,
                title=str(entry.get("agent_name") or catalog.get(agent_id, {}).get("name") or agent_id),
                depends_on=depends_on,
                input_summary={
                    "specialist_id": agent_id,
                    "domain_id": domain_id,
                    "objective": objective,
                    "assignment_reason": str(entry.get("reason") or ""),
                    "bootstrap_summary": bootstrap,
                    "route_signal_hits": global_route_hits,
                    "matched_signals": matched,
                },
                required_evidence=True,
                profile=profile_summary,
                priority=10,
            )
        )

    return append_arbiter_task_spec(
        specs,
        objective=objective,
        domain_id=domain_id,
    )


__all__ = ["append_arbiter_task_spec", "plan_smart_committee_tasks"]
