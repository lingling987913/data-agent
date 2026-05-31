"""GNC full-review pipeline satellite DAG nodes and edges."""

from __future__ import annotations

from data_agent.agents.orchestrator.schemas import DAGEdge, DAGNode
from data_agent.integrations.satellite_review.gnc_planner import build_gnc_review_dag_nodes
from data_agent.integrations.satellite_review.schemas import SatelliteAgentRole, SatelliteTaskType


def _edge(from_node: str, to_node: str) -> DAGEdge:
    return DAGEdge(from_node=from_node, to_node=to_node)


def build_satellite_dag_nodes() -> tuple[list[DAGNode], list[DAGEdge]]:
    """Return slot_gatekeeping, rule_review, and gnc_review nodes with dependency edges."""
    gnc_nodes, gnc_edges = build_gnc_review_dag_nodes()
    nodes = [
        DAGNode(
            node_id="slot_gatekeeping",
            task_type=SatelliteTaskType.SLOT_GATEKEEPING.value,
            label="槽位门禁复核",
            agent_role=SatelliteAgentRole.GATEKEEPING.value,
            depends_on=["data_structuring"],
        ),
        DAGNode(
            node_id="rule_review",
            task_type=SatelliteTaskType.RULE_REVIEW.value,
            label="规则合规审查 (Review-Plus)",
            agent_role=SatelliteAgentRole.REVIEW_PLUS.value,
            depends_on=["slot_gatekeeping"],
        ),
        *gnc_nodes,
    ]
    edges = [
        _edge("data_structuring", "slot_gatekeeping"),
        _edge("slot_gatekeeping", "rule_review"),
        *gnc_edges,
    ]
    return nodes, edges
