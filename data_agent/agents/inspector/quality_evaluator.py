"""Five-dimension quality scoring for evaluation runs."""

from __future__ import annotations

from data_agent.agents.inspector.schemas import (
    CostSummary,
    EvaluationMetrics,
    QualityReport,
    SelfHealingRecord,
)
from data_agent.agents.orchestrator.schemas import ExecutionTrace


class QualityEvaluator:
    """Compute quality scores from execution trace and evaluation metrics."""

    def evaluate(
        self,
        execution_trace: ExecutionTrace | None,
        healing_records: list[SelfHealingRecord],
        cost_summary: CostSummary | None,
        metrics: EvaluationMetrics | None,
    ) -> QualityReport:
        del execution_trace, healing_records, cost_summary
        from data_agent.evaluation.quality import score_quality

        return score_quality(metrics)
