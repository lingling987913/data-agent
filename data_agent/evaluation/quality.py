from __future__ import annotations

from data_agent.agents.inspector.schemas import EvaluationMetrics, QualityReport

HITL_OVERALL_THRESHOLD = 0.7


def _ratio(numerator: int, denominator: int, *, default: float = 1.0) -> float:
    if denominator <= 0:
        return default
    return max(0.0, min(1.0, numerator / denominator))


def score_quality(metrics: EvaluationMetrics | None) -> QualityReport:
    m = metrics or EvaluationMetrics()
    parse_quality = 1.0 - _ratio(m.damaged_blocks, m.blocks_total, default=0.0) if m.blocks_total else 1.0
    evidence_quality = _ratio(m.anchor_covered, m.anchor_total)
    traceability = 1.0 - _ratio(m.fallback_count, m.blocks_total, default=0.0) if m.blocks_total else 1.0
    consistency = _ratio(m.numeric_passed, m.numeric_checks)
    instability = m.degradation_count + m.failure_count + m.retry_count
    stability = 1.0 - _ratio(instability, max(m.blocks_total, 1), default=0.0)
    overall = (parse_quality + evidence_quality + traceability + consistency + stability) / 5.0
    return QualityReport(
        parse_quality_score=round(parse_quality, 4),
        evidence_quality_score=round(evidence_quality, 4),
        traceability_score=round(traceability, 4),
        consistency_score=round(consistency, 4),
        stability_score=round(stability, 4),
        overall_score=round(overall, 4),
        human_confirmation_required=overall < HITL_OVERALL_THRESHOLD or m.failure_count > 0,
    )
