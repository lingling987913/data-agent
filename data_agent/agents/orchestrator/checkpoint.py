"""DAG execution checkpoint persistence (JSON files alongside TraceStore)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from data_agent.core import config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_upstream_hash(node_outputs: dict[str, Any], depends_on: list[str]) -> str:
    """Stable hash of upstream node outputs for evaluation skip on resume."""
    subset = {dep: node_outputs.get(dep) for dep in sorted(depends_on)}
    payload = json.dumps(subset, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ExecutionCheckpoint(BaseModel):
    """Lightweight index of completed nodes for resume."""

    plan_id: str
    dag_version: str = "task_dag.v1"
    completed_nodes: list[str] = Field(default_factory=list)
    node_outputs: dict[str, Any] = Field(default_factory=dict)
    failed_node: str | None = None
    evaluation_upstream_hash: str | None = None
    updated_at: str = Field(default_factory=_utc_now)


class CheckpointStore:
    """Persist checkpoints under ``storage/runs/checkpoints/{plan_id}.checkpoint.json``."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = (base_dir or config.CHECKPOINTS_DIR).resolve()
        self._legacy_dir = config.RUNS_DIR.resolve() if base_dir is None else None
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, plan_id: str) -> Path:
        path = (self._base_dir / f"{plan_id}.checkpoint.json").resolve()
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
            legacy = (self._legacy_dir / f"{plan_id}.checkpoint.json").resolve()
            if legacy.is_file():
                return legacy
        return canonical

    def save(self, checkpoint: ExecutionCheckpoint) -> None:
        checkpoint.updated_at = _utc_now()
        path = self.path_for(checkpoint.plan_id)
        payload = checkpoint.model_dump_json(indent=2)
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent, prefix=".checkpoint-", suffix=".tmp"
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

    def load(self, plan_id: str) -> ExecutionCheckpoint | None:
        path = self._resolve_read_path(plan_id)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return ExecutionCheckpoint.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    def delete(self, plan_id: str) -> None:
        paths = [self.path_for(plan_id)]
        if self._legacy_dir is not None:
            paths.append(self._legacy_dir / f"{plan_id}.checkpoint.json")
        for path in paths:
            if path.is_file():
                path.unlink()


_store: CheckpointStore | None = None


def get_checkpoint_store() -> CheckpointStore:
    global _store
    if _store is None:
        _store = CheckpointStore()
    return _store


def apply_checkpoint_to_dag(dag: Any, checkpoint: ExecutionCheckpoint) -> None:
    """Restore SUCCESS nodes from checkpoint; reset FAILED/SKIPPED for retry."""
    completed = set(checkpoint.completed_nodes)
    node_outputs = checkpoint.node_outputs or {}
    for node in dag.nodes:
        if node.node_id in completed:
            node.status = "SUCCESS"
            node.result = node_outputs.get(node.node_id)
            node.error = None
        elif node.status in ("FAILED", "SKIPPED"):
            node.status = "PENDING"
            node.result = None
            node.error = None
            node.started_at = None
            node.finished_at = None


def build_checkpoint(
    plan_id: str,
    *,
    completed_nodes: list[str],
    node_outputs: dict[str, Any],
    failed_node: str | None = None,
    evaluation_upstream_hash: str | None = None,
) -> ExecutionCheckpoint:
    return ExecutionCheckpoint(
        plan_id=plan_id,
        completed_nodes=list(completed_nodes),
        node_outputs=dict(node_outputs),
        failed_node=failed_node,
        evaluation_upstream_hash=evaluation_upstream_hash,
    )
