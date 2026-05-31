"""Planner and handler adapter for GNC design review tasks."""

from __future__ import annotations

import asyncio
from typing import Any

from data_agent.agents.orchestrator.schemas import DAGEdge, DAGNode
from data_agent.integrations.satellite_review.gnc_schemas import GNCReviewRequest
from data_agent.integrations.satellite_review.schemas import SatelliteAgentRole, SatelliteTaskType


GNC_REVIEW_NODE_ID = "gnc_review"


def build_gnc_review_dag_nodes() -> tuple[list[DAGNode], list[DAGEdge]]:
    """Return the GNC review DAG node for satellite planner composition."""
    return (
        [
            DAGNode(
                node_id=GNC_REVIEW_NODE_ID,
                task_type=SatelliteTaskType.GNC_REVIEW.value,
                label="总体设计评审 (GNC)",
                agent_role=SatelliteAgentRole.GNC_REVIEW.value,
                depends_on=["slot_gatekeeping"],
            )
        ],
        [DAGEdge(from_node="slot_gatekeeping", to_node=GNC_REVIEW_NODE_ID)],
    )


class GNCReviewDAGHandler:
    """Execute a GNC review request from orchestrator context metadata."""

    task_type = SatelliteTaskType.GNC_REVIEW.value

    async def execute(self, node: DAGNode, context: dict[str, Any]) -> dict[str, Any]:
        del node
        metadata = context.get("metadata", {}) or {}
        adapter = metadata.get("gnc_adapter")
        if adapter is not None:
            result = adapter(context)
            if hasattr(result, "__await__"):
                result = await result
            return {"status": "ok", "workflow": "gnc", "mock": False, "result": result}

        request_payload = metadata.get("gnc_review_request")
        if not request_payload:
            return {
                "status": "skipped",
                "workflow": "gnc",
                "review_id": metadata.get("gnc_review_id", ""),
                "mock": False,
                "reason": "gnc_review_request not provided",
            }

        from data_agent.api.gnc_review_router import get_gnc_review_service

        request = GNCReviewRequest.model_validate(request_payload)
        svc = get_gnc_review_service()
        run = svc.create_review(request)
        result_run = await asyncio.to_thread(svc.start_review, run.review_id)
        return {
            "status": result_run.status,
            "workflow": "gnc",
            "review_id": result_run.review_id,
            "mock": False,
            "result": result_run.result.model_dump(mode="json") if result_run.result else None,
        }


__all__ = ["GNC_REVIEW_NODE_ID", "GNCReviewDAGHandler", "build_gnc_review_dag_nodes"]
