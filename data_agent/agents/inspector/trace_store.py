"""JSON file persistence for evaluation run traces."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from data_agent.core import config
from data_agent.agents.inspector.schemas import (
    CostSummary,
    EvaluationMetrics,
    RunTrace,
    SelfHealingRecord,
)
from data_agent.agents.orchestrator.schemas import ExecutionTrace


def _parser_trace_summary_from_execution(exec_trace: ExecutionTrace) -> dict[str, Any] | None:
    evaluation = (exec_trace.node_outputs or {}).get("evaluation") or {}
    summary = evaluation.get("parser_trace_summary")
    if isinstance(summary, dict) and summary:
        return dict(summary)
    return None


class TraceStore:
    """Persist :class:`RunTrace` objects under ``storage/runs/traces/{plan_id}.json``."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = (base_dir or config.TRACES_DIR).resolve()
        self._legacy_dir = config.RUNS_DIR.resolve() if base_dir is None else None
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, plan_id: str) -> Path:
        path = (self._base_dir / f"{plan_id}.json").resolve()
        try:
            path.relative_to(self._base_dir)
        except ValueError as exc:
            raise ValueError(f"Invalid plan_id: {plan_id!r}") from exc
        return path

    def _resolve_read_path(self, plan_id: str) -> Path:
        canonical = self.path_for(plan_id)
        if canonical.is_file():
            return canonical
        if self._legacy_dir is not None:
            legacy = (self._legacy_dir / f"{plan_id}.json").resolve()
            if legacy.is_file():
                return legacy
        return canonical

    def save(self, trace: RunTrace) -> None:
        path = self.path_for(trace.plan_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = trace.model_dump_json(indent=2)
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent, prefix=".trace-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load(self, plan_id: str) -> RunTrace | None:
        path = self._resolve_read_path(plan_id)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return RunTrace.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    def list_runs(self) -> list[str]:
        ids = {p.stem for p in self._base_dir.glob("*.json")}
        if self._legacy_dir is not None:
            for path in self._legacy_dir.glob("*.json"):
                if path.stem.endswith(".checkpoint"):
                    continue
                ids.add(path.stem)
        return sorted(ids)

    def build_from_execution(
        self,
        exec_trace: ExecutionTrace,
        *,
        healing_records: list[SelfHealingRecord] | None = None,
        cost_summary: CostSummary | None = None,
        metrics: EvaluationMetrics | None = None,
        parser_trace_summary: dict[str, Any] | None = None,
    ) -> RunTrace:
        now = datetime.now(timezone.utc).isoformat()
        summary = parser_trace_summary or _parser_trace_summary_from_execution(exec_trace)
        return RunTrace(
            plan_id=exec_trace.plan_id,
            execution_plan=exec_trace,
            self_healing_records=healing_records or [],
            cost_summary=cost_summary,
            evaluation_metrics=metrics,
            parser_trace_summary=summary,
            created_at=now,
            updated_at=now,
        )


_store: TraceStore | None = None


def get_trace_store() -> TraceStore:
    global _store
    if _store is None:
        _store = TraceStore()
    return _store
