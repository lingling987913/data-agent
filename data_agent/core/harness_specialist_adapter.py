"""Adapter to run a single Review-Plus harness specialist for SMART committee."""

from __future__ import annotations

from typing import Any

from data_agent.core.domain_registry import harness_agent_for_specialist
from data_agent.review_plus.agent_harness import (
    SPECIALIST_TO_HARNESS_AGENT,
    AgentRunTrace,
    ReviewPlusAgentHarness,
    ReviewPlusAgentHarnessError,
    ReviewPlusHarnessPlan,
)
from data_agent.review_plus.schemas import ReviewPlusMaterialRole


def _matched_signals(chief_plan: dict[str, Any], specialist_id: str) -> list[str]:
    for item in chief_plan.get("selected_agents") or []:
        if isinstance(item, dict) and str(item.get("agent_id") or "") == specialist_id:
            return [str(signal) for signal in item.get("matched_signals") or []]
    return []


def _context_has_review_materials(context: dict[str, Any] | None) -> bool:
    if not context:
        return False
    corpus_text = str(context.get("corpus_text") or "").strip()
    if corpus_text:
        return True
    for item in context.get("materials") or []:
        if isinstance(item, dict) and str(item.get("content") or "").strip():
            return True
    return False


_GENERIC_DOMAIN_ID = "generic_document_review"


def resolve_harness_strategy(
    specialist_id: str,
    domain_id: str = "aerospace_review",
) -> str:
    """Classify how a specialist would be executed via harness."""
    harness_agent_id = harness_agent_for_specialist(specialist_id, domain_id)
    if not harness_agent_id:
        harness_agent_id = SPECIALIST_TO_HARNESS_AGENT.get(specialist_id)
    if not harness_agent_id:
        return "unavailable"
    if domain_id == _GENERIC_DOMAIN_ID:
        return "generic_harness"
    return "review_plus_harness"


def harness_availability_for_specialist(
    specialist_id: str,
    context: dict[str, Any] | None = None,
    *,
    domain_id: str = "aerospace_review",
) -> dict[str, Any]:
    """Report whether a harness specialist can be attempted and why not."""
    from data_agent.review_plus.agent_service import _agents_enabled

    harness_agent_id = harness_agent_for_specialist(specialist_id, domain_id)
    if not harness_agent_id:
        harness_agent_id = SPECIALIST_TO_HARNESS_AGENT.get(specialist_id)
    harness_strategy = resolve_harness_strategy(specialist_id, domain_id)
    base: dict[str, Any] = {
        "harness_strategy": harness_strategy,
        "harness_agent_id": harness_agent_id or "",
    }
    if not harness_agent_id:
        return {
            **base,
            "harness_available": False,
            "harness_unavailable_reason": "missing_mapping",
        }
    if not _agents_enabled():
        return {
            **base,
            "harness_available": False,
            "harness_unavailable_reason": "disabled",
        }
    if not _context_has_review_materials(context):
        return {
            **base,
            "harness_available": False,
            "harness_unavailable_reason": "missing_context",
        }
    return {
        **base,
        "harness_available": True,
        "harness_unavailable_reason": "",
    }


def _normalize_check_items(items: list[Any]) -> list[Any]:
    from types import SimpleNamespace

    normalized: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            requirement_text = str(item.get("requirement_text") or item.get("description") or "")
            source_quote = str(item.get("source_quote") or requirement_text or item.get("title") or "")
            evidence_ref = str(
                item.get("source_evidence_ref")
                or item.get("evidence_id")
                or (item.get("evidence_refs") or [""])[0]
                if isinstance(item.get("evidence_refs"), list)
                else item.get("source_evidence_ref")
                or ""
            )
            normalized.append(
                SimpleNamespace(
                    check_item_id=str(item.get("check_item_id") or item.get("id") or ""),
                    title=str(item.get("title") or ""),
                    description=str(item.get("description") or requirement_text),
                    requirement_text=requirement_text,
                    source_quote=source_quote,
                    source_evidence_ref=evidence_ref,
                    source_role=str(item.get("source_role") or item.get("source") or "synthetic"),
                    source_material_name=str(item.get("source_material_name") or "smart_synthetic_checklist"),
                )
            )
        else:
            normalized.append(item)
    return normalized


def _merge_synthetic_evidence_pool(task: Any, context: dict[str, Any]) -> None:
    pool = getattr(task, "evidence_pool", None)
    if not isinstance(pool, dict):
        pool = {}
    evidences = list(pool.get("evidences") or [])
    if evidences:
        return

    for ref in context.get("source_evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        evidences.append(
            {
                "evidence_id": str(ref.get("evidence_id") or ""),
                "excerpt": str(ref.get("excerpt") or ref.get("quote") or ref.get("text") or ""),
                "page": ref.get("page") or ref.get("page_no"),
                "source_file_name": str(ref.get("source_file_name") or ""),
            }
        )

    section_tree = context.get("section_tree")
    if isinstance(section_tree, dict):
        for section in (section_tree.get("sections") or [])[:10]:
            if not isinstance(section, dict):
                continue
            evidences.append(
                {
                    "evidence_id": str(section.get("section_id") or section.get("id") or f"sec-{len(evidences)+1}"),
                    "excerpt": str(section.get("text") or section.get("content") or section.get("title") or "")[:400],
                    "source_file_name": str(section.get("source_file_name") or ""),
                }
            )

    if evidences:
        setattr(task, "evidence_pool", {"evidences": evidences})


def _synthetic_task_book_content(context: dict[str, Any]) -> str:
    book = str(context.get("synthetic_task_book") or "").strip()
    objective = str(context.get("objective") or "").strip()
    check_items = context.get("check_items") or context.get("synthetic_check_items") or []
    requirement_lines: list[str] = []
    for item in check_items[:6]:
        if not isinstance(item, dict):
            continue
        line = str(item.get("requirement_text") or item.get("title") or "").strip()
        if len(line) >= 6:
            requirement_lines.append(f"要求：{line}")
    if book:
        if requirement_lines and "要求：" not in book:
            return f"{book}\n" + "\n".join(requirement_lines)
        return book
    lines = [
        "【SMART 合成任务书】",
        f"审查目标：{objective or '文档核心结论'}。",
        "验收要求：应满足指标与交付要求，结论须可追溯至章节或证据。",
    ]
    lines.extend(requirement_lines)
    if objective:
        return "\n".join(lines)
    return "智能审查：应核对文档指标、验收要求与结论一致性。"


def _apply_smart_bootstrap_materials(task: Any, context: dict[str, Any]) -> None:
    """Inject minimal package roles so harness material gate can proceed under SMART bootstrap."""
    if str(context.get("bootstrap_mode") or "") != "smart_synthetic_context":
        return

    from types import SimpleNamespace

    existing = list(getattr(task, "materials", []) or [])
    roles_present = {
        str(getattr(item, "role", "") or (item.get("role") if isinstance(item, dict) else ""))
        for item in existing
    }
    subject_content = ""
    for item in existing:
        content = str(getattr(item, "content", "") or (item.get("content") if isinstance(item, dict) else ""))
        if content.strip():
            subject_content = content[:8000]
            break
    if not subject_content:
        subject_content = str(context.get("corpus_text") or "").strip()
    if not subject_content:
        for ref in context.get("source_evidence_refs") or []:
            if isinstance(ref, dict):
                excerpt = str(ref.get("excerpt") or ref.get("quote") or "").strip()
                if excerpt:
                    subject_content = excerpt
                    break
    subject_content = subject_content[:8000]

    synthetic_book = _synthetic_task_book_content(context)
    check_items = context.get("check_items") or context.get("synthetic_check_items") or []
    checklist_lines = [
        "智能合成检查单：单文档 SMART 审查上下文。",
        "要求：应满足指标与验收交付要求。",
        "验收：结论应覆盖审查目标并可追溯至章节或证据引用。",
    ]
    for item in check_items[:8]:
        if isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            line = str(item.get("requirement_text") or item.get("description") or title).strip()
            quote = str(item.get("source_quote") or "").strip()
            if len(line) >= 6:
                entry = f"- [{item.get('check_item_id') or title}] {line}"
                if quote:
                    entry += f"（依据：{quote[:120]}）"
                checklist_lines.append(entry)
    additions: list[Any] = []
    if ReviewPlusMaterialRole.TASK_BOOK.value not in roles_present:
        additions.append(
            SimpleNamespace(
                name="smart_synthetic_task_book",
                content=f"{synthetic_book}\n要求：应满足指标与验收交付要求。",
                role=ReviewPlusMaterialRole.TASK_BOOK.value,
                included_in_formal_review=True,
                role_confirmed=True,
            )
        )
    if not (
        roles_present
        & {
            ReviewPlusMaterialRole.CHECKLIST.value,
            ReviewPlusMaterialRole.REVIEW_RULE.value,
        }
    ):
        additions.append(
            SimpleNamespace(
                name="smart_synthetic_checklist",
                content="\n".join(checklist_lines),
                role=ReviewPlusMaterialRole.CHECKLIST.value,
                included_in_formal_review=True,
                role_confirmed=True,
            )
        )
    if not (
        roles_present
        & {
            ReviewPlusMaterialRole.SUBJECT_REPORT.value,
            ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
        }
    ):
        additions.append(
            SimpleNamespace(
                name="smart_synthetic_subject",
                content=subject_content or synthetic_book,
                role=ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
                included_in_formal_review=True,
                role_confirmed=True,
            )
        )

    if additions:
        setattr(task, "materials", [*existing, *additions])
    setattr(task, "smart_bootstrap_mode", True)


def _enrich_task_from_context(task: Any, context: dict[str, Any] | None) -> None:
    if not context:
        return
    objective = str(context.get("objective") or "").strip()
    if objective:
        setattr(task, "scenario", objective)
    section_tree = context.get("section_tree")
    if isinstance(section_tree, dict) and section_tree:
        setattr(task, "section_tree", section_tree)
    evidence_pool = context.get("evidence_pool")
    if isinstance(evidence_pool, dict) and evidence_pool:
        setattr(task, "evidence_pool", evidence_pool)
    check_items = context.get("check_items") or context.get("synthetic_check_items")
    if check_items:
        setattr(task, "check_items", _normalize_check_items(list(check_items)))
    document_format_review = context.get("document_format_review")
    if isinstance(document_format_review, dict) and document_format_review:
        setattr(task, "document_format_review", document_format_review)
    if str(context.get("bootstrap_mode") or "") == "smart_synthetic_context":
        setattr(task, "smart_bootstrap_mode", True)
        _apply_smart_bootstrap_materials(task, context)
        _merge_synthetic_evidence_pool(task, context)


def _coerce_harness_finding(item: Any, *, specialist_id: str, index: int) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        payload = item.model_dump(mode="json")
    elif isinstance(item, dict):
        payload = dict(item)
    else:
        payload = {}
    evidence_refs = list(payload.get("evidence_refs") or [])
    evidence_refs.extend(ref for ref in payload.get("task_book_evidence_refs") or [] if ref not in evidence_refs)
    evidence_refs.extend(ref for ref in payload.get("subject_evidence_refs") or [] if ref not in evidence_refs)
    return {
        "review_item_id": str(
            payload.get("finding_id")
            or payload.get("review_item_id")
            or payload.get("check_item_id")
            or f"{specialist_id}-finding-{index}"
        ),
        "check_item_id": str(payload.get("check_item_id") or ""),
        "item_type": str(payload.get("item_type") or "harness_check_item_review"),
        "severity": str(payload.get("severity") or "info"),
        "judgment": str(payload.get("judgment") or ""),
        "title": str(payload.get("title") or payload.get("check_item_id") or "Harness 检查项审查"),
        "description": str(payload.get("reasoning") or payload.get("description") or ""),
        "recommendation": str(payload.get("recommendation") or ""),
        "agent_id": specialist_id,
        "evidence_refs": evidence_refs,
        "source_evidence_ids": evidence_refs,
        "source_quote": str(payload.get("source_quote") or ""),
        "confidence": payload.get("confidence", 0.0),
        "coverage_status": str(payload.get("coverage_status") or ""),
    }


def _extract_findings(context: dict[str, Any], harness_agent_id: str, specialist_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []
    seen_refs: set[str] = set()

    for index, item in enumerate(context.get("findings") or [], start=1):
        finding = _coerce_harness_finding(item, specialist_id=specialist_id, index=index)
        findings.append(finding)
        for ref in finding.get("evidence_refs") or finding.get("source_evidence_ids") or []:
            ref_id = str(ref)
            if ref_id and ref_id not in seen_refs:
                seen_refs.add(ref_id)
                evidence_refs.append({"evidence_id": ref_id, "source": "harness_finding"})

    for contribution in context.get("coverage_contributions") or []:
        agent_id = getattr(contribution, "agent_id", "") or str((contribution or {}).get("agent_id") or "")
        if agent_id != harness_agent_id:
            continue
        for ref in list(getattr(contribution, "task_book_evidence_refs", []) or []):
            ref_id = str(ref)
            if ref_id and ref_id not in seen_refs:
                seen_refs.add(ref_id)
                evidence_refs.append({"evidence_id": ref_id, "source": "task_book"})
        for ref in list(getattr(contribution, "subject_evidence_refs", []) or []):
            ref_id = str(ref)
            if ref_id and ref_id not in seen_refs:
                seen_refs.add(ref_id)
                evidence_refs.append({"evidence_id": ref_id, "source": "subject"})
        for risk in list(getattr(contribution, "risks", []) or []):
            if not str(risk).strip():
                continue
            findings.append(
                {
                    "review_item_id": f"{specialist_id}-harness-{len(findings) + 1}",
                    "item_type": "harness_coverage_risk",
                    "severity": "major" if "未找到" in str(risk) else "info",
                    "title": "Harness 覆盖审查",
                    "description": str(risk),
                    "agent_id": specialist_id,
                }
            )

    cross_items = list(context.get("cross_document_items") or [])
    if harness_agent_id == "cross_document_consistency_agent" and cross_items:
        for item in cross_items:
            if not isinstance(item, dict):
                continue
            findings.append(
                {
                    "review_item_id": str(item.get("review_item_id") or f"{specialist_id}-cross-{len(findings) + 1}"),
                    "item_type": str(item.get("item_type") or "cross_document"),
                    "severity": str(item.get("severity") or "major"),
                    "title": str(item.get("title") or "跨文档一致性"),
                    "description": str(item.get("description") or ""),
                    "agent_id": specialist_id,
                }
            )
            for ref in list(item.get("source_evidence_ids") or item.get("evidence_refs") or []):
                ref_id = str(ref)
                if ref_id and ref_id not in seen_refs:
                    seen_refs.add(ref_id)
                    evidence_refs.append({"evidence_id": ref_id, "source": "cross_document"})

    return findings, evidence_refs


def _trace_payload(traces: list[AgentRunTrace]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for trace in traces:
        if hasattr(trace, "model_dump"):
            payload.append(trace.model_dump())
        elif isinstance(trace, dict):
            payload.append(trace)
    return payload


def _build_harness_summary(
    *,
    specialist_id: str,
    harness_agent_id: str,
    objective: str,
    findings: list[dict[str, Any]],
    trace_count: int,
    degraded: bool,
    harness_strategy: str = "review_plus_harness",
) -> dict[str, Any]:
    objective_text = objective.strip()
    focus = (
        f"围绕审查目标「{objective_text}」完成 Harness 专家审查。"
        if objective_text
        else "已完成 Harness 专家审查。"
    )
    return {
        "message": focus,
        "review_focus": focus,
        "objective": objective_text,
        "finding_count": len(findings),
        "harness_agent_id": harness_agent_id,
        "harness_trace_count": trace_count,
        "execution_mode": "harness",
        "harness_strategy": harness_strategy,
        "limited": degraded,
        "specialist_id": specialist_id,
    }


def try_run_harness_specialist(
    task: Any,
    specialist_id: str,
    chief_plan: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    """Attempt a single harness specialist run; return (result, warnings, diagnostics)."""
    context = dict(context or {})
    domain_id = str(context.get("domain_id") or "aerospace_review")
    objective = str(context.get("objective") or getattr(task, "scenario", "") or "").strip()
    bootstrap_mode = str(context.get("bootstrap_mode") or "")
    availability = harness_availability_for_specialist(specialist_id, context, domain_id=domain_id)
    harness_strategy = str(availability.get("harness_strategy") or resolve_harness_strategy(specialist_id, domain_id))
    diagnostics: dict[str, Any] = {
        **availability,
        "harness_attempted": False,
        "fallback_reason": "",
        "objective": objective,
        "bootstrap_mode": bootstrap_mode,
        "synthetic_context_used": bootstrap_mode == "smart_synthetic_context",
        "harness_strategy": harness_strategy,
        "domain_id": domain_id,
        "generic_llm_attempted": False,
        "generic_llm_used": False,
    }
    warnings: list[str] = []

    if not availability["harness_available"]:
        reason = str(availability["harness_unavailable_reason"] or "harness_unavailable")
        warning = f"harness_unavailable:{reason}"
        diagnostics["fallback_reason"] = reason
        return None, [warning], diagnostics

    if bootstrap_mode == "smart_synthetic_context":
        _enrich_task_from_context(task, context)

    if harness_strategy == "generic_harness":
        from data_agent.core.agent_profile import profile_for_specialist
        from data_agent.core.generic_harness_runner import (
            EXECUTION_MODE_GENERIC_LLM,
            GenericHarnessError,
            GenericHarnessUnavailable,
            run_generic_specialist_review,
        )

        profile = profile_for_specialist(specialist_id, domain_id=domain_id).to_dict()
        diagnostics["generic_llm_attempted"] = True
        diagnostics["harness_attempted"] = True
        try:
            generic_result = run_generic_specialist_review(specialist_id, profile, context)
            diagnostics["generic_llm_used"] = True
            diagnostics["fallback_reason"] = ""
            agent_entry = next(
                (
                    item
                    for item in chief_plan.get("selected_agents") or []
                    if isinstance(item, dict) and str(item.get("agent_id") or "") == specialist_id
                ),
                {},
            )
            if not generic_result.get("agent_name"):
                generic_result["agent_name"] = str(
                    agent_entry.get("agent_name") or profile.get("display_name") or specialist_id
                )
            if not generic_result.get("role"):
                generic_result["role"] = str(agent_entry.get("role") or "")
            generic_result["execution_mode"] = EXECUTION_MODE_GENERIC_LLM
            generic_result["harness_strategy"] = harness_strategy
            return generic_result, warnings, diagnostics
        except GenericHarnessUnavailable as exc:
            reason = f"generic_llm_unavailable:{exc.reason}"
            warnings.append(reason)
            diagnostics["fallback_reason"] = reason
        except GenericHarnessError as exc:
            reason = f"generic_llm_failed:{exc.reason}"
            warnings.append(reason)
            diagnostics["fallback_reason"] = reason
        except Exception as exc:
            reason = f"generic_llm_failed:{exc.__class__.__name__}"
            warnings.append(reason)
            diagnostics["fallback_reason"] = reason

    harness_agent_id = str(availability["harness_agent_id"])
    harness = ReviewPlusAgentHarness()
    run_context: dict[str, Any] = {"task": task}
    traces: list[AgentRunTrace] = []
    diagnostics["harness_attempted"] = True

    try:
        _enrich_task_from_context(task, context)
        setattr(task, "chief_review_plan", chief_plan)
        harness._run_agent("material_package_agent", harness._material_package_agent, run_context, traces)
        run_context["material_roles"] = list(run_context.get("material_roles") or [])

        prep_agents = ["checklist_agent", "task_book_agent", "subject_report_agent"]
        if harness_agent_id == "cross_document_consistency_agent":
            prep_agents = ["checklist_agent", "task_book_agent", "subject_report_agent"]
        elif harness_agent_id in prep_agents:
            prep_agents = [agent_id for agent_id in prep_agents if agent_id != harness_agent_id]

        for prep_id in prep_agents:
            harness._run_agent(prep_id, harness._specialist_runner(prep_id), run_context, traces)

        run_context["harness_plan"] = ReviewPlusHarnessPlan(
            selected_agent_ids=[harness_agent_id],
            required_agent_ids=[harness_agent_id],
            matched_signals={harness_agent_id: _matched_signals(chief_plan, specialist_id)},
        )
        harness._run_agent(
            harness_agent_id,
            harness._specialist_runner(harness_agent_id),
            run_context,
            traces,
        )
        if hasattr(harness, "_coverage_matrix_builder_agent") and hasattr(harness, "_review_plus_arbiter_agent"):
            harness._run_agent(
                "coverage_matrix_builder_agent",
                harness._coverage_matrix_builder_agent,
                run_context,
                traces,
            )
            harness._run_agent(
                "review_plus_arbiter_agent",
                harness._review_plus_arbiter_agent,
                run_context,
                traces,
            )

        findings, evidence_refs = _extract_findings(run_context, harness_agent_id, specialist_id)
        agent_entry = next(
            (
                item
                for item in chief_plan.get("selected_agents") or []
                if isinstance(item, dict) and str(item.get("agent_id") or "") == specialist_id
            ),
            {},
        )
        degraded = not bool(evidence_refs)
        summary = _build_harness_summary(
            specialist_id=specialist_id,
            harness_agent_id=harness_agent_id,
            objective=objective,
            findings=findings,
            trace_count=len(traces),
            degraded=degraded,
            harness_strategy=harness_strategy,
        )
        summary["harness_strategy"] = harness_strategy
        return {
            "agent_id": specialist_id,
            "agent_name": str(agent_entry.get("agent_name") or specialist_id),
            "role": str(agent_entry.get("role") or ""),
            "status": "completed",
            "findings": findings,
            "summary": summary,
            "evidence_refs": evidence_refs,
            "citations": evidence_refs,
            "harness_agent_id": harness_agent_id,
            "harness_strategy": harness_strategy,
            "harness_trace_count": len(traces),
            "agent_trace": _trace_payload(traces),
            "objective": objective,
        }, warnings, diagnostics
    except ReviewPlusAgentHarnessError as exc:
        reason = f"harness_failed:{exc.error_code or 'agent_failed'}"
        if diagnostics.get("synthetic_context_used"):
            reason = f"{reason};synthetic_context_attempted"
        diagnostics["fallback_reason"] = reason
        return None, [*warnings, reason], diagnostics
    except Exception as exc:
        reason = f"harness_failed:{exc.__class__.__name__}"
        if diagnostics.get("synthetic_context_used"):
            reason = f"{reason};synthetic_context_attempted"
        diagnostics["fallback_reason"] = reason
        return None, [*warnings, reason], diagnostics


__all__ = [
    "harness_availability_for_specialist",
    "resolve_harness_strategy",
    "try_run_harness_specialist",
]
