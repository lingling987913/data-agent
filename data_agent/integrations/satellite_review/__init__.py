"""Satellite GNC review domain integration for orchestrator DAG and tools."""

from data_agent.integrations.satellite_review.schemas import SatelliteAgentRole, SatelliteTaskType

__all__ = [
    "SatelliteAgentRole",
    "SatelliteTaskType",
    "GNCReviewToolHandler",
    "GatekeepingToolHandler",
    "ReviewPlusToolHandler",
    "build_satellite_dag_nodes",
    "build_satellite_review_planner",
    "satellite_handlers",
]


def __getattr__(name: str):
    if name == "build_satellite_dag_nodes":
        from data_agent.integrations.satellite_review.dag import build_satellite_dag_nodes

        return build_satellite_dag_nodes
    if name == "build_satellite_review_planner":
        from data_agent.integrations.satellite_review.planner import build_satellite_review_planner

        return build_satellite_review_planner
    if name in ("GNCReviewToolHandler", "GatekeepingToolHandler", "ReviewPlusToolHandler", "satellite_handlers"):
        from data_agent.integrations.satellite_review import handlers

        return getattr(handlers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
