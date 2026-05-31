"""DAG execution engine with parallel levels and failure isolation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from data_agent.agents.orchestrator.checkpoint import (
    apply_checkpoint_to_dag,
    build_checkpoint,
    compute_upstream_hash,
    get_checkpoint_store,
)
from data_agent.agents.orchestrator.dag import execution_levels, should_skip_node
from data_agent.agents.orchestrator.schemas import (
    ExecutionTrace,
    ParserFallbackLog,
    PlanStatus,
    TaskDAG,
    TaskNodeStatus,
)
from data_agent.agents.orchestrator.tool_router import ExecutionContext, ToolRouter

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_fallback_logs(raw: list[Any]) -> list[ParserFallbackLog]:
    out: list[ParserFallbackLog] = []
    for item in raw:
        if isinstance(item, ParserFallbackLog):
            out.append(item)
        elif isinstance(item, dict):
            out.append(ParserFallbackLog.model_validate(item))
    return out


def _set_node_status(node: Any, status: TaskNodeStatus) -> None:
    node.status = status
    if status == "RUNNING":
        node.started_at = _utc_now()
    elif status in ("SUCCESS", "FAILED", "SKIPPED"):
        node.finished_at = _utc_now()


class DAGExecutor:
    """Execute a TaskDAG in topological levels with bounded parallelism."""

    def __init__(
        self,
        router: ToolRouter | None = None,
        *,
        max_parallel: int = 4,
        checkpoint_store: Any | None = None,
    ) -> None:
        self.router = router or ToolRouter()
        self.max_parallel = max(1, max_parallel)
        self._checkpoint_store = checkpoint_store

    def _checkpoints(self):
        return self._checkpoint_store or get_checkpoint_store()

    async def execute(
        self,
        dag: TaskDAG,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionTrace:
        """Run all nodes; failed deps cause SKIP without blocking unrelated branches."""
        ctx = ExecutionContext(
            plan_id=dag.plan_id,
            instruction=dag.instruction,
            metadata=dict(metadata or {}),
        )
        return await self._run(dag, ctx, resume=False)

    async def resume(
        self,
        dag: TaskDAG,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionTrace:
        """Resume from checkpoint: skip completed nodes, retry failed/skipped boundary."""
        checkpoint = self._checkpoints().load(dag.plan_id)
        if checkpoint is None:
            raise ValueError(f"No checkpoint found for plan: {dag.plan_id}")

        apply_checkpoint_to_dag(dag, checkpoint)
        ctx = ExecutionContext(
            plan_id=dag.plan_id,
            instruction=dag.instruction,
            metadata=dict(metadata or {}),
        )
        ctx.node_results.update(checkpoint.node_outputs)
        return await self._run(dag, ctx, resume=True)

    async def _run(
        self,
        dag: TaskDAG,
        ctx: ExecutionContext,
        *,
        resume: bool,
    ) -> ExecutionTrace:
        trace = ExecutionTrace(
            plan_id=dag.plan_id,
            instruction=dag.instruction,
            status="running",
            dag=dag,
            started_at=_utc_now(),
            node_outputs=dict(ctx.node_results),
            completed_nodes=[
                n.node_id for n in dag.nodes if n.status == "SUCCESS"
            ],
        )
        node_map = dag.node_map()
        sem = asyncio.Semaphore(self.max_parallel)
        failed_node: str | None = None

        try:
            for level in execution_levels(dag):
                await self._run_level(level, dag, node_map, ctx, sem, trace, resume=resume)
            trace.parser_fallback_logs = _coerce_fallback_logs(ctx.parser_fallback_logs)
            trace.node_outputs = dict(ctx.node_results)
            trace.completed_nodes = [
                n.node_id for n in dag.nodes if n.status == "SUCCESS"
            ]
            statuses = {n.status for n in dag.nodes}
            if "FAILED" in statuses:
                trace.status = "failed"
                failed_node = next(
                    (n.node_id for n in dag.nodes if n.status == "FAILED"),
                    None,
                )
                trace.failed_node = failed_node
            else:
                trace.status = "completed"
                trace.failed_node = None
        except Exception as exc:
            trace.status = "failed"
            trace.error = str(exc)
            logger.exception("[DAGExecutor] plan %s failed: %s", dag.plan_id, exc)
        finally:
            trace.dag = dag
            trace.finished_at = _utc_now()
            self._persist_checkpoint(trace, failed_node)
            self._persist_trace(trace)

        return trace

    def _persist_checkpoint(
        self,
        trace: ExecutionTrace,
        failed_node: str | None,
        *,
        evaluation_upstream_hash: str | None = None,
    ) -> None:
        if not trace.completed_nodes:
            return
        try:
            existing = self._checkpoints().load(trace.plan_id)
            eval_hash = evaluation_upstream_hash
            if eval_hash is None and existing is not None:
                eval_hash = existing.evaluation_upstream_hash
            cp = build_checkpoint(
                trace.plan_id,
                completed_nodes=trace.completed_nodes,
                node_outputs=trace.node_outputs,
                failed_node=failed_node,
                evaluation_upstream_hash=eval_hash,
            )
            self._checkpoints().save(cp)
        except Exception as persist_exc:
            logger.warning(
                "[DAGExecutor] failed to persist checkpoint for plan %s: %s",
                trace.plan_id,
                persist_exc,
            )

    def _try_skip_evaluation(
        self,
        node: Any,
        ctx: ExecutionContext,
        dag: TaskDAG,
    ) -> dict[str, Any] | None:
        checkpoint = self._checkpoints().load(dag.plan_id)
        if checkpoint is None or not checkpoint.evaluation_upstream_hash:
            return None
        current_hash = compute_upstream_hash(ctx.node_results, list(node.depends_on))
        if current_hash != checkpoint.evaluation_upstream_hash:
            return None
        try:
            from data_agent.agents.inspector.trace_store import get_trace_store

            run_trace = get_trace_store().load(dag.plan_id)
        except Exception:
            return None
        if run_trace is None or run_trace.quality_report is None:
            return None
        report = run_trace.quality_report
        node_results = ctx.node_results
        material_parse = node_results.get("material_parse") or {}
        structuring = node_results.get("data_structuring") or {}
        parse_artifact = (
            structuring.get("parse_artifact")
            or material_parse.get("parse_artifact")
            or {}
        )
        parser_trace_summary = run_trace.parser_trace_summary or {}
        metrics = run_trace.evaluation_metrics
        return {
            "status": "ok",
            "mock": False,
            "skipped": True,
            "reason": "evaluation_upstream_unchanged",
            "quality_report": report.model_dump(),
            "overall_score": report.overall_score,
            "human_confirmation_required": report.human_confirmation_required,
            "parser_trace_summary": parser_trace_summary,
            "evaluation_metrics": metrics.model_dump() if metrics else {},
        }

    def _persist_trace(self, trace: ExecutionTrace) -> None:
        try:
            from data_agent.agents.inspector.trace_store import get_trace_store

            store = get_trace_store()
            existing = store.load(trace.plan_id)
            run_trace = store.build_from_execution(trace)
            if existing is not None:
                run_trace.self_healing_records = existing.self_healing_records
                run_trace.cost_summary = existing.cost_summary
                run_trace.evaluation_metrics = existing.evaluation_metrics
                run_trace.quality_report = existing.quality_report
                run_trace.parser_trace_summary = existing.parser_trace_summary
                run_trace.created_at = existing.created_at
            store.save(run_trace)
        except Exception as persist_exc:
            logger.warning(
                "[DAGExecutor] failed to persist trace for plan %s: %s",
                trace.plan_id,
                persist_exc,
            )

    async def _run_level(
        self,
        level: list[str],
        dag: TaskDAG,
        node_map: dict[str, Any],
        ctx: ExecutionContext,
        sem: asyncio.Semaphore,
        trace: ExecutionTrace,
        *,
        resume: bool = False,
    ) -> None:
        tasks = [
            self._run_node(nid, dag, node_map, ctx, sem, trace, resume=resume)
            for nid in level
        ]
        await asyncio.gather(*tasks)

    async def _run_node(
        self,
        node_id: str,
        dag: TaskDAG,
        node_map: dict[str, Any],
        ctx: ExecutionContext,
        sem: asyncio.Semaphore,
        trace: ExecutionTrace,
        *,
        resume: bool = False,
    ) -> None:
        node = node_map[node_id]
        if should_skip_node(node, dag):
            if node.status != "SUCCESS":
                _set_node_status(node, "SKIPPED")
                ctx.node_results[node_id] = {"status": "skipped", "reason": "dependency failed"}
            return

        async with sem:
            if resume and node_id == "evaluation":
                cached = self._try_skip_evaluation(node, ctx, dag)
                if cached is not None:
                    node.result = cached
                    node.error = None
                    _set_node_status(node, "SUCCESS")
                    ctx.node_results[node_id] = cached
                    trace.completed_nodes = [
                        n.node_id for n in dag.nodes if n.status == "SUCCESS"
                    ]
                    trace.node_outputs = dict(ctx.node_results)
                    self._persist_checkpoint(trace, failed_node=None)
                    return

            _set_node_status(node, "RUNNING")
            try:
                payload = {
                    "plan_id": ctx.plan_id,
                    "instruction": ctx.instruction,
                    "metadata": ctx.metadata,
                    "node_results": dict(ctx.node_results),
                    "parser_fallback_logs": ctx.parser_fallback_logs,
                }
                result = await self.router.execute_node(node, payload)
                node.result = result
                node.error = None
                _set_node_status(node, "SUCCESS")
                ctx.node_results[node_id] = result
                trace.completed_nodes = [
                    n.node_id for n in dag.nodes if n.status == "SUCCESS"
                ]
                trace.node_outputs = dict(ctx.node_results)
                eval_hash = None
                if node_id == "evaluation":
                    eval_hash = compute_upstream_hash(
                        ctx.node_results, list(node.depends_on)
                    )
                self._persist_checkpoint(trace, failed_node=None, evaluation_upstream_hash=eval_hash)
            except Exception as exc:
                node.error = str(exc)
                node.result = None
                _set_node_status(node, "FAILED")
                ctx.node_results[node_id] = {"status": "failed", "error": str(exc)}
                trace.failed_node = node_id
                self._persist_checkpoint(trace, failed_node=node_id)
                logger.warning("[DAGExecutor] node %s failed: %s", node_id, exc)
