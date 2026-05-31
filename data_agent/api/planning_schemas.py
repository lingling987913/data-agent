"""Request/response models for planning REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from data_agent.agents.orchestrator.schemas import ExecutionTrace, PlanStatus, TaskDAG


class PlanRequest(BaseModel):
    instruction: str = Field(
        ...,
        description='总体任务指令，如 "对这份卫星GNC设计文档进行全流程评审"',
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanResponse(BaseModel):
    plan_id: str
    dag: TaskDAG
    visualization: dict[str, Any]
    task_classification: dict[str, Any] | None = None


class ExecuteRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanStatusResponse(BaseModel):
    plan_id: str
    status: PlanStatus
    dag: TaskDAG
    visualization: dict[str, Any]


class TraceResponse(BaseModel):
    plan_id: str
    trace: ExecutionTrace
    parser_trace_summary: dict[str, Any] | None = None


class CheckpointResponse(BaseModel):
    plan_id: str
    checkpoint: dict[str, Any]
    pending_nodes: list[str] = Field(default_factory=list)
