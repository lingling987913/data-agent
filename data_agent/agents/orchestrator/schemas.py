"""Pydantic models for task planning and DAG execution."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskNodeStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED"]

PlanStatus = Literal["planned", "running", "completed", "failed", "cancelled"]


class CoreTaskType(str, Enum):
    MATERIAL_PARSE = "material_parse"
    DATA_STRUCTURING = "data_structuring"
    EVALUATION = "evaluation"


class CoreAgentRole(str, Enum):
    PARSER = "parser_agent"
    DATA_STRUCTURING = "data_structuring_agent"
    EVALUATOR = "stability_evaluator_agent"


TaskType = CoreTaskType
AgentRole = CoreAgentRole


class DAGNode(BaseModel):
    """A single sub-task node in the execution DAG."""

    node_id: str
    task_type: str
    label: str
    agent_role: str
    status: TaskNodeStatus = "PENDING"
    depends_on: list[str] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    retry_count: int = 0


class DAGEdge(BaseModel):
    """Directed dependency edge between two nodes."""

    from_node: str
    to_node: str


class TaskDAG(BaseModel):
    """Directed acyclic graph of sub-tasks."""

    plan_id: str
    instruction: str
    nodes: list[DAGNode] = Field(default_factory=list)
    edges: list[DAGEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def node_map(self) -> dict[str, DAGNode]:
        return {n.node_id: n for n in self.nodes}

    def to_visualization(self) -> dict[str, Any]:
        """Frontend-friendly DAG snapshot."""
        return {
            "plan_id": self.plan_id,
            "instruction": self.instruction,
            "nodes": [
                {
                    "id": n.node_id,
                    "label": n.label,
                    "task_type": n.task_type,
                    "agent_role": n.agent_role,
                    "status": n.status,
                    "depends_on": n.depends_on,
                }
                for n in self.nodes
            ],
            "edges": [{"from": e.from_node, "to": e.to_node} for e in self.edges],
        }


class ParserFallbackLog(BaseModel):
    """Record of a parser degradation attempt."""

    timestamp: str
    source: str
    target: str
    reason: str
    recovered: bool
    retry_count: int = 0


class ExecutionTrace(BaseModel):
    """Full execution trace for a plan run."""

    plan_id: str
    instruction: str
    status: PlanStatus
    dag: TaskDAG
    parser_fallback_logs: list[ParserFallbackLog] = Field(default_factory=list)
    node_outputs: dict[str, Any] = Field(default_factory=dict)
    completed_nodes: list[str] = Field(default_factory=list)
    failed_node: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
