"""Request/response models for evaluation REST API."""

from __future__ import annotations

from pydantic import BaseModel

from data_agent.agents.inspector.schemas import (
    CostSummary,
    EvaluationMetrics,
    QualityReport,
    RunTrace,
)


class ReportResponse(BaseModel):
    plan_id: str
    report: QualityReport
    evaluation_metrics: EvaluationMetrics | None = None


class TraceResponse(BaseModel):
    plan_id: str
    trace: RunTrace


class CostResponse(BaseModel):
    plan_id: str
    cost: CostSummary
