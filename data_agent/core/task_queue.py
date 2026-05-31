from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

from data_agent.core.config import RUNS_DIR

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DocumentTask:
    task_id: str
    task_description: str
    processing_mode: str = "OPTIMAL"
    output_format: str = "json"
    output_schema: str | None = None
    package_id: str | None = None
    documents: list[dict[str, Any]] = field(default_factory=list)
    use_dag: bool = False
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    current_step: str = ""
    scenario: str = "single_doc_parse"
    parser_trace: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None

    def to_status_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "progress": self.progress,
            "current_step": self.current_step,
            "scenario": self.scenario,
            "parser_trace": self.parser_trace,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    def to_result_dict(self) -> dict[str, Any]:
        payload = self.to_status_dict()
        payload["result"] = self.result
        return payload


class DocumentTaskQueue:
    def __init__(self, max_concurrent: int = 10) -> None:
        self.tasks: dict[str, DocumentTask] = {}
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def create_task(
        self,
        *,
        task_description: str,
        documents: list[dict[str, Any]],
        processing_mode: str = "OPTIMAL",
        output_format: str = "json",
        output_schema: str | None = None,
        package_id: str | None = None,
        use_dag: bool = False,
    ) -> DocumentTask:
        task_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task = DocumentTask(
            task_id=task_id,
            task_description=task_description,
            processing_mode=processing_mode,
            output_format=output_format,
            output_schema=output_schema,
            package_id=package_id,
            documents=documents,
            use_dag=use_dag,
            created_at=now,
        )
        self.tasks[task_id] = task
        return task

    async def execute_task(self, task_id: str, runner: Callable[[DocumentTask], Any]) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        async with self._semaphore:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(timezone.utc).isoformat()
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: runner(task))
                task.result = result
                task.progress = 1.0
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                self._persist_trace(task)
            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                task.completed_at = datetime.now(timezone.utc).isoformat()
                logger.exception("Task %s failed", task.task_id)

    def get_status(self, task_id: str) -> dict[str, Any] | None:
        task = self.tasks.get(task_id)
        if not task:
            return None
        return task.to_status_dict()

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        task = self.tasks.get(task_id)
        if not task:
            return None
        return task.to_result_dict()

    def _persist_trace(self, task: DocumentTask) -> None:
        """Persist task result snapshot under ``storage/runs/tasks/``.

        DAG mode uses ``task_id`` as ``plan_id`` for :class:`TraceStore`; keep
        task snapshots in a separate directory so evaluation traces are not overwritten.
        """
        tasks_dir = RUNS_DIR / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        path = tasks_dir / f"{task.task_id}.json"
        path.write_text(
            json.dumps(task.to_result_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


_queue: DocumentTaskQueue | None = None


def get_task_queue() -> DocumentTaskQueue:
    global _queue
    if _queue is None:
        _queue = DocumentTaskQueue()
    return _queue
