"""Task DAG data structure and graph algorithms."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from data_agent.agents.orchestrator.schemas import AgentRole, DAGEdge, DAGNode, TaskDAG, TaskType


def _edge(from_node: str, to_node: str) -> DAGEdge:
    return DAGEdge(from_node=from_node, to_node=to_node)


DomainDAGBuilder = Callable[[], tuple[list[DAGNode], list[DAGEdge]]]


def build_default_dag(
    plan_id: str,
    instruction: str,
    *,
    include_evaluation: bool = True,
    domain_builders: list[DomainDAGBuilder] | None = None,
    evaluation_depends_on: list[str] | None = None,
) -> TaskDAG:
    """Build the core data-processing DAG, optionally extended by domain builders."""
    nodes = [
        DAGNode(
            node_id="material_parse",
            task_type=TaskType.MATERIAL_PARSE.value,
            label="多格式材料解析",
            agent_role=AgentRole.PARSER.value,
            depends_on=[],
        ),
        DAGNode(
            node_id="data_structuring",
            task_type=TaskType.DATA_STRUCTURING.value,
            label="指代消解与语料净化",
            agent_role=AgentRole.DATA_STRUCTURING.value,
            depends_on=["material_parse"],
        ),
    ]
    edges = [_edge("material_parse", "data_structuring")]

    for builder in domain_builders or []:
        domain_nodes, domain_edges = builder()
        nodes.extend(domain_nodes)
        edges.extend(domain_edges)

    if include_evaluation:
        eval_deps = evaluation_depends_on
        if eval_deps is None:
            eval_deps = [nodes[-1].node_id] if nodes else []
        nodes.append(
            DAGNode(
                node_id="evaluation",
                task_type=TaskType.EVALUATION.value,
                label="跨链路稳定性汇总评分",
                agent_role=AgentRole.EVALUATOR.value,
                depends_on=eval_deps,
            )
        )
        edges.extend(_edge(dep, "evaluation") for dep in eval_deps)
    return TaskDAG(plan_id=plan_id, instruction=instruction, nodes=nodes, edges=edges)


def topological_sort(dag: TaskDAG) -> list[str]:
    """Return node ids in topological order; raise ValueError if cycle detected."""
    indegree: dict[str, int] = {n.node_id: 0 for n in dag.nodes}
    adj: dict[str, list[str]] = {n.node_id: [] for n in dag.nodes}
    for edge in dag.edges:
        adj[edge.from_node].append(edge.to_node)
        indegree[edge.to_node] = indegree.get(edge.to_node, 0) + 1

    queue: deque[str] = deque(nid for nid, deg in indegree.items() if deg == 0)
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for nxt in adj.get(nid, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(dag.nodes):
        raise ValueError("TaskDAG contains a cycle")
    return order


def execution_levels(dag: TaskDAG) -> list[list[str]]:
    """Group nodes into parallel execution levels (topological generations)."""
    order = topological_sort(dag)
    node_map = dag.node_map()
    level_of: dict[str, int] = {}
    for nid in order:
        deps = node_map[nid].depends_on
        level_of[nid] = max((level_of[d] for d in deps), default=-1) + 1
    max_level = max(level_of.values()) if level_of else 0
    levels: list[list[str]] = [[] for _ in range(max_level + 1)]
    for nid, lvl in level_of.items():
        levels[lvl].append(nid)
    return levels


def should_skip_node(node: DAGNode, dag: TaskDAG) -> bool:
    """True if already completed or any dependency failed/skipped."""
    if node.status == "SUCCESS":
        return True
    nm = dag.node_map()
    for dep_id in node.depends_on:
        dep = nm.get(dep_id)
        if dep is None:
            continue
        if dep.status in ("FAILED", "SKIPPED"):
            return True
    return False
