"""Real evaluation DAG node handler (separate from tool_router mock)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from data_agent.agents.inspector.quality_evaluator import QualityEvaluator
from data_agent.agents.inspector.schemas import EvaluationMetrics, RunTrace
from data_agent.agents.inspector.trace_store import TraceStore, get_trace_store
from data_agent.agents.orchestrator.schemas import DAGNode, TaskType
from data_agent.evaluation.execution_metrics import build_execution_metrics_snapshot
from data_agent.evaluation.parser_trace_summary import build_parser_trace_summary

logger = logging.getLogger(__name__)


def _metrics_from_context(context: dict[str, Any]) -> EvaluationMetrics:
    node_results = context.get("node_results", {}) or {}
    structuring = node_results.get("data_structuring") or {}
    material_parse = node_results.get("material_parse") or {}
    stats = (structuring.get("structured_bundle") or {}).get("stats") or {}

    blocks_total = int(stats.get("blocks_total") or structuring.get("blocks_total") or material_parse.get("blocks") or 0)
    damaged_blocks = int(stats.get("damaged_blocks") or structuring.get("damaged_blocks") or 0)
    section_count = int(stats.get("section_count") or structuring.get("section_count") or 0)
    evidence_count = int(stats.get("evidence_count") or structuring.get("evidence_count") or 0)
    fallback_count = int(stats.get("fallback_count") or len(context.get("parser_fallback_logs") or []))
    degradation_count = int(stats.get("degradation_count") or 0)
    warning_count = int(material_parse.get("warning_count") or len(structuring.get("warnings") or []))
    failure_count = sum(1 for result in node_results.values() if isinstance(result, dict) and result.get("status") == "failed")

    return EvaluationMetrics(
        blocks_total=blocks_total,
        damaged_blocks=damaged_blocks,
        fallback_count=fallback_count,
        anchor_total=section_count,
        anchor_covered=min(section_count, evidence_count),
        anaphora_attempts=int(structuring.get("anaphora_attempts") or 0),
        anaphora_resolved=int(structuring.get("anaphora_resolved") or 0),
        degradation_count=degradation_count + (1 if warning_count else 0),
        failure_count=failure_count,
    )


class EvaluationToolHandler:
    """DAG evaluation node: load RunTrace, score quality, persist report."""

    task_type = TaskType.EVALUATION.value

    def __init__(
        self,
        *,
        trace_store: TraceStore | None = None,
        evaluator: QualityEvaluator | None = None,
    ) -> None:
        self._store = trace_store
        self._evaluator = evaluator or QualityEvaluator()

    async def execute(self, node: DAGNode, context: dict[str, Any]) -> dict[str, Any]:
        del node
        plan_id = str(context.get("plan_id", ""))
        store = self._store or get_trace_store()
        run_trace = store.load(plan_id)

        if run_trace is None:
            metrics = _metrics_from_context(context)
            if not context.get("node_results"):
                logger.warning("[EvaluationToolHandler] no trace for plan_id=%s", plan_id)
                return {
                    "status": "error",
                    "mock": False,
                    "message": f"No run trace found for plan_id={plan_id}",
                }
            run_trace = RunTrace(plan_id=plan_id, evaluation_metrics=metrics)
        elif run_trace.evaluation_metrics is None:
            run_trace.evaluation_metrics = _metrics_from_context(context)

        metrics = run_trace.evaluation_metrics or EvaluationMetrics()
        report = self._evaluator.evaluate(
            run_trace.execution_plan,
            run_trace.self_healing_records,
            run_trace.cost_summary,
            metrics,
        )
        node_results = context.get("node_results", {}) or {}
        material_parse = node_results.get("material_parse") or {}
        structuring = node_results.get("data_structuring") or {}
        parse_artifact = (
            structuring.get("parse_artifact")
            or material_parse.get("parse_artifact")
            or {}
        )
        parser_trace_summary = build_parser_trace_summary(
            parse_artifact=parse_artifact,
            parser_fallback_logs=context.get("parser_fallback_logs"),
        )
        run_trace.quality_report = report
        run_trace.parser_trace_summary = parser_trace_summary
        run_trace.updated_at = datetime.now(timezone.utc).isoformat()
        store.save(run_trace)

        execution_metrics_snapshot = build_execution_metrics_snapshot(
            run_trace=run_trace,
            dag_result={
                "node_results": node_results,
                "quality_report": report.model_dump(),
                "evaluation_metrics": metrics.model_dump(),
            },
        )

        return {
            "status": "ok",
            "mock": False,
            "quality_report": report.model_dump(),
            "overall_score": report.overall_score,
            "human_confirmation_required": report.human_confirmation_required,
            "execution_metrics_snapshot": execution_metrics_snapshot,
            "parser_trace_summary": parser_trace_summary,
        }
