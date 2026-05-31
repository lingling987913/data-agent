"""REST API for task planning and DAG execution."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from data_agent.api.auth import verify_api_token
from data_agent.api.planning_schemas import (
    ExecuteRequest,
    PlanRequest,
    PlanResponse,
    PlanStatusResponse,
    TraceResponse,
    CheckpointResponse,
)
from data_agent.core.contracts import success_response
from data_agent.agents.orchestrator.checkpoint import get_checkpoint_store
from data_agent.agents.orchestrator.dag import execution_levels, should_skip_node
from data_agent.agents.orchestrator.store import get_plan_store
from data_agent.agents.inspector.trace_store import get_trace_store
from data_agent.services.pipeline_runner import build_dag_executor, build_planner
from data_agent.services.task_classifier import classify_for_planning

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/planning",
    tags=["planning"],
    dependencies=[Depends(verify_api_token)],
)

_planner = build_planner()
_executor = build_dag_executor()


@router.post("/plan", summary="提交任务指令并生成执行计划 DAG")
async def create_plan(req: PlanRequest):
    if not req.instruction.strip():
        raise HTTPException(status_code=422, detail="instruction cannot be empty")
    classification, enriched_metadata = classify_for_planning(req.instruction, req.metadata)
    dag = _planner.plan(req.instruction, metadata=enriched_metadata)
    store = get_plan_store()
    store.save_plan(dag)
    payload = PlanResponse(
        plan_id=dag.plan_id,
        dag=dag,
        visualization=dag.to_visualization(),
        task_classification=classification.model_dump(mode="json"),
    )
    return success_response(payload.model_dump(mode="json"))


@router.post("/execute/{plan_id}", summary="启动 DAG 执行")
async def execute_plan(plan_id: str, req: ExecuteRequest | None = None):
    store = get_plan_store()
    dag = store.get_plan(plan_id)
    if dag is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")

    store.set_status(plan_id, "running")
    execute_metadata = (req.metadata if req else {}) or {}
    merged_metadata = {**(dag.metadata or {}), **execute_metadata}
    if execute_metadata.get("materials"):
        _, merged_metadata = classify_for_planning(dag.instruction, merged_metadata)
    dag.metadata = merged_metadata
    trace = await _executor.execute(dag, metadata=merged_metadata)
    store.save_trace(trace)
    store.update_dag(dag)
    return success_response(
        {
            "plan_id": plan_id,
            "status": trace.status,
            "visualization": dag.to_visualization(),
        }
    )


@router.post("/resume/{plan_id}", summary="从 checkpoint 恢复 DAG 执行")
async def resume_plan(plan_id: str, req: ExecuteRequest | None = None):
    store = get_plan_store()
    dag = store.get_plan(plan_id)
    if dag is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")

    checkpoint = get_checkpoint_store().load(plan_id)
    if checkpoint is None:
        raise HTTPException(
            status_code=404,
            detail=f"No checkpoint found for plan: {plan_id}",
        )

    store.set_status(plan_id, "running")
    execute_metadata = (req.metadata if req else {}) or {}
    merged_metadata = {**(dag.metadata or {}), **execute_metadata}
    if execute_metadata.get("materials"):
        _, merged_metadata = classify_for_planning(dag.instruction, merged_metadata)
    dag.metadata = merged_metadata
    try:
        trace = await _executor.resume(dag, metadata=merged_metadata)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store.save_trace(trace)
    store.update_dag(dag)
    return success_response(
        {
            "plan_id": plan_id,
            "status": trace.status,
            "completed_nodes": trace.completed_nodes,
            "visualization": dag.to_visualization(),
        }
    )


def _pending_nodes_from_dag(dag) -> list[str]:
    pending: list[str] = []
    for level in execution_levels(dag):
        for nid in level:
            node = dag.node_map()[nid]
            if not should_skip_node(node, dag) and node.status != "SUCCESS":
                pending.append(nid)
    return pending


@router.get("/checkpoint/{plan_id}", summary="查询 checkpoint 与 pending 边界")
async def get_plan_checkpoint(plan_id: str):
    store = get_plan_store()
    dag = store.get_plan(plan_id)
    if dag is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")

    checkpoint = get_checkpoint_store().load(plan_id)
    if checkpoint is None:
        raise HTTPException(
            status_code=404,
            detail=f"No checkpoint found for plan: {plan_id}",
        )

    from data_agent.agents.orchestrator.checkpoint import apply_checkpoint_to_dag

    dag_copy = dag.model_copy(deep=True)
    apply_checkpoint_to_dag(dag_copy, checkpoint)
    payload = CheckpointResponse(
        plan_id=plan_id,
        checkpoint=checkpoint.model_dump(mode="json"),
        pending_nodes=_pending_nodes_from_dag(dag_copy),
    )
    return success_response(payload.model_dump(mode="json"))


@router.get("/status/{plan_id}", summary="查询计划/执行状态")
async def get_plan_status(plan_id: str):
    store = get_plan_store()
    dag = store.get_plan(plan_id)
    if dag is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    status = store.get_status(plan_id) or "planned"
    payload = PlanStatusResponse(
        plan_id=plan_id,
        status=status,
        dag=dag,
        visualization=dag.to_visualization(),
    )
    return success_response(payload.model_dump(mode="json"))


@router.get("/trace/{plan_id}", summary="获取执行 Trace")
async def get_plan_trace(plan_id: str):
    store = get_plan_store()
    trace = store.get_trace(plan_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace not found for plan: {plan_id}")

    run_trace = get_trace_store().load(plan_id)
    parser_trace_summary = run_trace.parser_trace_summary if run_trace else None
    payload = TraceResponse(
        plan_id=plan_id,
        trace=trace,
        parser_trace_summary=parser_trace_summary,
    )
    return success_response(payload.model_dump(mode="json"))
