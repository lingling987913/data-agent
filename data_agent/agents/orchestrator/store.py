"""In-memory plan and execution trace store."""

from __future__ import annotations

import threading
from typing import Any

from data_agent.agents.orchestrator.schemas import ExecutionTrace, PlanStatus, TaskDAG


class PlanStore:
    """Thread-safe in-memory registry for plans and execution traces."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dags: dict[str, TaskDAG] = {}
        self._traces: dict[str, ExecutionTrace] = {}
        self._status: dict[str, PlanStatus] = {}

    def save_plan(self, dag: TaskDAG) -> None:
        with self._lock:
            self._dags[dag.plan_id] = dag
            self._status[dag.plan_id] = "planned"

    def get_plan(self, plan_id: str) -> TaskDAG | None:
        with self._lock:
            return self._dags.get(plan_id)

    def get_status(self, plan_id: str) -> PlanStatus | None:
        with self._lock:
            return self._status.get(plan_id)

    def set_status(self, plan_id: str, status: PlanStatus) -> None:
        with self._lock:
            self._status[plan_id] = status

    def save_trace(self, trace: ExecutionTrace) -> None:
        with self._lock:
            self._traces[trace.plan_id] = trace
            self._status[trace.plan_id] = trace.status

    def get_trace(self, plan_id: str) -> ExecutionTrace | None:
        with self._lock:
            return self._traces.get(plan_id)

    def update_dag(self, dag: TaskDAG) -> None:
        with self._lock:
            self._dags[dag.plan_id] = dag


_store: PlanStore | None = None


def get_plan_store() -> PlanStore:
    global _store
    if _store is None:
        _store = PlanStore()
    return _store
