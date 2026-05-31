"""Tool routing: map sub-task types to execution handlers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from data_agent.agents.orchestrator.schemas import DAGNode, TaskType

logger = logging.getLogger(__name__)


@runtime_checkable
class ToolHandler(Protocol):
    """Uniform protocol for DAG node execution backends."""

    task_type: str

    async def execute(self, node: DAGNode, context: dict[str, Any]) -> dict[str, Any]:
        """Run the sub-task and return a JSON-serializable result."""
        ...


@dataclass
class ExecutionContext:
    """Shared mutable context passed across DAG node executions."""

    plan_id: str
    instruction: str
    metadata: dict[str, Any] = field(default_factory=dict)
    node_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    parser_fallback_logs: list[dict[str, Any]] = field(default_factory=list)


class MockToolHandler:
    """Deterministic mock handler for tests and API stubs."""

    def __init__(self, task_type: str | TaskType, *, should_fail: bool = False) -> None:
        self.task_type = task_type.value if hasattr(task_type, "value") else str(task_type)
        self.should_fail = should_fail

    async def execute(self, node: DAGNode, context: dict[str, Any]) -> dict[str, Any]:
        if self.should_fail:
            raise RuntimeError(f"mock failure for {node.node_id}")
        return {
            "status": "ok",
            "node_id": node.node_id,
            "task_type": self.task_type,
            "mock": True,
            "plan_id": context.get("plan_id"),
        }


def _parsed_document_from_context(
    parse_result: dict[str, Any],
    metadata: dict[str, Any],
) -> Any | None:
    """Extract ParsedDocument from upstream parse output or execute metadata."""
    from data_agent.parsing.schemas import ParsedDocument

    for key in ("document", "parsed_document"):
        raw = parse_result.get(key) or metadata.get(key)
        if raw is None:
            continue
        if isinstance(raw, ParsedDocument):
            return raw
        if isinstance(raw, dict):
            return ParsedDocument.model_validate(raw)
    raw_docs = parse_result.get("documents") or parse_result.get("parsed_documents")
    if isinstance(raw_docs, list) and raw_docs:
        first = raw_docs[0].get("document") if isinstance(raw_docs[0], dict) else raw_docs[0]
        if isinstance(first, ParsedDocument):
            return first
        if isinstance(first, dict):
            return ParsedDocument.model_validate(first)
    return None


def _parsed_documents_from_context(
    parse_result: dict[str, Any],
    metadata: dict[str, Any],
) -> list[Any]:
    """Extract all ParsedDocument objects from upstream parse output or metadata."""
    from data_agent.parsing.schemas import ParsedDocument

    out: list[ParsedDocument] = []
    raw_docs = parse_result.get("documents") or parse_result.get("parsed_documents")
    if isinstance(raw_docs, list):
        for raw in raw_docs:
            candidate = raw.get("document") if isinstance(raw, dict) else raw
            if isinstance(candidate, ParsedDocument):
                out.append(candidate)
            elif isinstance(candidate, dict):
                out.append(ParsedDocument.model_validate(candidate))
    if out:
        return out
    single = _parsed_document_from_context(parse_result, metadata)
    return [single] if single is not None else []


def _fast_structuring_modes(mode: str | None) -> bool:
    return str(mode or "").upper() in {"HIGH_SPEED", "QUICK", "LOCAL"}


def _structure_from_parse_artifact(
    parse_result: dict[str, Any],
    parse_artifact: dict[str, Any],
    *,
    node: DAGNode,
    context: dict[str, Any],
    metadata: dict[str, Any],
    documents: list[Any],
) -> dict[str, Any]:
    from data_agent.agents.inspector.schemas import EvaluationMetrics
    from data_agent.parsing.schemas import DocumentEvidencePool, DocumentIR, DocumentSectionTree, ReviewDocumentBundle

    mode = metadata.get("processing_mode", "OPTIMAL")
    section_tree = DocumentSectionTree.model_validate(parse_artifact.get("section_tree") or {})
    evidence_pool = DocumentEvidencePool.model_validate(parse_artifact.get("evidence_pool") or {})
    document_summaries: list[dict[str, Any]] = []
    warnings: list[str] = list(parse_artifact.get("warnings") or [])
    for item in parse_result.get("documents") or []:
        document_payload = item.get("document") or {}
        item_warnings = list(item.get("warnings") or []) + list(item.get("structuring_warnings") or [])
        warnings.extend(item_warnings)
        document_summaries.append(
            {
                "document_id": document_payload.get("document_id", ""),
                "file_name": item.get("file_name", ""),
                "file_type": item.get("file_type", ""),
                "parser_name": item.get("parser_name", ""),
                "parse_status": item.get("parse_status", ""),
                "block_count": int(item.get("block_count") or 0),
                "damaged_blocks": 0,
                "repaired_blocks": 0,
                "section_count": len(section_tree.sections),
                "evidence_count": len(evidence_pool.evidences),
                "warnings": item_warnings,
            }
        )

    bundle = ReviewDocumentBundle(
        parsed_documents=documents,
        section_tree=section_tree,
        evidence_pool=evidence_pool,
    )
    if parse_artifact.get("document_ir"):
        bundle.document_ir = DocumentIR.model_validate(parse_artifact["document_ir"])
    blocks_total = sum(summary["block_count"] for summary in document_summaries)
    section_count = len(section_tree.sections)
    evidence_count = len(evidence_pool.evidences)
    batch_summary = parse_artifact.get("batch_summary") or parse_result.get("batch_summary") or {}
    fallback_count = len(context.get("parser_fallback_logs") or [])
    degradation_count = int(batch_summary.get("degraded_count") or 0)
    metrics = EvaluationMetrics(
        blocks_total=blocks_total,
        damaged_blocks=0,
        fallback_count=fallback_count,
        anchor_total=section_count,
        anchor_covered=min(section_count, evidence_count),
        degradation_count=degradation_count,
    )
    extracted_parameters = parse_artifact.get("extracted_parameters") or []
    extracted_objects = parse_artifact.get("extracted_objects") or []
    trace_link_candidates = parse_artifact.get("trace_link_candidates") or []
    structured_bundle = {
            "documents": document_summaries,
            "section_tree": section_tree.model_dump(mode="json"),
            "evidence_pool": evidence_pool.model_dump(mode="json"),
            "document_ir": parse_artifact.get("document_ir") or bundle.document_ir.model_dump(mode="json"),
            "extracted_parameters": extracted_parameters,
            "extracted_objects": extracted_objects,
            "trace_link_candidates": trace_link_candidates,
            "traceability_matrix_summary": parse_artifact.get("traceability_matrix_summary") or {},
            "parse_artifact": parse_artifact,
            "stats": {
                "document_count": len(document_summaries),
                "blocks_total": blocks_total,
                "damaged_blocks": 0,
                "repaired_blocks": 0,
                "section_count": section_count,
                "evidence_count": evidence_count,
                "fallback_count": fallback_count,
                "degradation_count": degradation_count,
                "extracted_parameter_count": len(extracted_parameters),
                "extracted_object_count": len(extracted_objects),
                "trace_link_candidate_count": len(trace_link_candidates),
                "layout_block_count": len((parse_artifact.get("document_ir") or {}).get("layout_blocks") or []),
                "visual_element_count": len((parse_artifact.get("document_ir") or {}).get("visual_elements") or []),
                "table_element_count": len((parse_artifact.get("document_ir") or {}).get("table_elements") or []),
                "graph_element_count": len((parse_artifact.get("document_ir") or {}).get("graph_elements") or []),
                "chart_element_count": len((parse_artifact.get("document_ir") or {}).get("chart_elements") or []),
            },
    }
    return {
        "status": "ok",
        "node_id": node.node_id,
        "structuring_mode": mode,
        "mock": False,
        "reused_parse_artifact": True,
        "blocks_total": blocks_total,
        "damaged_blocks": 0,
        "repaired_blocks": 0,
        "document_count": len(document_summaries),
        "section_count": section_count,
        "evidence_count": evidence_count,
        "llm_call_count": 0,
        "warnings": warnings,
        "structured_bundle": structured_bundle,
        "parse_artifact": parse_artifact,
        "evaluation_metrics": metrics.model_dump(mode="json"),
    }


class StructuringToolHandler:
    """Routes to Task 1 SelfHealingPipeline (injectable for tests)."""

    task_type = TaskType.DATA_STRUCTURING.value

    def __init__(self, pipeline_runner: Any | None = None) -> None:
        self._pipeline_runner = pipeline_runner

    async def execute(self, node: DAGNode, context: dict[str, Any]) -> dict[str, Any]:
        parse_result = context.get("node_results", {}).get("material_parse", {})
        if self._pipeline_runner is not None:
            result = await self._pipeline_runner(parse_result, context)
            return {"status": "ok", "structuring": result, "mock": False}

        from data_agent.services.pipeline_runner import run_structuring_pipeline

        return await run_structuring_pipeline(parse_result, context, node=node)


class MaterialParseToolHandler:
    """Material parse with parser fallback chain."""

    task_type = TaskType.MATERIAL_PARSE.value

    def __init__(self, fallback_runner: Any | None = None) -> None:
        self._fallback_runner = fallback_runner

    async def execute(self, node: DAGNode, context: dict[str, Any]) -> dict[str, Any]:
        if self._fallback_runner is not None:
            result = await self._fallback_runner(context)
            logs = getattr(self._fallback_runner, "logs", [])
            context["parser_fallback_logs"] = [log.model_dump() for log in logs]
            return result
        metadata = context.get("metadata", {}) or {}
        from data_agent.parsing.materials import material_items_from_metadata
        from data_agent.services.pipeline_runner import run_material_parse_pipeline

        materials = material_items_from_metadata(metadata)
        result = await run_material_parse_pipeline(materials, metadata=metadata, node=node)
        if result.get("status") == "ok":
            context["parser_fallback_logs"] = list(result.get("parser_fallback_logs") or [])
        return result


class ToolRouter:
    """Resolve task type to handler instance."""

    def __init__(self, handlers: list[ToolHandler] | None = None) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        for h in default_handlers() if handlers is None else handlers:
            self._handlers[h.task_type] = h

    def register(self, handler: ToolHandler) -> None:
        self._handlers[handler.task_type] = handler

    def route(self, node: DAGNode) -> ToolHandler:
        handler = self._handlers.get(node.task_type)
        if handler is None:
            raise KeyError(f"No handler registered for task_type={node.task_type}")
        return handler

    async def execute_node(
        self,
        node: DAGNode,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        handler = self.route(node)
        logger.info("[ToolRouter] executing %s via %s", node.node_id, handler.task_type)
        return await handler.execute(node, context)


def default_handlers() -> list[ToolHandler]:
    from data_agent.agents.inspector.handler import EvaluationToolHandler

    return [
        MaterialParseToolHandler(),
        StructuringToolHandler(),
        EvaluationToolHandler(),
    ]
