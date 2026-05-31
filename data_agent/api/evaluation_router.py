"""REST API for persisted evaluation run traces."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from data_agent.api.auth import verify_api_token
from data_agent.api.evaluation_schemas import (
    CostResponse,
    ReportResponse,
    TraceResponse,
)
from data_agent.core.contracts import success_response
from data_agent.agents.inspector.quality_evaluator import QualityEvaluator
from data_agent.agents.inspector.schemas import EvaluationMetrics
from data_agent.agents.inspector.trace_store import TraceStore, get_trace_store

router = APIRouter(
    prefix="/api/v1/evaluation",
    tags=["evaluation"],
    dependencies=[Depends(verify_api_token)],
)

_evaluator = QualityEvaluator()


def _load_trace(plan_id: str, store: TraceStore):
    trace = store.load(plan_id)
    if trace is None:
        raise HTTPException(
            status_code=404,
            detail=f"Run trace not found for plan: {plan_id}",
        )
    return trace


@router.get("/{plan_id}/report", summary="获取质量评测报告")
async def get_report(plan_id: str):
    store = get_trace_store()
    trace = _load_trace(plan_id, store)
    report = trace.quality_report
    if report is None:
        report = _evaluator.evaluate(
            trace.execution_plan,
            trace.self_healing_records,
            trace.cost_summary,
            trace.evaluation_metrics,
        )
    payload = ReportResponse(
        plan_id=plan_id,
        report=report,
        evaluation_metrics=trace.evaluation_metrics,
    )
    return success_response(payload.model_dump(mode="json"))


@router.get("/{plan_id}/trace", summary="获取完整 RunTrace")
async def get_trace(plan_id: str):
    store = get_trace_store()
    trace = _load_trace(plan_id, store)
    payload = TraceResponse(plan_id=plan_id, trace=trace)
    return success_response(payload.model_dump(mode="json"))


@router.get("/{plan_id}/cost", summary="获取 LLM 成本汇总")
async def get_cost(plan_id: str):
    store = get_trace_store()
    trace = _load_trace(plan_id, store)
    if trace.cost_summary is None:
        raise HTTPException(
            status_code=404,
            detail=f"Cost summary not found for plan: {plan_id}",
        )
    payload = CostResponse(plan_id=plan_id, cost=trace.cost_summary)
    return success_response(payload.model_dump(mode="json"))
