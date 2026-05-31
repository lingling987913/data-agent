from __future__ import annotations

from typing import Any

from data_agent.agents.inspector.schemas import EvaluationMetrics, QualityReport, RunTrace
from data_agent.evaluation.quality import score_quality


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, dict) else {}


def _quality_scores_from_report(report: QualityReport | dict[str, Any] | None) -> dict[str, float]:
    if report is None:
        base = score_quality(EvaluationMetrics())
        report = base
    data = _as_dict(report)
    return {
        "parse_quality_score": float(data.get("parse_quality_score") or 0.0),
        "evidence_quality_score": float(data.get("evidence_quality_score") or 0.0),
        "traceability_score": float(data.get("traceability_score") or 0.0),
        "consistency_score": float(data.get("consistency_score") or 0.0),
        "stability_score": float(data.get("stability_score") or 0.0),
        "overall_score": float(data.get("overall_score") or 0.0),
    }


def _parse_artifact_summary_from_batch(batch: dict[str, Any]) -> dict[str, Any]:
    file_count = int(batch.get("file_count") or 0)
    parsed_count = int(batch.get("parsed_count") or 0)
    degraded_count = int(batch.get("degraded_count") or 0)
    failed_count = int(batch.get("failed_count") or 0)
    execution_pass_rate = float(batch.get("execution_pass_rate") or 0.0)
    capability_pass_rate = float(batch.get("capability_pass_rate") or 0.0)
    degradation_rate = float(batch.get("degradation_rate") or 0.0)
    if file_count and not batch.get("execution_pass_rate"):
        execution_pass_rate = round(parsed_count / file_count, 4)
    if file_count and not batch.get("capability_pass_rate"):
        capability_pass_rate = round(max(0, parsed_count - degraded_count) / file_count, 4)
    if file_count and not batch.get("degradation_rate"):
        degradation_rate = round(degraded_count / file_count, 4)
    return {
        "file_count": file_count,
        "parsed_count": parsed_count,
        "degraded_count": degraded_count,
        "failed_count": failed_count,
        "execution_pass_rate": execution_pass_rate,
        "capability_pass_rate": capability_pass_rate,
        "degradation_rate": degradation_rate,
    }


def _document_ir_summary_from_node_outputs(node_outputs: dict[str, Any]) -> dict[str, int]:
    """Summarize Document IR element counts from DAG structuring output."""
    structuring = node_outputs.get("data_structuring") or {}
    bundle = structuring.get("structured_bundle") or {}
    stats = bundle.get("stats") or {}
    document_ir = bundle.get("document_ir") or {}
    if not stats and not document_ir:
        parse_artifact = structuring.get("parse_artifact") or {}
        document_ir = parse_artifact.get("document_ir") or document_ir
        stats = parse_artifact.get("stats") or stats

    def _count(key: str, ir_key: str) -> int:
        if stats.get(key) is not None:
            return int(stats[key])
        items = document_ir.get(ir_key) or []
        return len(items) if isinstance(items, list) else 0

    return {
        "layout_block_count": _count("layout_block_count", "layout_blocks"),
        "visual_element_count": _count("visual_element_count", "visual_elements"),
        "table_element_count": _count("table_element_count", "table_elements"),
        "graph_element_count": _count("graph_element_count", "graph_elements"),
        "chart_element_count": _count("chart_element_count", "chart_elements"),
    }


def _batch_summary_from_node_outputs(node_outputs: dict[str, Any]) -> dict[str, Any]:
    material = node_outputs.get("material_parse") or {}
    structuring = node_outputs.get("data_structuring") or {}
    bundle = structuring.get("structured_bundle") or {}
    stats = bundle.get("stats") or {}
    docs = bundle.get("documents") or material.get("documents") or []
    file_count = len(docs) or int(material.get("material_count") or 0) or int(stats.get("document_count") or 0)
    if not file_count and material.get("blocks"):
        file_count = 1
    failed_count = sum(1 for item in docs if isinstance(item, dict) and item.get("parse_status") == "failed")
    parsed_count = max(0, file_count - failed_count) if file_count else 0
    degraded_count = int(stats.get("degradation_count") or 0)
    if not degraded_count:
        degraded_count = sum(
            1
            for item in docs
            if isinstance(item, dict) and (item.get("parse_status") != "ok" or item.get("warnings"))
        )
    if not degraded_count and material.get("warning_count"):
        degraded_count = int(material.get("warning_count") or 0)
    capability_count = sum(
        1
        for item in docs
        if isinstance(item, dict) and item.get("parse_status") == "ok" and not item.get("warnings")
    )
    if not docs and parsed_count and not material.get("warning_count"):
        capability_count = parsed_count
    return {
        "file_count": file_count,
        "parsed_count": parsed_count,
        "degraded_count": degraded_count,
        "failed_count": failed_count,
        "execution_pass_rate": round(parsed_count / file_count, 4) if file_count else 0.0,
        "capability_pass_rate": round(capability_count / file_count, 4) if file_count else 0.0,
        "degradation_rate": round(degraded_count / file_count, 4) if file_count else 0.0,
    }


def _evaluation_metrics_from_sources(
    *,
    quality_report: QualityReport | dict[str, Any] | None,
    evaluation_metrics: EvaluationMetrics | dict[str, Any] | None,
    batch_summary: dict[str, Any],
    node_outputs: dict[str, Any],
) -> EvaluationMetrics:
    if evaluation_metrics is not None:
        if isinstance(evaluation_metrics, EvaluationMetrics):
            return evaluation_metrics
        return EvaluationMetrics.model_validate(evaluation_metrics)

    structuring = node_outputs.get("data_structuring") or {}
    bundle = structuring.get("structured_bundle") or {}
    stats = bundle.get("stats") or {}
    if stats:
        blocks_total = int(stats.get("blocks_total") or 0)
        section_count = int(stats.get("section_count") or 0)
        evidence_count = int(stats.get("evidence_count") or 0)
        return EvaluationMetrics(
            blocks_total=blocks_total,
            damaged_blocks=int(stats.get("damaged_blocks") or 0),
            fallback_count=int(stats.get("fallback_count") or 0),
            anchor_total=section_count,
            anchor_covered=min(section_count, evidence_count),
            degradation_count=int(stats.get("degradation_count") or 0),
            failure_count=int(batch_summary.get("failed_count") or 0),
        )

    if quality_report is not None:
        return EvaluationMetrics()

    file_count = int(batch_summary.get("file_count") or 0)
    failed_count = int(batch_summary.get("failed_count") or 0)
    degraded_count = int(batch_summary.get("degraded_count") or 0)
    return EvaluationMetrics(
        blocks_total=file_count,
        degradation_count=degraded_count,
        failure_count=failed_count,
    )


def build_execution_metrics_snapshot(
    *,
    run_trace: RunTrace | dict[str, Any] | None = None,
    task_result: dict[str, Any] | None = None,
    dag_result: dict[str, Any] | None = None,
    super_agent_run: Any = None,
) -> dict[str, Any]:
    """Build a shared execution metrics snapshot for Planning traces and Task API results."""
    quality_report: QualityReport | dict[str, Any] | None = None
    evaluation_metrics: EvaluationMetrics | dict[str, Any] | None = None
    batch_summary: dict[str, Any] = {}
    node_outputs: dict[str, Any] = {}

    if task_result is not None:
        structured = task_result.get("structured_output") or task_result
        parse_artifact = structured.get("parse_artifact") or {}
        batch_summary = structured.get("batch_summary") or parse_artifact.get("batch_summary") or {}
        quality_report = structured.get("quality_report")
        evaluation_metrics = structured.get("evaluation_metrics")
    elif super_agent_run is not None:
        from data_agent.evaluation.super_agent_adapter import build_super_agent_evaluation_metrics
        from data_agent.super_agent.schemas import SuperAgentRun

        run = (
            super_agent_run
            if isinstance(super_agent_run, SuperAgentRun)
            else SuperAgentRun.model_validate(super_agent_run)
        )
        parse_artifact = run.structured_bundle.parse_artifact or {}
        batch_summary = parse_artifact.get("batch_summary") or run.structured_bundle.stats or {}
        quality_report = run.quality_report.model_dump(mode="json")
        evaluation_metrics = build_super_agent_evaluation_metrics(run)
    elif run_trace is not None:
        trace_data = _as_dict(run_trace)
        quality_report = trace_data.get("quality_report")
        evaluation_metrics = trace_data.get("evaluation_metrics")
        execution_plan = trace_data.get("execution_plan") or {}
        node_outputs = execution_plan.get("node_outputs") or {}
        batch_summary = _batch_summary_from_node_outputs(node_outputs)
    elif dag_result is not None:
        quality_report = dag_result.get("quality_report")
        evaluation_metrics = dag_result.get("evaluation_metrics")
        node_outputs = dag_result.get("node_results") or dag_result.get("node_outputs") or {}
        batch_summary = dag_result.get("batch_summary") or _batch_summary_from_node_outputs(node_outputs)

    if task_result is not None and not batch_summary:
        batch_summary = _batch_summary_from_node_outputs(node_outputs)

    parse_artifact_summary = _parse_artifact_summary_from_batch(batch_summary)
    metrics = _evaluation_metrics_from_sources(
        quality_report=quality_report,
        evaluation_metrics=evaluation_metrics,
        batch_summary=batch_summary,
        node_outputs=node_outputs,
    )
    if quality_report is None:
        quality_report = score_quality(metrics)
    quality_scores = _quality_scores_from_report(quality_report)

    execution_pass = (
        parse_artifact_summary["execution_pass_rate"] >= 1.0
        and parse_artifact_summary["failed_count"] == 0
    )
    capability_pass = (
        parse_artifact_summary["capability_pass_rate"] >= 1.0
        and parse_artifact_summary["degradation_rate"] == 0.0
    )

    document_ir_summary = _document_ir_summary_from_node_outputs(node_outputs)
    if task_result is not None:
        structured = task_result.get("structured_output") or task_result
        task_node_outputs = structured.get("node_outputs") or {}
        if task_node_outputs:
            document_ir_summary = _document_ir_summary_from_node_outputs(task_node_outputs)
        parse_artifact = structured.get("parse_artifact") or {}
        document_ir = structured.get("document_ir") or parse_artifact.get("document_ir") or {}
        if isinstance(document_ir, dict) and document_ir and not any(document_ir_summary.values()):
            first_ir = next(iter(document_ir.values()), {})
            if isinstance(first_ir, dict):
                document_ir_summary = {
                    "layout_block_count": len(first_ir.get("layout_blocks") or []),
                    "visual_element_count": len(first_ir.get("visual_elements") or []),
                    "table_element_count": len(first_ir.get("table_elements") or []),
                    "graph_element_count": len(first_ir.get("graph_elements") or []),
                    "chart_element_count": len(first_ir.get("chart_elements") or []),
                }

    return {
        "execution_pass": execution_pass,
        "capability_pass": capability_pass,
        "degradation_rate": parse_artifact_summary["degradation_rate"],
        "parse_artifact_summary": parse_artifact_summary,
        "document_ir_summary": document_ir_summary,
        "quality_scores": quality_scores,
    }
