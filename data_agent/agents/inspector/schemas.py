"""Pydantic models for evaluation traces, cost, and quality reporting."""

from __future__ import annotations

from datetime import datetime, timezone

from typing import Any

from pydantic import BaseModel, Field

from data_agent.agents.orchestrator.schemas import ExecutionTrace
from data_agent.agents.format_guard.schemas import FormatDamageType

RepairStatus = str


class LLMCallDetail(BaseModel):
    call_id: str
    component: str
    model_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    status: str = "ok"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class CostSummary(BaseModel):
    llm_call_count: int = 0
    api_call_count: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    calls: list[LLMCallDetail] = Field(default_factory=list)


class SelfHealingRecord(BaseModel):
    block_id: str
    damage_types: list[FormatDamageType] = Field(default_factory=list)
    repair_status: RepairStatus
    unified_diff: str = ""
    text_before_len: int = 0
    text_after_len: int = 0


class EvaluationMetrics(BaseModel):
    blocks_total: int = 0
    damaged_blocks: int = 0
    fallback_count: int = 0
    anchor_total: int = 0
    anchor_covered: int = 0
    anaphora_attempts: int = 0
    anaphora_resolved: int = 0
    numeric_checks: int = 0
    numeric_passed: int = 0
    degradation_count: int = 0
    failure_count: int = 0
    retry_count: int = 0


class QualityReport(BaseModel):
    parse_quality_score: float = 0.0
    evidence_quality_score: float = 0.0
    traceability_score: float = 0.0
    consistency_score: float = 0.0
    stability_score: float = 0.0
    overall_score: float = 0.0
    human_confirmation_required: bool = False


class RunTrace(BaseModel):
    plan_id: str
    execution_plan: ExecutionTrace | None = None
    self_healing_records: list[SelfHealingRecord] = Field(default_factory=list)
    cost_summary: CostSummary | None = None
    quality_report: QualityReport | None = None
    evaluation_metrics: EvaluationMetrics | None = None
    parser_trace_summary: dict[str, Any] | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
