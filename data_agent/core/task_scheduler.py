"""In-run TaskBoard scheduler: DAG order, optional parallelism, gate propagation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from data_agent.core.task_board import (
    TaskBoard,
    TaskItem,
    arbiter_output_from_board,
    compute_replan_assessment,
    is_gate_task,
    propagate_gate_blocks,
    resolved_task_ids,
    smart_task_board_summary,
    specialist_reviews_from_task_board,
    specialist_task_count_on_board,
)
from data_agent.core.task_spec import KIND_ARBITER_SUMMARY, KIND_FORMAT_GATE, KIND_SMART_SPECIALIST_REVIEW

CheckpointCallback = Callable[[TaskBoard, TaskItem | None, str], None]
TaskRunner = Callable[[TaskItem], dict[str, Any]]

_REPLAN_ACTION_LABELS: dict[str, str] = {
    "enable_harness": "启用 Harness 专家审查以替代确定性预审",
    "upload_checklist": "补充上传检查单以提升引用覆盖率",
    "upload_task_book": "补充上传任务书以提升证据覆盖",
    "rerun_with_force_refresh": "使用 force_refresh 重新执行委员会审查",
    "add_domain_specialist": "根据领域注册表追加相关专家",
}


@dataclass
class SchedulerResult:
    board: TaskBoard
    summary: dict[str, Any] = field(default_factory=dict)
    arbiter_summary: dict[str, Any] | None = None
    replan_suggestions: list[str] = field(default_factory=list)
    followup_task_specs: list[dict[str, Any]] = field(default_factory=list)


def _task_priority(task: TaskItem) -> int:
    if task.priority is not None:
        return int(task.priority)
    raw = task.input_summary.get("priority")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    if task.kind == KIND_ARBITER_SUMMARY:
        return 100
    return 50


def ready_tasks_sorted(board: TaskBoard) -> list[TaskItem]:
    """Return runnable tasks whose dependencies are resolved, sorted by priority."""
    resolved = resolved_task_ids(board)
    ready: list[TaskItem] = []
    for task in board.tasks:
        if task.status not in {"pending", "ready"}:
            continue
        if task.status == "pending":
            if all(dep in resolved for dep in task.depends_on):
                task.status = "ready"
        if task.status != "ready":
            continue
        if not all(dep in resolved for dep in task.depends_on):
            continue
        ready.append(task)
    ready.sort(key=lambda item: (_task_priority(item), item.task_id))
    return ready


def _wrap_specialist_review(task: TaskItem, result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("review"), dict):
        return result
    if task.kind not in {KIND_SMART_SPECIALIST_REVIEW, KIND_FORMAT_GATE}:
        return result
    review_record = {
        "agent_id": task.specialist_id,
        "agent_name": result.get("agent_name") or task.title,
        "role": result.get("role") or "",
        "status": result.get("status") or "completed",
        "findings": list(result.get("findings") or []),
        "finding_count": len(result.get("findings") or []),
        "summary": dict(result.get("summary") or {}),
        "warnings": list(result.get("warnings") or []),
        "execution_mode": result.get("execution_mode")
        or (result.get("summary") or {}).get("execution_mode"),
        "profile": dict(result.get("profile") or task.input_summary.get("profile") or {}),
        "limited": bool(result.get("limited")),
        "evidence_refs": list(result.get("evidence_refs") or result.get("citations") or []),
        "citations": list(result.get("citations") or result.get("evidence_refs") or []),
        "objective": str(result.get("objective") or ""),
        "fallback_reason": str(result.get("fallback_reason") or ""),
        "harness_available": bool(result.get("harness_available")),
        "harness_attempted": bool(result.get("harness_attempted")),
        "harness_unavailable_reason": str(result.get("harness_unavailable_reason") or ""),
        "harness_agent_id": str(result.get("harness_agent_id") or ""),
        "agent_trace": list(result.get("agent_trace") or []),
    }
    return {
        **result,
        "review": review_record,
        "finding_count": review_record["finding_count"],
    }


def generate_replan_suggestions(
    board: TaskBoard,
    *,
    citation_threshold: float = 0.5,
) -> tuple[list[str], dict[str, Any], list[dict[str, Any]]]:
    """Build human-readable replan suggestions from board quality metrics."""
    board_summary = smart_task_board_summary(board)
    specialist_reviews = specialist_reviews_from_task_board(board)
    assessment = compute_replan_assessment(
        specialist_reviews,
        board_summary,
        specialist_task_count=specialist_task_count_on_board(board),
    )

    suggestions: list[str] = []
    for action in assessment.get("recommended_replan_actions") or []:
        label = _REPLAN_ACTION_LABELS.get(str(action), str(action))
        if label not in suggestions:
            suggestions.append(label)

    citation_coverage = float(assessment.get("citation_coverage") or 0.0)
    if citation_coverage < citation_threshold:
        pct = int(citation_coverage * 100)
        suggestions.append(f"引用覆盖率 {pct}% 低于阈值 {int(citation_threshold * 100)}%，建议补充证据材料")

    failed = int(board_summary.get("failed") or 0)
    blocked = int(board_summary.get("blocked") or 0)
    skipped = int((board_summary.get("status_counts") or {}).get("skipped") or 0)
    if failed:
        suggestions.append(f"存在 {failed} 个失败任务，建议排查专家配置或材料完整性")
    if blocked:
        suggestions.append(f"存在 {blocked} 个阻塞任务，建议补充检查单/任务书或修复格式门禁")
    if skipped:
        suggestions.append(f"存在 {skipped} 个被跳过的下游任务，建议修复格式门禁或重新规划 DAG")

    followup_specs: list[dict[str, Any]] = []
    if assessment.get("needs_replan") and citation_coverage < citation_threshold:
        followup_specs.append(
            {
                "task_id": "followup:evidence_review",
                "kind": KIND_SMART_SPECIALIST_REVIEW,
                "agent_id": "requirements_traceability_reviewer",
                "specialist_id": "requirements_traceability_reviewer",
                "title": "补证据跟踪审查（follow-up）",
                "depends_on": [],
                "input_summary": {"followup": True, "reason": "low_citation_coverage"},
                "execute_by_default": False,
            }
        )

    return suggestions, assessment, followup_specs


def _apply_task_result(task: TaskItem, result: dict[str, Any]) -> None:
    result = _wrap_specialist_review(task, result)
    task_status = str(result.get("status") or "completed")
    if task.kind == KIND_ARBITER_SUMMARY:
        task.output_summary = {
            **dict(result),
            "status": task_status,
        }
        if task_status in {"failed", "blocked"}:
            task.status = task_status
            task.error = str(result.get("message") or result.get("error") or task_status)
        else:
            task.status = "completed"
        return

    review_record = result.get("review")
    if isinstance(review_record, dict):
        task.output_summary = {
            "review": review_record,
            "finding_count": int(result.get("finding_count") or len(review_record.get("findings") or [])),
            "status": task_status,
            "execution_mode": result.get("execution_mode") or review_record.get("execution_mode"),
            "profile": dict(result.get("profile") or review_record.get("profile") or {}),
            "limited": bool(result.get("limited")),
            "objective": str(result.get("objective") or ""),
            "fallback_reason": str(result.get("fallback_reason") or ""),
            "harness_available": bool(result.get("harness_available")),
            "harness_attempted": bool(result.get("harness_attempted")),
            "harness_unavailable_reason": str(result.get("harness_unavailable_reason") or ""),
        }
    else:
        task.output_summary = {
            **dict(result),
            "status": task_status,
        }

    if task_status == "blocked":
        task.status = "blocked"
        task.error = str((result.get("summary") or {}).get("message") or result.get("message") or "blocked")
    elif task_status == "failed":
        task.status = "failed"
        task.error = str((result.get("summary") or {}).get("message") or result.get("message") or "failed")
    else:
        task.status = "completed"


def _gate_limited_warnings(board: TaskBoard, task: TaskItem) -> list[str]:
    warnings: list[str] = []
    by_id = {item.task_id: item for item in board.tasks}
    for dep_id in task.depends_on:
        dep = by_id.get(dep_id)
        if dep and is_gate_task(dep) and dep.status == "completed":
            if dep.output_summary.get("limited") is True:
                warnings.append(f"gate_limited:{dep.task_id}")
    return warnings


def run_task_board(
    board: TaskBoard,
    runner: TaskRunner,
    context: dict[str, Any],
    *,
    max_parallel: int = 1,
    allow_replan: bool = False,
    checkpoint: CheckpointCallback | None = None,
) -> SchedulerResult:
    """Execute TaskBoard tasks in DAG order until no runnable tasks remain."""
    del context  # reserved for future scheduler context hooks
    max_workers = max(1, int(max_parallel or 1))

    while True:
        propagate_gate_blocks(board)
        batch = ready_tasks_sorted(board)
        if not batch:
            break

        if checkpoint:
            checkpoint(board, None, "batch_start")

        if max_workers == 1:
            for task in batch:
                if checkpoint:
                    checkpoint(board, task, "before")
                task.status = "in_progress"
                gate_warnings = _gate_limited_warnings(board, task)
                if gate_warnings:
                    task.input_summary.setdefault("gate_warnings", gate_warnings)
                try:
                    result = runner(task)
                except Exception as exc:
                    result = {
                        "status": "failed",
                        "message": str(exc),
                        "summary": {"message": str(exc)},
                    }
                _apply_task_result(task, result)
                propagate_gate_blocks(board)
                if checkpoint:
                    checkpoint(board, task, "after")
        else:
            running: dict[str, TaskItem] = {}

            def _execute(item: TaskItem) -> tuple[str, dict[str, Any]]:
                gate_warnings = _gate_limited_warnings(board, item)
                if gate_warnings:
                    item.input_summary.setdefault("gate_warnings", gate_warnings)
                return item.task_id, runner(item)

            with ThreadPoolExecutor(max_workers=min(max_workers, len(batch))) as pool:
                for task in batch:
                    task.status = "in_progress"
                    running[task.task_id] = task
                futures = {pool.submit(_execute, task): task for task in batch}
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        _task_id, result = future.result()
                    except Exception as exc:
                        result = {
                            "status": "failed",
                            "message": str(exc),
                            "summary": {"message": str(exc)},
                        }
                    _apply_task_result(task, result)
                    if checkpoint:
                        checkpoint(board, task, "after")

            propagate_gate_blocks(board)
            if checkpoint:
                checkpoint(board, None, "batch_end")

    propagate_gate_blocks(board)
    summary = smart_task_board_summary(board)
    summary["skipped"] = int((summary.get("status_counts") or {}).get("skipped") or 0)
    arbiter_summary = arbiter_output_from_board(board)
    replan_suggestions, replan_assessment, followup_specs = generate_replan_suggestions(board)
    if arbiter_summary is None and replan_assessment.get("needs_replan"):
        summary["needs_replan"] = True
    elif isinstance(arbiter_summary, dict) and arbiter_summary.get("needs_replan") is not None:
        summary["needs_replan"] = bool(arbiter_summary.get("needs_replan"))

    return SchedulerResult(
        board=board,
        summary=summary,
        arbiter_summary=arbiter_summary,
        replan_suggestions=replan_suggestions if replan_assessment.get("needs_replan") else [],
        followup_task_specs=followup_specs if allow_replan and replan_assessment.get("needs_replan") else [],
    )


class TaskScheduler:
    """Thin wrapper around run_task_board for dependency injection in tests."""

    def __init__(self, *, max_parallel: int = 1):
        self.max_parallel = max(1, int(max_parallel or 1))

    def run(
        self,
        board: TaskBoard,
        runner: TaskRunner,
        context: dict[str, Any],
        *,
        allow_replan: bool = False,
        checkpoint: CheckpointCallback | None = None,
    ) -> SchedulerResult:
        return run_task_board(
            board,
            runner,
            context,
            max_parallel=self.max_parallel,
            allow_replan=allow_replan,
            checkpoint=checkpoint,
        )


__all__ = [
    "SchedulerResult",
    "TaskScheduler",
    "generate_replan_suggestions",
    "ready_tasks_sorted",
    "run_task_board",
]
