"""Lightweight task board for SMART committee specialist subtasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data_agent.core.task_spec import (
    KIND_ARBITER_SUMMARY,
    KIND_FORMAT_GATE,
    KIND_SMART_SPECIALIST_REVIEW,
    TaskSpec,
    task_spec_from_dict,
)

TASK_STATUSES = frozenset({
    "pending",
    "ready",
    "in_progress",
    "completed",
    "failed",
    "blocked",
    "skipped",
})

SMART_SPECIALIST_KIND = "smart_specialist_review"


def smart_specialist_task_id(specialist_id: str) -> str:
    return f"smart_specialist:{specialist_id}"


@dataclass
class TaskItem:
    task_id: str
    kind: str
    agent_id: str
    specialist_id: str
    title: str
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    priority: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task_id": self.task_id,
            "kind": self.kind,
            "agent_id": self.agent_id,
            "specialist_id": self.specialist_id,
            "title": self.title,
            "status": self.status,
            "depends_on": list(self.depends_on),
            "input_summary": dict(self.input_summary),
            "output_summary": dict(self.output_summary),
            "error": self.error,
        }
        if self.priority is not None:
            payload["priority"] = self.priority
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TaskItem:
        priority = payload.get("priority")
        return cls(
            task_id=str(payload.get("task_id") or ""),
            kind=str(payload.get("kind") or SMART_SPECIALIST_KIND),
            agent_id=str(payload.get("agent_id") or payload.get("specialist_id") or ""),
            specialist_id=str(payload.get("specialist_id") or payload.get("agent_id") or ""),
            title=str(payload.get("title") or ""),
            status=str(payload.get("status") or "pending"),
            depends_on=[str(item) for item in payload.get("depends_on") or []],
            input_summary=dict(payload.get("input_summary") or {}),
            output_summary=dict(payload.get("output_summary") or {}),
            error=str(payload.get("error") or ""),
            priority=int(priority) if priority is not None else None,
        )


@dataclass
class TaskBoard:
    board_id: str
    kind: str = "smart_committee"
    tasks: list[TaskItem] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_id": self.board_id,
            "kind": self.kind,
            "tasks": [task.to_dict() for task in self.tasks],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> TaskBoard | None:
        if not isinstance(payload, dict):
            return None
        tasks_raw = payload.get("tasks") or []
        tasks = [TaskItem.from_dict(item) for item in tasks_raw if isinstance(item, dict)]
        return cls(
            board_id=str(payload.get("board_id") or "smart_committee"),
            kind=str(payload.get("kind") or "smart_committee"),
            tasks=tasks,
            metadata=dict(payload.get("metadata") or {}),
        )

    def task_by_id(self, task_id: str) -> TaskItem | None:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def completed_task_ids(self) -> set[str]:
        return {task.task_id for task in self.tasks if task.status == "completed"}

    def resolved_task_ids(self) -> set[str]:
        return resolved_task_ids(self)

    def ready_tasks(self) -> list[TaskItem]:
        completed = self.completed_task_ids()
        ready: list[TaskItem] = []
        for task in self.tasks:
            if task.status not in {"ready", "pending", "failed"}:
                continue
            if task.status == "pending":
                if all(dep in completed for dep in task.depends_on):
                    task.status = "ready"
            if task.status in {"ready", "failed"}:
                if all(dep in completed for dep in task.depends_on):
                    ready.append(task)
        return ready

    def summary(self) -> dict[str, Any]:
        return smart_task_board_summary(self)


def _task_limited(task: TaskItem) -> bool:
    output = task.output_summary or {}
    review = output.get("review") if isinstance(output.get("review"), dict) else {}
    if output.get("limited") is True or review.get("limited") is True:
        return True
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    if summary.get("limited") is True:
        return True
    execution_mode = (
        output.get("execution_mode")
        or review.get("execution_mode")
        or summary.get("execution_mode")
        or ""
    )
    return execution_mode in {"deterministic_pre_review", "blocked"}


def completed_task_ids(board: TaskBoard) -> set[str]:
    return board.completed_task_ids()


def resolved_task_ids(board: TaskBoard) -> set[str]:
    return {
        task.task_id
        for task in board.tasks
        if task.status in {"completed", "failed", "blocked", "skipped"}
    }


def is_gate_task(task: TaskItem) -> bool:
    if task.kind == KIND_FORMAT_GATE:
        return True
    return bool(task.input_summary.get("gate"))


def _gate_block_reason(task: TaskItem) -> str:
    message = str(task.error or "").strip()
    if not message:
        output = task.output_summary or {}
        review = output.get("review") if isinstance(output.get("review"), dict) else {}
        summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
        message = str(summary.get("message") or output.get("message") or "").strip()
    if message:
        return message
    return "格式门禁未通过，下游专家任务已跳过。"


def propagate_gate_blocks(board: TaskBoard) -> int:
    """Skip downstream tasks when a format gate failed/blocked. Returns tasks updated."""
    task_by_id = {task.task_id: task for task in board.tasks}
    blocked_gates = {
        task.task_id: _gate_block_reason(task)
        for task in board.tasks
        if is_gate_task(task) and task.status in {"failed", "blocked"}
    }
    if not blocked_gates:
        return 0

    updated = 0
    changed = True
    while changed:
        changed = False
        for task in board.tasks:
            if task.status not in {"pending", "ready"}:
                continue
            if is_gate_task(task) or task.kind == KIND_ARBITER_SUMMARY:
                continue
            blocking_gate = ""
            for dep_id in task.depends_on:
                dep = task_by_id.get(dep_id)
                if dep and is_gate_task(dep) and dep.status in {"failed", "blocked"}:
                    blocking_gate = dep.task_id
                    break
                if dep and dep.status == "skipped":
                    blocked_by = str((dep.output_summary or {}).get("blocked_by") or "")
                    if blocked_by:
                        blocking_gate = blocked_by
                        break
            if not blocking_gate:
                continue
            reason = blocked_gates.get(blocking_gate) or _gate_block_reason(task_by_id[blocking_gate])
            task.status = "skipped"
            task.error = reason
            task.output_summary = {
                **dict(task.output_summary or {}),
                "status": "skipped",
                "blocked_by": blocking_gate,
                "message": f"因格式门禁未通过而跳过（blocked_by={blocking_gate}）",
            }
            updated += 1
            changed = True
    return updated


def compute_replan_assessment(
    specialist_reviews: list[dict[str, Any]],
    board_summary: dict[str, Any],
    *,
    quality_meta: dict[str, Any] | None = None,
    specialist_task_count: int | None = None,
) -> dict[str, Any]:
    quality = quality_meta or aggregate_smart_committee_quality(specialist_reviews, board_summary)
    execution_mode_summary = quality.get("execution_mode_summary") or {}
    deterministic_count = int(execution_mode_summary.get("deterministic_count") or 0)
    harness_count = int(execution_mode_summary.get("harness_count") or 0)
    generic_llm_harness_count = int(execution_mode_summary.get("generic_llm_harness_count") or 0)
    effective_harness_count = harness_count + generic_llm_harness_count
    failed_count = int(board_summary.get("failed") or execution_mode_summary.get("failed_count") or 0)
    blocked_count = int(board_summary.get("blocked") or execution_mode_summary.get("blocked_count") or 0)
    skipped_count = int((board_summary.get("status_counts") or {}).get("skipped") or 0)
    citation_coverage = float(quality.get("citation_coverage") or 0.0)

    specialist_total = specialist_task_count
    if specialist_total is None:
        specialist_total = len(specialist_reviews)
    if specialist_total <= 0:
        specialist_total = max(
            int(board_summary.get("task_count") or 0)
            - int(board_summary.get("status_counts", {}).get("skipped") or 0)
            - 1,
            0,
        )

    needs_replan = bool(
        (specialist_total > 0 and deterministic_count == specialist_total and effective_harness_count == 0)
        or citation_coverage < 0.5
        or failed_count > 0
        or blocked_count > 0
        or skipped_count > 0
    )

    actions: list[str] = []
    if specialist_total > 0 and deterministic_count == specialist_total and effective_harness_count == 0:
        actions.append("enable_harness")
    if citation_coverage < 0.5:
        actions.extend(["upload_checklist", "upload_task_book"])
    if failed_count > 0 or blocked_count > 0 or skipped_count > 0:
        actions.append("rerun_with_force_refresh")
    if blocked_count > 0 or skipped_count > 0:
        actions.append("add_domain_specialist")

    deduped_actions: list[str] = []
    for action in actions:
        if action not in deduped_actions:
            deduped_actions.append(action)

    return {
        "needs_replan": needs_replan,
        "recommended_replan_actions": deduped_actions,
        "citation_coverage": citation_coverage,
        "deterministic_count": deterministic_count,
        "specialist_task_count": specialist_total,
    }


def arbiter_output_from_board(board: TaskBoard) -> dict[str, Any] | None:
    for task in board.tasks:
        if task.kind != KIND_ARBITER_SUMMARY:
            continue
        if task.status != "completed":
            continue
        output = dict(task.output_summary or {})
        if output:
            return output
    return None


def specialist_reviews_from_task_board(board: TaskBoard) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for task in board.tasks:
        if task.status != "completed":
            continue
        if task.kind == KIND_ARBITER_SUMMARY:
            continue
        output = task.output_summary or {}
        review = output.get("review")
        if isinstance(review, dict) and review:
            reviews.append(review)
    return reviews


def specialist_task_count_on_board(board: TaskBoard) -> int:
    return sum(1 for task in board.tasks if task.kind == KIND_SMART_SPECIALIST_REVIEW)


def aggregate_smart_committee_quality(
    specialist_reviews: list[dict[str, Any]],
    board_summary: dict[str, Any],
) -> dict[str, Any]:
    execution_mode_summary = {
        "harness_count": 0,
        "generic_llm_harness_count": 0,
        "deterministic_count": 0,
        "failed_count": int(board_summary.get("failed") or 0),
        "blocked_count": int(board_summary.get("blocked") or 0),
    }
    total_findings = 0
    findings_with_evidence = 0
    limited_reviews = 0

    for review in specialist_reviews:
        mode = str(
            review.get("execution_mode")
            or (review.get("summary") or {}).get("execution_mode")
            or "deterministic_pre_review"
        )
        if mode == "harness":
            execution_mode_summary["harness_count"] += 1
        elif mode == "generic_llm_harness":
            execution_mode_summary["generic_llm_harness_count"] += 1
        elif mode in {"blocked", "failed"}:
            pass
        else:
            execution_mode_summary["deterministic_count"] += 1

        if review.get("limited") is True or (review.get("summary") or {}).get("limited") is True:
            limited_reviews += 1

        findings = list(review.get("findings") or [])
        total_findings += len(findings)
        evidence_refs = list(review.get("evidence_refs") or review.get("citations") or [])
        if evidence_refs:
            findings_with_evidence += len(findings) if findings else 1
        else:
            for finding in findings:
                if finding.get("source_evidence_ids") or finding.get("evidence_refs"):
                    findings_with_evidence += 1

    if total_findings:
        citation_coverage = round(findings_with_evidence / total_findings, 4)
        citation_source = "findings_with_evidence_ratio"
    elif execution_mode_summary["harness_count"] or execution_mode_summary["generic_llm_harness_count"]:
        citation_coverage = 1.0
        citation_source = "harness_only_no_findings"
    else:
        citation_coverage = 0.0
        citation_source = "no_findings_or_harness"

    limited = bool(
        limited_reviews
        or execution_mode_summary["deterministic_count"]
        or execution_mode_summary["failed_count"]
        or execution_mode_summary["blocked_count"]
        or citation_coverage < 1.0
    )
    return {
        "execution_mode_summary": execution_mode_summary,
        "citation_coverage": citation_coverage,
        "evidence_coverage": citation_coverage,
        "citation_coverage_source": citation_source,
        "limited": limited,
        "limited_review_count": limited_reviews,
    }


def _resolve_smart_task_board_payload(
    review_plus_result: dict[str, Any] | None,
    *,
    classification: dict[str, Any] | None = None,
    phase_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    result = review_plus_result if isinstance(review_plus_result, dict) else {}
    classification = classification if isinstance(classification, dict) else {}
    phase_artifacts = phase_artifacts if isinstance(phase_artifacts, dict) else {}
    doc_review = phase_artifacts.get("document_review")
    doc_review = doc_review if isinstance(doc_review, dict) else {}

    for candidate in (
        result.get("smart_task_board"),
        classification.get("smart_task_board"),
        doc_review.get("smart_task_board"),
    ):
        if isinstance(candidate, dict) and candidate.get("tasks") is not None:
            return candidate
    return None


def _is_smart_committee_result(
    review_plus_result: dict[str, Any] | None,
    *,
    classification: dict[str, Any] | None = None,
    phase_artifacts: dict[str, Any] | None = None,
) -> bool:
    result = review_plus_result if isinstance(review_plus_result, dict) else {}
    if result.get("review_mode") == "smart_committee":
        return True
    if _resolve_smart_task_board_payload(result, classification=classification, phase_artifacts=phase_artifacts):
        return True
    classification = classification if isinstance(classification, dict) else {}
    return bool(classification.get("smart_task_board") or classification.get("smart_task_board_summary"))


def enrich_smart_committee_result(
    review_plus_result: dict[str, Any] | None,
    *,
    classification: dict[str, Any] | None = None,
    phase_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure SMART committee diagnostics are present, backfilling from task board when needed."""
    result = dict(review_plus_result or {})
    if not _is_smart_committee_result(result, classification=classification, phase_artifacts=phase_artifacts):
        return result

    result.setdefault("review_mode", "smart_committee")
    board_payload = _resolve_smart_task_board_payload(
        result,
        classification=classification,
        phase_artifacts=phase_artifacts,
    )
    board = TaskBoard.from_dict(board_payload) if board_payload else None
    if board is None:
        return result

    board_summary = smart_task_board_summary(board)
    if isinstance(result.get("task_board_summary"), dict):
        board_summary = {**board_summary, **result["task_board_summary"]}

    specialist_reviews = list(result.get("specialist_reviews") or [])
    if not specialist_reviews:
        specialist_reviews = specialist_reviews_from_task_board(board)

    quality_meta = aggregate_smart_committee_quality(specialist_reviews, board_summary)
    execution_mode_summary = quality_meta["execution_mode_summary"]

    result.update(
        {
            "smart_task_board": board_payload,
            "task_board_summary": board_summary,
            "total_tasks": board_summary.get("task_count", 0),
            "completed_tasks": board_summary.get("completed", 0),
            "failed_tasks": board_summary.get("failed", 0),
            "blocked_tasks": board_summary.get("blocked", 0),
            "limited_tasks": board_summary.get("limited", 0),
            "execution_mode_summary": execution_mode_summary,
            "citation_coverage": quality_meta["citation_coverage"],
            "evidence_coverage": quality_meta["evidence_coverage"],
            "citation_coverage_source": quality_meta["citation_coverage_source"],
            "limited": quality_meta["limited"],
            "limited_review_count": quality_meta["limited_review_count"],
        }
    )
    if specialist_reviews and not result.get("specialist_reviews"):
        result["specialist_reviews"] = specialist_reviews
    if specialist_reviews and not result.get("finding_count"):
        result["finding_count"] = sum(len(item.get("findings") or []) for item in specialist_reviews)

    arbiter_output = result.get("arbiter_summary")
    if not isinstance(arbiter_output, dict):
        arbiter_output = arbiter_output_from_board(board)
    if isinstance(arbiter_output, dict):
        result["arbiter_summary"] = arbiter_output
        if arbiter_output.get("needs_replan") is not None:
            result["needs_replan"] = bool(arbiter_output.get("needs_replan"))
        if arbiter_output.get("recommended_replan_actions"):
            result["recommended_replan_actions"] = list(arbiter_output.get("recommended_replan_actions") or [])

    if result.get("needs_replan") is None:
        replan = compute_replan_assessment(
            specialist_reviews,
            board_summary,
            quality_meta=quality_meta,
            specialist_task_count=specialist_task_count_on_board(board),
        )
        result["needs_replan"] = replan["needs_replan"]
        result.setdefault("recommended_replan_actions", replan["recommended_replan_actions"])

    if quality_meta["limited"] and result.get("status") == "completed":
        result["status"] = "limited"

    return result


def smart_task_board_summary(board: TaskBoard) -> dict[str, Any]:
    counts: dict[str, int] = {}
    limited_count = 0
    execution_modes: dict[str, int] = {}
    for task in board.tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
        if _task_limited(task):
            limited_count += 1
        output = task.output_summary or {}
        review = output.get("review") if isinstance(output.get("review"), dict) else {}
        mode = str(
            output.get("execution_mode")
            or review.get("execution_mode")
            or (review.get("summary") or {}).get("execution_mode")
            or ""
        ).strip()
        if mode:
            execution_modes[mode] = execution_modes.get(mode, 0) + 1
    specialist_ids = [task.specialist_id for task in board.tasks]
    return {
        "task_count": len(board.tasks),
        "specialist_ids": specialist_ids,
        "status_counts": counts,
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "blocked": counts.get("blocked", 0),
        "ready": counts.get("ready", 0),
        "limited": limited_count,
        "execution_mode_counts": execution_modes,
    }


def task_board_to_dict(board: TaskBoard) -> dict[str, Any]:
    return board.to_dict()


def task_board_from_dict(payload: dict[str, Any] | None) -> TaskBoard | None:
    return TaskBoard.from_dict(payload)


def completed_task_ids(board: TaskBoard) -> set[str]:
    return board.completed_task_ids()


def ready_tasks(board: TaskBoard) -> list[TaskItem]:
    return board.ready_tasks()


def _specialist_ids_from_chief_plan(
    chief_plan: dict[str, Any],
    fallback_ids: list[str] | None = None,
) -> list[str]:
    ids: list[str] = []
    for item in chief_plan.get("selected_agents") or []:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agent_id") or "").strip()
        if agent_id and agent_id not in ids:
            ids.append(agent_id)
    if ids:
        return ids
    return [str(item) for item in (fallback_ids or []) if item]


def _agent_entry(chief_plan: dict[str, Any], specialist_id: str) -> dict[str, Any]:
    for item in chief_plan.get("selected_agents") or []:
        if isinstance(item, dict) and str(item.get("agent_id") or "") == specialist_id:
            return item
    return {"agent_id": specialist_id, "agent_name": specialist_id}


def build_task_board_from_specs(
    task_specs: list[TaskSpec] | list[dict[str, Any]],
    evidence_summary: dict[str, Any] | None = None,
    existing_board: dict[str, Any] | TaskBoard | None = None,
    *,
    force_refresh: bool = False,
) -> TaskBoard:
    """Materialize TaskBoard from TaskSpec DAG, preserving completed tasks."""
    specs: list[TaskSpec] = []
    for item in task_specs:
        if isinstance(item, TaskSpec):
            specs.append(item)
        elif isinstance(item, dict):
            specs.append(task_spec_from_dict(item))

    evidence = dict(evidence_summary or {})

    prev: TaskBoard | None = None
    if isinstance(existing_board, TaskBoard):
        prev = existing_board
    elif isinstance(existing_board, dict):
        prev = TaskBoard.from_dict(existing_board)

    completed_map: dict[str, TaskItem] = {}
    if prev and not force_refresh:
        for task in prev.tasks:
            if task.status == "completed":
                completed_map[task.task_id] = task

    tasks: list[TaskItem] = []
    for spec in specs:
        if spec.task_id in completed_map:
            tasks.append(completed_map[spec.task_id])
            continue

        input_summary = dict(spec.input_summary)
        if evidence:
            input_summary.setdefault("evidence_summary", evidence)
        if spec.profile:
            input_summary.setdefault("profile", dict(spec.profile))
        if spec.kind == KIND_FORMAT_GATE:
            input_summary.setdefault("gate", True)

        status = "ready" if not spec.depends_on else "pending"
        tasks.append(
            TaskItem(
                task_id=spec.task_id,
                kind=spec.kind,
                agent_id=spec.agent_id,
                specialist_id=spec.specialist_id,
                title=spec.title,
                status=status,
                depends_on=list(spec.depends_on),
                input_summary=input_summary,
                priority=spec.priority,
            )
        )

    specialist_ids = [spec.specialist_id for spec in specs]
    domain_id = ""
    bootstrap: dict[str, Any] = {}
    if specs:
        first_input = specs[0].input_summary or {}
        domain_id = str(first_input.get("domain_id") or "")
        bootstrap = dict(first_input.get("bootstrap_summary") or {})

    return TaskBoard(
        board_id="smart_committee",
        kind="smart_committee",
        tasks=tasks,
        metadata={
            "specialist_ids": specialist_ids,
            "evidence_summary": evidence,
            "bootstrap_summary": bootstrap,
            "domain_id": domain_id,
            "task_spec_count": len(specs),
            "task_spec_ids": [spec.task_id for spec in specs],
        },
    )


def build_smart_committee_task_board(
    chief_plan: dict[str, Any],
    evidence_summary: dict[str, Any] | None = None,
    existing_board: dict[str, Any] | TaskBoard | None = None,
    *,
    specialist_ids: list[str] | None = None,
    force_refresh: bool = False,
    bootstrap_summary: dict[str, Any] | None = None,
    domain_id: str = "aerospace_review",
    task_specs: list[TaskSpec] | list[dict[str, Any]] | None = None,
) -> TaskBoard:
    """Expand chief plan or TaskSpecs into specialist subtasks, reusing completed work."""
    if task_specs:
        board = build_task_board_from_specs(
            task_specs,
            evidence_summary,
            existing_board,
            force_refresh=force_refresh,
        )
        board.metadata["chief_agent_id"] = str(chief_plan.get("chief_agent_id") or "")
        return board

    ids = _specialist_ids_from_chief_plan(chief_plan, fallback_ids=specialist_ids)
    evidence = dict(evidence_summary or {})
    bootstrap = dict(bootstrap_summary or {})

    prev: TaskBoard | None = None
    if isinstance(existing_board, TaskBoard):
        prev = existing_board
    elif isinstance(existing_board, dict):
        prev = TaskBoard.from_dict(existing_board)

    completed_map: dict[str, TaskItem] = {}
    if prev and not force_refresh:
        for task in prev.tasks:
            if task.status == "completed":
                completed_map[task.task_id] = task

    tasks: list[TaskItem] = []
    for specialist_id in ids:
        entry = _agent_entry(chief_plan, specialist_id)
        task_id = smart_specialist_task_id(specialist_id)
        title = str(entry.get("agent_name") or specialist_id)

        if task_id in completed_map:
            tasks.append(completed_map[task_id])
            continue

        profile_summary: dict[str, Any] = {}
        try:
            from data_agent.core.agent_profile import profile_for_specialist

            profile_summary = profile_for_specialist(specialist_id, domain_id=domain_id).summary()
        except Exception:
            profile_summary = {"agent_id": specialist_id}

        tasks.append(
            TaskItem(
                task_id=task_id,
                kind=SMART_SPECIALIST_KIND,
                agent_id=specialist_id,
                specialist_id=specialist_id,
                title=title,
                status="ready",
                depends_on=[],
                input_summary={
                    "specialist_id": specialist_id,
                    "domain_id": domain_id,
                    "assignment_reason": str(entry.get("reason") or ""),
                    "evidence_summary": evidence,
                    "bootstrap_summary": bootstrap,
                    "profile": profile_summary,
                },
            )
        )

    return TaskBoard(
        board_id="smart_committee",
        kind="smart_committee",
        tasks=tasks,
        metadata={
            "specialist_ids": ids,
            "chief_agent_id": str(chief_plan.get("chief_agent_id") or ""),
            "evidence_summary": evidence,
            "bootstrap_summary": bootstrap,
            "domain_id": domain_id,
        },
    )


__all__ = [
    "SMART_SPECIALIST_KIND",
    "TaskBoard",
    "TaskItem",
    "aggregate_smart_committee_quality",
    "arbiter_output_from_board",
    "build_smart_committee_task_board",
    "build_task_board_from_specs",
    "completed_task_ids",
    "compute_replan_assessment",
    "enrich_smart_committee_result",
    "is_gate_task",
    "propagate_gate_blocks",
    "ready_tasks",
    "resolved_task_ids",
    "smart_specialist_task_id",
    "smart_task_board_summary",
    "specialist_reviews_from_task_board",
    "specialist_task_count_on_board",
    "task_board_from_dict",
    "task_board_to_dict",
]
