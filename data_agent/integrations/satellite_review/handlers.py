"""Satellite review domain tool handlers for DAG execution."""

from __future__ import annotations

from typing import Any

from data_agent.agents.orchestrator.schemas import DAGNode
from data_agent.integrations.satellite_review.gnc_planner import GNCReviewDAGHandler
from data_agent.integrations.satellite_review.schemas import SatelliteTaskType


def _metadata(context: dict[str, Any]) -> dict[str, Any]:
    return context.get("metadata", {}) or {}


def _review_id(context: dict[str, Any]) -> str:
    return str(_metadata(context).get("review_id") or "").strip()


class GatekeepingToolHandler:
    task_type = SatelliteTaskType.SLOT_GATEKEEPING.value

    async def execute(self, node: DAGNode, context: dict[str, Any]) -> dict[str, Any]:
        del node
        review_id = _review_id(context)
        if not review_id:
            return {
                "status": "skipped",
                "mock": False,
                "reason": "review_id not provided; domain gatekeeping was not invoked",
            }

        from data_agent.review_plus.service import get_review_plus_service

        task = get_review_plus_service().recheck_gatekeeping(review_id)
        if task is None:
            raise KeyError(f"Review-Plus task not found: {review_id}")
        return {
            "status": "ok",
            "review_id": review_id,
            "mock": False,
            "gatekeeping_result": task.gatekeeping_result,
        }


class ReviewPlusToolHandler:
    """Delegate satellite rule review to the Review-Plus service."""

    task_type = SatelliteTaskType.RULE_REVIEW.value

    async def execute(self, node: DAGNode, context: dict[str, Any]) -> dict[str, Any]:
        del node
        review_id = _review_id(context)
        if not review_id:
            return {
                "status": "skipped",
                "workflow": "review_plus",
                "mock": False,
                "reason": "review_id not provided; Review-Plus workflow was not invoked",
            }

        from data_agent.review_plus.service import get_review_plus_service

        svc = get_review_plus_service()
        task = svc.start_review(review_id)
        if task is None:
            raise KeyError(f"Review-Plus task not found: {review_id}")
        if _metadata(context).get("execute_review_plus_workflow", True):
            task = svc.continue_started_review(review_id) or task
        return {
            "status": "ok",
            "workflow": "review_plus",
            "review_id": review_id,
            "review_status": task.status,
            "mock": False,
            "findings_count": len(task.findings),
        }


class GNCReviewToolHandler(GNCReviewDAGHandler):
    """Delegate satellite GNC review to the migrated GNC workflow."""


def satellite_handlers() -> list[GatekeepingToolHandler | ReviewPlusToolHandler | GNCReviewToolHandler]:
    return [
        GatekeepingToolHandler(),
        ReviewPlusToolHandler(),
        GNCReviewToolHandler(),
    ]
