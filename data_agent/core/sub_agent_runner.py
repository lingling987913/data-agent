"""Execute individual SMART committee specialist subtasks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from data_agent.core.agent_profile import profile_for_specialist
from data_agent.core.harness_specialist_adapter import (
    harness_availability_for_specialist,
    resolve_harness_strategy,
    try_run_harness_specialist,
)
from data_agent.core.task_board import TaskBoard, TaskItem, compute_replan_assessment, smart_task_board_summary
from data_agent.core.task_spec import KIND_ARBITER_SUMMARY, KIND_FORMAT_GATE, KIND_SMART_SPECIALIST_REVIEW


def _context_has_materials(context: dict[str, Any]) -> bool:
    materials = context.get("materials") or []
    if not materials:
        return False
    for item in materials:
        if isinstance(item, dict) and str(item.get("content") or "").strip():
            return True
    return False


def _build_task_namespace(context: dict[str, Any]) -> Any:
    materials = context.get("materials") or []
    return SimpleNamespace(
        materials=[
            SimpleNamespace(
                name=str(item.get("name") or ""),
                content=str(item.get("content") or ""),
                role=str(item.get("role") or "unknown"),
                included_in_formal_review=True,
            )
            for item in materials
            if isinstance(item, dict)
        ],
        section_tree=dict(context.get("section_tree") or {}),
        evidence_pool=dict(context.get("evidence_pool") or {}),
        document_format_review=dict(context.get("document_format_review") or {}),
        check_items=list(context.get("check_items") or context.get("synthetic_check_items") or []),
        traceability_result=dict(context.get("traceability_result") or {}),
        cross_document_review_items=list(context.get("cross_document_review_items") or []),
        scenario=str(context.get("objective") or ""),
    )


def _chief_plan_for_specialist(chief_plan: dict[str, Any], specialist_id: str) -> dict[str, Any]:
    selected = [
        item
        for item in chief_plan.get("selected_agents") or []
        if isinstance(item, dict) and str(item.get("agent_id") or "") == specialist_id
    ]
    if not selected:
        selected = [{"agent_id": specialist_id, "agent_name": specialist_id}]
    return {
        **chief_plan,
        "selected_agents": selected,
    }


def _apply_objective_to_review(
    review: dict[str, Any],
    *,
    specialist_id: str,
    objective: str,
    execution_mode: str,
    profile: dict[str, Any],
) -> None:
    objective_text = str(objective or "").strip()
    if not objective_text:
        return

    summary_payload = review.get("summary")
    summary = dict(summary_payload) if isinstance(summary_payload, dict) else {}
    mode_label = {
        "harness": "Harness 专家审查",
        "generic_llm_harness": "LLM Harness 专家审查",
    }.get(execution_mode, "确定性预审")
    specialist_name = str(review.get("agent_name") or profile.get("display_name") or specialist_id)
    focus = f"围绕审查目标「{objective_text}」执行 {specialist_name} {mode_label}。"
    summary.setdefault("objective", objective_text)
    summary.setdefault("review_focus", focus)
    if not str(summary.get("message") or "").strip():
        finding_count = len(review.get("findings") or [])
        summary["message"] = (
            f"已针对审查目标「{objective_text}」完成 {specialist_name} {mode_label}，"
            f"共 {finding_count} 条发现。"
        )
    review["summary"] = summary

    for finding in review.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        if finding.get("item_type") in {"specialist_assignment", "check_item_coverage"}:
            description = str(finding.get("description") or "")
            if objective_text not in description:
                finding["description"] = f"围绕审查目标「{objective_text}」：{description}" if description else focus
        rationale = str(finding.get("rationale") or finding.get("reasoning") or "")
        if rationale and objective_text not in rationale:
            finding["rationale"] = f"{rationale}（审查目标：{objective_text}）"


def _run_deterministic_review(task_ns: Any, chief_plan: dict[str, Any], specialist_id: str) -> dict[str, Any]:
    from data_agent.review_plus.specialist_orchestration_service import run_specialist_reviews

    scoped_plan = _chief_plan_for_specialist(chief_plan, specialist_id)
    reviews = run_specialist_reviews(task_ns, scoped_plan)
    if not reviews:
        return {
            "specialist_id": specialist_id,
            "status": "failed",
            "findings": [],
            "summary": {"message": f"专家 {specialist_id} 未返回审查结果。"},
            "citations": [],
            "evidence_refs": [],
            "warnings": ["empty_review"],
        }

    review = reviews[0]
    if str(review.get("agent_id") or "") != specialist_id:
        for item in reviews:
            if str(item.get("agent_id") or "") == specialist_id:
                review = item
                break
    return review


def _resolve_fallback_reason(harness_warnings: list[str], harness_diagnostics: dict[str, Any]) -> str:
    explicit = str(harness_diagnostics.get("fallback_reason") or "").strip()
    if explicit:
        return explicit
    for warning in harness_warnings:
        text = str(warning)
        if text.startswith("harness_unavailable:"):
            return text.removeprefix("harness_unavailable:")
        if text.startswith("harness_failed:"):
            return text
    return ""


def _normalize_review(
    review: dict[str, Any],
    specialist_id: str,
    *,
    execution_mode: str,
    profile: dict[str, Any],
    limited: bool,
    objective: str = "",
    harness_diagnostics: dict[str, Any] | None = None,
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    _apply_objective_to_review(
        review,
        specialist_id=specialist_id,
        objective=objective,
        execution_mode=execution_mode,
        profile=profile,
    )

    findings = list(review.get("findings") or [])
    summary_payload = review.get("summary")
    if isinstance(summary_payload, dict):
        summary = dict(summary_payload)
    else:
        summary = {
            "finding_count": len(findings),
            "assignment_reason": str(review.get("assignment_reason") or ""),
        }
    bootstrap_mode = str((harness_diagnostics or {}).get("bootstrap_mode") or "")
    harness_meta = dict(harness_diagnostics or {})
    harness_strategy = str(
        harness_meta.get("harness_strategy")
        or review.get("harness_strategy")
        or resolve_harness_strategy(specialist_id, str(profile.get("domain_id") or "aerospace_review"))
    )
    summary["execution_mode"] = execution_mode
    summary["limited"] = limited
    summary["profile"] = profile
    summary["harness_strategy"] = harness_strategy
    if bootstrap_mode:
        summary["bootstrap_mode"] = bootstrap_mode
    if objective:
        summary.setdefault("objective", objective)

    warnings = list(extra_warnings or [])
    if execution_mode == "deterministic_pre_review":
        warnings.append("execution_mode=deterministic_pre_review")
    if limited:
        warnings.append("limited=true")
    if bootstrap_mode:
        warnings.append(f"bootstrap_mode={bootstrap_mode}")

    fallback_reason = _resolve_fallback_reason(warnings, harness_meta)
    if not fallback_reason:
        unavailable = str(harness_meta.get("harness_unavailable_reason") or "").strip()
        if unavailable and not harness_meta.get("harness_attempted"):
            fallback_reason = unavailable
    evidence_refs = list(review.get("evidence_refs") or review.get("citations") or [])
    return {
        "specialist_id": specialist_id,
        "status": str(review.get("status") or "completed"),
        "findings": findings,
        "summary": summary,
        "citations": list(review.get("citations") or evidence_refs),
        "evidence_refs": evidence_refs,
        "warnings": warnings,
        "agent_name": str(review.get("agent_name") or profile.get("display_name") or ""),
        "role": str(review.get("role") or ""),
        "execution_mode": execution_mode,
        "profile": profile,
        "limited": limited,
        "objective": objective,
        "fallback_reason": fallback_reason,
        "harness_available": bool(harness_meta.get("harness_available")),
        "harness_attempted": bool(harness_meta.get("harness_attempted")),
        "harness_unavailable_reason": str(harness_meta.get("harness_unavailable_reason") or ""),
        "harness_agent_id": str(harness_meta.get("harness_agent_id") or review.get("harness_agent_id") or ""),
        "harness_strategy": harness_strategy,
        "agent_trace": list(review.get("agent_trace") or []),
        "bootstrap_mode": bootstrap_mode,
    }


class SubAgentRunner:
    """Run a single specialist subtask with harness-first execution and deterministic fallback."""

    def run_specialist_task(self, task: TaskItem, context: dict[str, Any]) -> dict[str, Any]:
        if task.kind == KIND_ARBITER_SUMMARY:
            board = context.get("task_board")
            if isinstance(board, TaskBoard):
                return self.run_arbiter_summary(task, board, context)
            return self.run_arbiter_summary(task, TaskBoard(board_id="inline", tasks=[]), context)

        specialist_id = task.specialist_id or task.agent_id
        chief_plan = context.get("chief_plan")
        corpus_text = str(context.get("corpus_text") or "").strip()
        objective = str(context.get("objective") or "").strip()
        domain_id = str(context.get("domain_id") or "aerospace_review")
        profile = profile_for_specialist(specialist_id, domain_id=domain_id).to_dict()
        harness_diagnostics = harness_availability_for_specialist(
            specialist_id,
            context,
            domain_id=domain_id,
        )
        harness_diagnostics["objective"] = objective
        harness_diagnostics["bootstrap_mode"] = str(context.get("bootstrap_mode") or "")
        harness_diagnostics["domain_id"] = domain_id
        harness_strategy = str(harness_diagnostics.get("harness_strategy") or resolve_harness_strategy(specialist_id, domain_id))

        if not isinstance(chief_plan, dict) or not chief_plan.get("selected_agents"):
            return {
                "specialist_id": specialist_id,
                "status": "blocked",
                "findings": [],
                "summary": {
                    "message": "缺少 chief_review_plan，无法执行专家子任务。",
                    "execution_mode": "blocked",
                    "limited": True,
                    "profile": profile,
                    "objective": objective,
                    "harness_strategy": harness_strategy,
                },
                "citations": [],
                "evidence_refs": [],
                "warnings": ["missing_chief_plan"],
                "execution_mode": "blocked",
                "profile": profile,
                "limited": True,
                "objective": objective,
                "fallback_reason": "missing_chief_plan",
                "harness_available": bool(harness_diagnostics.get("harness_available")),
                "harness_attempted": False,
                "harness_unavailable_reason": str(harness_diagnostics.get("harness_unavailable_reason") or ""),
                "harness_strategy": harness_strategy,
            }

        if not _context_has_materials(context) and not corpus_text:
            return {
                "specialist_id": specialist_id,
                "status": "blocked",
                "findings": [],
                "summary": {
                    "message": "缺少可审查材料或语料，专家子任务被阻塞。",
                    "execution_mode": "blocked",
                    "limited": True,
                    "profile": profile,
                    "objective": objective,
                    "harness_strategy": harness_strategy,
                },
                "citations": [],
                "evidence_refs": [],
                "warnings": ["empty_context"],
                "execution_mode": "blocked",
                "profile": profile,
                "limited": True,
                "objective": objective,
                "fallback_reason": "missing_context",
                "harness_available": bool(harness_diagnostics.get("harness_available")),
                "harness_attempted": False,
                "harness_unavailable_reason": "missing_context",
                "harness_strategy": harness_strategy,
            }

        task_ns = _build_task_namespace(context)
        harness_warnings: list[str] = []
        execution_mode = "deterministic_pre_review"
        limited = True
        review: dict[str, Any] | None = None

        if profile.get("preferred_execution") == "harness":
            harness_review, harness_warnings, harness_diagnostics = try_run_harness_specialist(
                task_ns,
                specialist_id,
                chief_plan,
                context=context,
            )
            if harness_review is not None:
                review = harness_review
                execution_mode = str(
                    review.get("execution_mode")
                    or (review.get("summary") or {}).get("execution_mode")
                    or "harness"
                )
                limited = not bool(review.get("evidence_refs") or review.get("citations"))
                if review.get("limited") is True:
                    limited = True

        if review is None:
            review = _run_deterministic_review(task_ns, chief_plan, specialist_id)
            if review.get("status") == "failed":
                return _normalize_review(
                    review,
                    specialist_id,
                    execution_mode="deterministic_pre_review",
                    profile=profile,
                    limited=True,
                    objective=objective,
                    harness_diagnostics=harness_diagnostics,
                    extra_warnings=[*harness_warnings, *list(review.get("warnings") or [])],
                )

        return _normalize_review(
            review,
            specialist_id,
            execution_mode=execution_mode,
            profile=profile,
            limited=limited if execution_mode in {"harness", "generic_llm_harness"} else True,
            objective=objective,
            harness_diagnostics=harness_diagnostics,
            extra_warnings=harness_warnings,
        )

    def run_arbiter_summary(
        self,
        task: TaskItem,
        board: TaskBoard,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Lightweight arbiter: aggregate specialist outputs without harness."""
        specialist_outputs: list[dict[str, Any]] = []
        finding_counts: list[int] = []
        limited_upstream = False
        failed_or_blocked = 0
        skipped = 0

        for board_task in board.tasks:
            if board_task.kind not in {KIND_SMART_SPECIALIST_REVIEW, KIND_FORMAT_GATE}:
                continue
            if board_task.kind == KIND_FORMAT_GATE and board_task.task_id == task.task_id:
                continue
            if board_task.status == "skipped":
                skipped += 1
                continue
            if board_task.status in {"failed", "blocked"}:
                failed_or_blocked += 1
                continue
            if board_task.status != "completed":
                continue

            output = board_task.output_summary or {}
            review = output.get("review") if isinstance(output.get("review"), dict) else output
            if not review:
                continue
            specialist_outputs.append(review)
            finding_counts.append(len(review.get("findings") or []))
            if output.get("limited") is True or review.get("limited") is True:
                limited_upstream = True

        conflict_count = 0
        if len(set(finding_counts)) > 1:
            conflict_count += 1
        conflict_count += failed_or_blocked
        if skipped:
            conflict_count += 1

        completed_names = [
            str(item.get("agent_name") or item.get("agent_id") or "")
            for item in specialist_outputs
        ]
        objective = str(context.get("objective") or task.input_summary.get("objective") or "")
        if specialist_outputs:
            total_findings = sum(finding_counts)
            consensus_summary = (
                f"已完成 {len(specialist_outputs)} 位专家审查，共 {total_findings} 条发现。"
            )
            if objective:
                consensus_summary = f"围绕「{objective}」：{consensus_summary}"
        elif failed_or_blocked or skipped:
            consensus_summary = "委员会审查未完整完成，存在失败/阻塞/跳过的专家任务。"
        else:
            consensus_summary = "暂无已完成专家输出可供汇总。"

        recommendations: list[str] = []
        if limited_upstream:
            recommendations.append("部分专家以确定性预审或受限模式执行，建议补充材料后启用 Harness。")
        if failed_or_blocked:
            recommendations.append("修复失败/阻塞任务后重新执行委员会审查。")
        if skipped:
            recommendations.append("格式门禁未通过导致下游跳过，请先修复文档格式/解析质量。")
        if conflict_count > 0 and len(set(finding_counts)) > 1:
            recommendations.append("专家发现数量存在差异，建议人工复核冲突项。")
        if not recommendations:
            recommendations.append("当前专家结论基本一致，可进入人工确认或报告生成。")

        board_summary = smart_task_board_summary(board)
        replan = compute_replan_assessment(
            specialist_outputs,
            board_summary,
            specialist_task_count=sum(
                1 for item in board.tasks if item.kind == KIND_SMART_SPECIALIST_REVIEW
            ),
        )

        return {
            "status": "completed",
            "consensus_summary": consensus_summary,
            "conflict_count": conflict_count,
            "final_recommendations": recommendations,
            "specialist_count": len(specialist_outputs),
            "specialist_ids": completed_names,
            "limited": limited_upstream or bool(replan.get("needs_replan")),
            "needs_replan": bool(replan.get("needs_replan")),
            "recommended_replan_actions": list(replan.get("recommended_replan_actions") or []),
            "citation_coverage": replan.get("citation_coverage"),
        }


__all__ = ["SubAgentRunner"]
