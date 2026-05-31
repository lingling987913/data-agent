"""Planner assembly for the satellite review domain."""

from __future__ import annotations

from data_agent.agents.orchestrator.planner import CorePlanner
from data_agent.integrations.satellite_review.dag import build_satellite_dag_nodes
from data_agent.integrations.satellite_review.planner_rules import SKIP_GNC_RE, SKIP_RULE_RE


def build_satellite_review_planner() -> CorePlanner:
    """Return a CorePlanner configured with satellite review domain steps."""
    return CorePlanner(
        domain_builders=[build_satellite_dag_nodes],
        evaluation_depends_on=["rule_review", "gnc_review"],
        skip_rules={
            "rule_review": SKIP_RULE_RE,
            "gnc_review": SKIP_GNC_RE,
        },
    )
