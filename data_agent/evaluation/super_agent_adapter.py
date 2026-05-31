from __future__ import annotations

from typing import Any

from data_agent.agents.inspector.schemas import EvaluationMetrics
from data_agent.evaluation.quality import score_quality
from data_agent.super_agent.schemas import SuperAgentQualityReport, SuperAgentRun


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_super_agent_evaluation_metrics(
    run: SuperAgentRun,
    *,
    extra_failure_count: int = 0,
    extra_degradation_count: int = 0,
) -> EvaluationMetrics:
    stats = run.structured_bundle.stats or {}
    document_ir = run.structured_bundle.document_ir or {}
    batch_summary = (run.structured_bundle.parse_artifact or {}).get("batch_summary") or {}
    blocks_total = (
        _as_int(stats.get("layout_block_count"))
        or len(document_ir.get("layout_blocks") or [])
        or _as_int(stats.get("chunk_count"))
        or len(run.structured_bundle.chunks)
    )
    section_count = _as_int(stats.get("section_count")) or len((run.structured_bundle.section_tree or {}).get("sections", []))
    evidence_count = _as_int(stats.get("evidence_count")) or len((run.structured_bundle.evidence_pool or {}).get("evidences", []))
    fallback_count = len(run.structured_bundle.parser_fallback_logs) + len(run.trace_report.fallback_events)
    failure_count = (
        _as_int(batch_summary.get("failed_count"))
        + sum(1 for trace in run.skill_traces if trace.status == "failed")
        + len(run.trace_report.failed_steps)
        + max(0, extra_failure_count)
    )
    degradation_count = (
        _as_int(batch_summary.get("degraded_count"))
        + len(run.structured_bundle.warnings)
        + len(run.trace_report.degradation_summary)
        + max(0, extra_degradation_count)
    )
    return EvaluationMetrics(
        blocks_total=blocks_total,
        damaged_blocks=_as_int(batch_summary.get("degraded_count")) + len(run.structured_bundle.self_healing_records),
        fallback_count=fallback_count,
        anchor_total=section_count,
        anchor_covered=min(evidence_count, section_count) if section_count else evidence_count,
        numeric_checks=max(_as_int(stats.get("extracted_parameter_count")), 0),
        numeric_passed=max(_as_int(stats.get("extracted_parameter_count")), 0),
        degradation_count=degradation_count,
        failure_count=failure_count,
        retry_count=len(run.structured_bundle.self_healing_records),
    )


def score_super_agent_quality(
    run: SuperAgentRun,
    *,
    traceability_score: float = 0.0,
    consistency_score: float | None = None,
    expert_consensus_score: float = 0.0,
    evidence_sufficiency_score: float = 0.0,
    conflict_detection_score: float = 0.0,
    warnings: list[str] | None = None,
    extra_failure_count: int = 0,
    extra_degradation_count: int = 0,
) -> SuperAgentQualityReport:
    base = score_quality(
        build_super_agent_evaluation_metrics(
            run,
            extra_failure_count=extra_failure_count,
            extra_degradation_count=extra_degradation_count,
        )
    )
    traceability = round(max(0.0, min(1.0, traceability_score or base.traceability_score)), 4)
    consistency = round(max(0.0, min(1.0, consistency_score if consistency_score is not None else base.consistency_score)), 4)
    return SuperAgentQualityReport(
        parse_quality_score=base.parse_quality_score,
        evidence_quality_score=base.evidence_quality_score,
        traceability_score=traceability,
        consistency_score=consistency,
        stability_score=base.stability_score,
        overall_score=round(
            (base.parse_quality_score + base.evidence_quality_score + traceability + consistency + base.stability_score) / 5.0,
            4,
        ),
        expert_consensus_score=round(max(0.0, min(1.0, expert_consensus_score)), 4),
        evidence_sufficiency_score=round(max(0.0, min(1.0, evidence_sufficiency_score)), 4),
        conflict_detection_score=round(max(0.0, min(1.0, conflict_detection_score)), 4),
        warnings=list(warnings or []),
        human_confirmation_required=base.human_confirmation_required,
    )
