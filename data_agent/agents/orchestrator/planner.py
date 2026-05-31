"""CorePlanner: decompose high-level instructions into executable DAGs."""

from __future__ import annotations

import re
import uuid
from typing import Any, Pattern

from data_agent.agents.orchestrator.dag import DomainDAGBuilder
from data_agent.agents.orchestrator.dag import build_default_dag
from data_agent.agents.orchestrator.schemas import DAGEdge, TaskDAG
from data_agent.services.task_classifier import classify_for_planning


class CorePlanner:
    """
    Planning agent that turns a natural-language mission into a TaskDAG.

    Domain-specific DAG steps and keyword rules are injected by the
    application assembly layer.
    """

    _SKIP_EVAL_RE = re.compile(r"(跳过|不做|无需).{0,8}(评分|评测|evaluation)", re.I)
    _SPEED_RE = re.compile(r"(高速|快速|high[- ]?speed)", re.I)

    def __init__(
        self,
        *,
        domain_builders: list[DomainDAGBuilder] | None = None,
        evaluation_depends_on: list[str] | None = None,
        skip_rules: dict[str, Pattern[str]] | None = None,
    ) -> None:
        self._domain_builders = list(domain_builders or [])
        self._evaluation_depends_on = evaluation_depends_on
        self._skip_rules = dict(skip_rules or {})

    def plan(
        self,
        instruction: str,
        *,
        plan_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskDAG:
        """
        Generate an execution DAG for the given mission instruction.

        Args:
            instruction: e.g. "对这份工程文档进行全流程处理"
            plan_id: optional stable id; auto-generated if omitted
            metadata: optional hints (processing_mode, file_name, etc.)
        """
        pid = plan_id or str(uuid.uuid4())
        include_eval = not bool(self._SKIP_EVAL_RE.search(instruction))
        _, enriched_meta = classify_for_planning(instruction, metadata)
        dag = build_default_dag(
            pid,
            instruction.strip(),
            include_evaluation=include_eval,
            domain_builders=self._domain_builders,
            evaluation_depends_on=self._evaluation_depends_on,
        )

        route = str(enriched_meta.get("task_route") or "parse_only")
        if route == "parse_only":
            for node_id in ("slot_gatekeeping", "rule_review", "gnc_review"):
                self._remove_node(dag, node_id)
        elif route == "review_plus":
            self._remove_node(dag, "gnc_review")

        for node_id, pattern in self._skip_rules.items():
            if pattern.search(instruction):
                self._remove_node(dag, node_id)

        if self._SPEED_RE.search(instruction):
            enriched_meta.setdefault("processing_mode", "HIGH_SPEED")
            enriched_meta.setdefault("parser_type", "local")

        dag.metadata = enriched_meta
        return dag

    def _remove_node(self, dag: TaskDAG, node_id: str) -> None:
        dag.nodes = [n for n in dag.nodes if n.node_id != node_id]
        dag.edges = [
            e
            for e in dag.edges
            if e.from_node != node_id and e.to_node != node_id
        ]
        for node in dag.nodes:
            if node_id in node.depends_on:
                node.depends_on = [d for d in node.depends_on if d != node_id]
        self._rewire_evaluation_deps(dag)

    def _rewire_evaluation_deps(self, dag: TaskDAG) -> None:
        """Keep evaluation reachable when domain nodes are pruned from the DAG."""
        eval_node = next((n for n in dag.nodes if n.node_id == "evaluation"), None)
        if eval_node is None:
            return

        remaining_ids = {n.node_id for n in dag.nodes}
        eval_node.depends_on = [dep for dep in eval_node.depends_on if dep in remaining_ids]
        if eval_node.depends_on:
            dag.edges = [
                edge
                for edge in dag.edges
                if not (edge.to_node == "evaluation" and edge.from_node not in eval_node.depends_on)
            ]
            existing_from = {edge.from_node for edge in dag.edges if edge.to_node == "evaluation"}
            for dep in eval_node.depends_on:
                if dep not in existing_from:
                    dag.edges.append(DAGEdge(from_node=dep, to_node="evaluation"))
            return

        fallback = "data_structuring"
        if fallback not in remaining_ids:
            self._remove_node(dag, "evaluation")
            return

        eval_node.depends_on = [fallback]
        dag.edges = [edge for edge in dag.edges if edge.to_node != "evaluation"]
        dag.edges.append(DAGEdge(from_node=fallback, to_node="evaluation"))
