"""Shared execution kernel for Planning API and Task API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from data_agent.agents.orchestrator.executor import DAGExecutor
from data_agent.agents.orchestrator.planner import CorePlanner
from data_agent.agents.orchestrator.schemas import DAGNode, ExecutionTrace, TaskDAG
from data_agent.agents.orchestrator.tool_router import (
    ToolRouter,
    _fast_structuring_modes,
    _parsed_documents_from_context,
    _structure_from_parse_artifact,
    default_handlers,
)
from data_agent.domain.material_roles import MaterialRole, MaterialSummary, StructuredTaskResult, TaskScenario
from data_agent.evaluation.execution_metrics import build_execution_metrics_snapshot
from data_agent.evaluation.parser_trace_summary import build_parser_trace_summary
from data_agent.services.task_classifier import TaskClassificationResult, classify_for_planning, to_material_role

logger = logging.getLogger(__name__)


def build_planner() -> CorePlanner:
    from data_agent.integrations.satellite_review.planner import build_satellite_review_planner

    return build_satellite_review_planner()


def build_dag_executor() -> DAGExecutor:
    from data_agent.integrations.satellite_review.handlers import satellite_handlers

    handlers = default_handlers()
    handlers.extend(satellite_handlers())
    return DAGExecutor(ToolRouter(handlers))


async def run_material_parse_pipeline(
    materials: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None = None,
    node: DAGNode | None = None,
) -> dict[str, Any]:
    """Parse materials and build parse_artifact (shared by DAG and Task paths)."""
    from data_agent.parsing.parse_artifacts import (
        build_parse_only_artifact_from_parsed,
        parse_materials_to_batch,
    )

    meta = metadata or {}
    if not materials:
        return {
            "status": "skipped",
            "node_id": (node.node_id if node else "material_parse"),
            "parser_used": "",
            "blocks": 0,
            "mock": False,
            "reason": "no materials provided in execution metadata",
        }

    parsed = parse_materials_to_batch(
        materials,
        default_parser_type=str(meta.get("parser_type") or ""),
        default_processing_mode=meta.get("processing_mode"),
    )
    artifact = build_parse_only_artifact_from_parsed(parsed)
    artifact_dict = artifact.model_dump(mode="json")
    return {
        "status": "ok",
        "node_id": (node.node_id if node else "material_parse"),
        "mock": False,
        "parser_used": parsed["parser_used"],
        "blocks": parsed["blocks"],
        "material_count": parsed["material_count"],
        "warning_count": parsed["warning_count"],
        "documents": parsed["documents"],
        "document": parsed["document"],
        "parse_artifact": artifact_dict,
        "batch_summary": artifact_dict["batch_summary"],
        "parser_fallback_logs": parsed["parser_fallback_logs"],
    }


async def run_structuring_pipeline(
    parse_result: dict[str, Any],
    context: dict[str, Any],
    *,
    node: DAGNode | None = None,
) -> dict[str, Any]:
    """Structure parsed documents (SelfHealing or fast artifact reuse)."""
    metadata = context.get("metadata", {}) or {}
    node_id = node.node_id if node else "data_structuring"
    documents = _parsed_documents_from_context(parse_result, metadata)
    if not documents:
        return {
            "status": "skipped",
            "node_id": node_id,
            "structuring_mode": metadata.get("processing_mode", "OPTIMAL"),
            "mock": False,
            "message": "no parsed documents available for structuring",
        }

    mode = metadata.get("processing_mode", "OPTIMAL")
    parse_artifact = dict(parse_result.get("parse_artifact") or {})
    from data_agent.parsing.artifact_builder import (
        is_parse_artifact_complete,
        is_structure_artifact_complete,
    )
    from data_agent.parsing.parse_artifacts import (
        build_structure_artifact,
        merge_parse_and_structure,
    )

    if _fast_structuring_modes(mode) and is_parse_artifact_complete(parse_artifact):
        if not is_structure_artifact_complete(
            parse_artifact.get("section_tree"),
            parse_artifact.get("evidence_pool"),
            document_ir=parse_artifact.get("document_ir"),
        ):
            structure = build_structure_artifact(parse_artifact, documents=documents)
            parse_artifact = merge_parse_and_structure(parse_artifact, structure).model_dump(mode="json")
            parse_result = {**parse_result, "parse_artifact": parse_artifact}

    if is_structure_artifact_complete(
        parse_artifact.get("section_tree"),
        parse_artifact.get("evidence_pool"),
        document_ir=parse_artifact.get("document_ir"),
        parse_artifact=parse_artifact,
    ):
        return _structure_from_parse_artifact(
            parse_result,
            parse_artifact,
            node=node or DAGNode(
                node_id=node_id,
                task_type="data_structuring",
                label="structuring",
                agent_role="data_structuring_agent",
            ),
            context=context,
            metadata=metadata,
            documents=documents,
        )

    from data_agent.agents.inspector.cost_tracker import CostTracker
    from data_agent.agents.inspector.diff_recorder import DiffRecorder
    from data_agent.agents.inspector.schemas import EvaluationMetrics, RunTrace
    from data_agent.agents.inspector.trace_store import get_trace_store
    from data_agent.agents.format_guard.pipeline import SelfHealingPipeline
    from data_agent.parsing.schemas import DocumentEvidencePool, DocumentSectionTree, ReviewDocumentBundle
    from data_agent.parsing.artifact_builder import (
        attach_document_ir,
        attach_extracted_structured_objects,
        build_evidence_pool,
        prepare_document_ir,
    )
    from data_agent.parsing.parse_artifacts import merge_healed_parse_artifact

    plan_id = str(context.get("plan_id", ""))
    cost_tracker = CostTracker()
    diff_recorder = DiffRecorder()
    pipeline = SelfHealingPipeline()
    section_tree = DocumentSectionTree()
    evidence_pool = DocumentEvidencePool()
    bundle = ReviewDocumentBundle()
    structured_documents = []
    all_repair_records = []
    all_anaphora_records = []
    warnings: list[str] = []
    document_summaries: list[dict[str, Any]] = []
    damaged_count = 0
    repaired_count = 0

    for document in documents:
        result = await pipeline.run(
            document,
            processing_mode=mode,
            cost_tracker=cost_tracker,
        )
        pool = build_evidence_pool(
            result.section_tree,
            result.document,
            document_ir=prepare_document_ir(bundle, result.document),
        )
        structured_documents.append(result.document)
        section_tree.sections.extend(result.section_tree.sections)
        section_tree.root_section_ids.extend(result.section_tree.root_section_ids)
        section_tree.toc_entries.extend(result.section_tree.toc_entries)
        evidence_pool.evidences.extend(pool.evidences)
        all_repair_records.extend(result.repair_records)
        all_anaphora_records.extend(result.anaphora_records)
        warnings.extend(result.stats.warnings or [])
        damaged_count += result.stats.damaged_count
        repaired_count += result.stats.repaired_count
        document_summaries.append(
            {
                "document_id": result.document.document_id,
                "file_name": result.document.file_name,
                "file_type": result.document.file_type,
                "parser_name": result.document.parser_name,
                "parse_status": result.document.parse_status,
                "block_count": len(result.document.blocks),
                "damaged_blocks": result.stats.damaged_count,
                "repaired_blocks": result.stats.repaired_count,
                "section_count": len(result.section_tree.sections),
                "evidence_count": len(pool.evidences),
                "warnings": list(result.stats.warnings or []),
            }
        )

    healing_records = diff_recorder.record_repairs(all_repair_records)
    cost_summary = cost_tracker.summary()
    blocks_total = sum(summary["block_count"] for summary in document_summaries)
    section_count = len(section_tree.sections)
    evidence_count = len(evidence_pool.evidences)
    fallback_count = len(context.get("parser_fallback_logs") or [])
    degradation_count = sum(
        1
        for summary in document_summaries
        if summary["parse_status"] != "ok" or summary["warnings"]
    )
    metrics = EvaluationMetrics(
        blocks_total=blocks_total,
        damaged_blocks=damaged_count,
        fallback_count=fallback_count,
        anchor_total=section_count,
        anchor_covered=min(section_count, evidence_count),
        anaphora_attempts=len(all_anaphora_records),
        anaphora_resolved=sum(1 for item in all_anaphora_records if item.resolver_status == "ok"),
        degradation_count=degradation_count,
    )

    bundle = ReviewDocumentBundle(
        parsed_documents=structured_documents,
        section_tree=section_tree,
        evidence_pool=evidence_pool,
        document_ir=bundle.document_ir,
    )
    attach_document_ir(bundle)
    attach_extracted_structured_objects(bundle)

    structured_bundle = {
        "documents": document_summaries,
        "section_tree": section_tree.model_dump(mode="json"),
        "evidence_pool": evidence_pool.model_dump(mode="json"),
        "document_ir": bundle.document_ir.model_dump(mode="json"),
        "extracted_parameters": [item.model_dump(mode="json") for item in bundle.extracted_parameters],
        "extracted_objects": [item.model_dump(mode="json") for item in bundle.extracted_objects],
        "trace_link_candidates": [item.model_dump(mode="json") for item in bundle.trace_link_candidates],
        "traceability_matrix_summary": bundle.traceability_matrix_summary.model_dump(mode="json"),
        "stats": {
            "document_count": len(document_summaries),
            "blocks_total": blocks_total,
            "damaged_blocks": damaged_count,
            "repaired_blocks": repaired_count,
            "section_count": section_count,
            "evidence_count": evidence_count,
            "fallback_count": fallback_count,
            "degradation_count": degradation_count,
            "extracted_parameter_count": len(bundle.extracted_parameters),
            "extracted_object_count": len(bundle.extracted_objects),
            "trace_link_candidate_count": len(bundle.trace_link_candidates),
            "layout_block_count": len(bundle.document_ir.layout_blocks),
            "visual_element_count": len(bundle.document_ir.visual_elements),
            "table_element_count": len(bundle.document_ir.table_elements),
            "graph_element_count": len(bundle.document_ir.graph_elements),
            "chart_element_count": len(bundle.document_ir.chart_elements),
        },
    }
    merged_parse_artifact: dict[str, Any] = {}
    upstream_artifact = parse_artifact if isinstance(parse_artifact, dict) else {}
    if upstream_artifact:
        merged_parse_artifact = merge_healed_parse_artifact(
            upstream_artifact,
            structured_bundle=structured_bundle,
            document_summaries=document_summaries,
            warnings=warnings,
        )
        structured_bundle["parse_artifact"] = merged_parse_artifact

    store = get_trace_store()
    existing = store.load(plan_id)
    if existing is not None:
        existing.self_healing_records = healing_records
        existing.cost_summary = cost_summary
        existing.evaluation_metrics = metrics
        store.save(existing)
    else:
        store.save(
            RunTrace(
                plan_id=plan_id,
                self_healing_records=healing_records,
                cost_summary=cost_summary,
                evaluation_metrics=metrics,
            )
        )

    return {
        "status": "ok",
        "node_id": node_id,
        "structuring_mode": mode,
        "mock": False,
        "blocks_total": blocks_total,
        "damaged_blocks": damaged_count,
        "repaired_blocks": repaired_count,
        "document_count": len(document_summaries),
        "section_count": section_count,
        "evidence_count": evidence_count,
        "llm_call_count": cost_summary.llm_call_count,
        "warnings": warnings,
        "structured_bundle": structured_bundle,
        "parse_artifact": merged_parse_artifact,
        "merged_upstream_parse_artifact": bool(merged_parse_artifact),
        "evaluation_metrics": metrics.model_dump(mode="json"),
    }


def plan_dag(
    instruction: str,
    *,
    plan_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    planner: CorePlanner | None = None,
) -> TaskDAG:
    """Build a TaskDAG via CorePlanner with shared L0/L1 classification."""
    _, enriched = classify_for_planning(instruction, metadata)
    return (planner or build_planner()).plan(
        instruction,
        plan_id=plan_id,
        metadata=enriched,
    )


async def run_dag_pipeline(
    instruction: str,
    *,
    plan_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    planner: CorePlanner | None = None,
    executor: DAGExecutor | None = None,
) -> ExecutionTrace:
    """Plan and execute a full DAG (Planning API and Task DAG mode)."""
    meta = dict(metadata or {})
    if meta.get("materials"):
        _, meta = classify_for_planning(instruction, meta)
    dag = plan_dag(instruction, plan_id=plan_id, metadata=meta, planner=planner)
    dag.metadata = meta
    exec_ = executor or build_dag_executor()
    return await exec_.execute(dag, metadata=meta)


def run_dag_pipeline_sync(
    instruction: str,
    *,
    plan_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionTrace:
    """Sync wrapper for Task API executor thread (and pytest-asyncio contexts)."""
    import concurrent.futures

    def _run() -> ExecutionTrace:
        return asyncio.run(
            run_dag_pipeline(instruction, plan_id=plan_id, metadata=metadata)
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run).result()


def _role_from_classification(file_name: str, classification: TaskClassificationResult | None) -> MaterialRole:
    if classification:
        for item in classification.material_roles:
            if item.file_name == file_name:
                return to_material_role(item.role, file_name)
    return to_material_role("", file_name)


def map_dag_trace_to_task_result(
    trace: ExecutionTrace,
    *,
    task_id: str,
    scenario: TaskScenario,
    classification: TaskClassificationResult | None = None,
    package_id: str | None = None,
) -> dict[str, Any]:
    """Convert DAG ExecutionTrace into Task API StructuredTaskResult payload."""
    outputs = trace.node_outputs or {}
    material = outputs.get("material_parse") or {}
    structuring = outputs.get("data_structuring") or {}
    evaluation = outputs.get("evaluation") or {}

    structured_bundle = structuring.get("structured_bundle") or {}
    parse_artifact = (
        structuring.get("parse_artifact")
        or structured_bundle.get("parse_artifact")
        or material.get("parse_artifact")
        or {}
    )
    batch_summary = parse_artifact.get("batch_summary") or material.get("batch_summary") or {}
    file_results = parse_artifact.get("file_results") or []
    section_tree = structured_bundle.get("section_tree") or parse_artifact.get("section_tree") or {}
    evidence_pool = structured_bundle.get("evidence_pool") or parse_artifact.get("evidence_pool") or {}
    document_ir = structured_bundle.get("document_ir") or parse_artifact.get("document_ir") or {}
    if section_tree or evidence_pool:
        parse_artifact = {
            **parse_artifact,
            "section_tree": section_tree,
            "evidence_pool": evidence_pool,
            "document_ir": document_ir,
            "extracted_parameters": structured_bundle.get("extracted_parameters")
            or parse_artifact.get("extracted_parameters")
            or [],
            "extracted_objects": structured_bundle.get("extracted_objects")
            or parse_artifact.get("extracted_objects")
            or [],
            "trace_link_candidates": structured_bundle.get("trace_link_candidates")
            or parse_artifact.get("trace_link_candidates")
            or [],
            "traceability_matrix_summary": structured_bundle.get("traceability_matrix_summary")
            or parse_artifact.get("traceability_matrix_summary")
            or {},
        }

    materials: list[MaterialSummary] = []
    section_trees: dict[str, dict] = {}
    evidence_pools: dict[str, list] = {}
    traceability_summaries: dict[str, dict] = {}
    document_irs: dict[str, dict] = {}
    markdown_parts: list[str] = []
    parser_trace: list[dict[str, Any]] = []

    doc_summaries = structured_bundle.get("documents") or []
    if not doc_summaries:
        for item in material.get("documents") or []:
            doc_summaries.append(
                {
                    "file_name": item.get("file_name", ""),
                    "parser_name": item.get("parser_name", ""),
                    "parse_status": item.get("parse_status", "failed"),
                    "block_count": item.get("block_count", 0),
                    "section_count": len(section_tree.get("sections") or []),
                }
            )

    per_file_sections = section_tree.get("sections") or []
    for summary in doc_summaries:
        file_name = str(summary.get("file_name") or "")
        role = _role_from_classification(file_name, classification)
        materials.append(
            MaterialSummary(
                file_name=file_name,
                role=role,
                parser_name=str(summary.get("parser_name") or ""),
                parse_status=str(summary.get("parse_status") or "failed"),
                block_count=int(summary.get("block_count") or 0),
                section_count=int(summary.get("section_count") or len(per_file_sections)),
            )
        )
        if section_tree:
            section_trees[file_name] = section_tree
        if evidence_pool:
            evidence_pools[file_name] = list(evidence_pool.get("evidences") or [])
        if document_ir:
            document_irs[file_name] = document_ir
        traceability = structured_bundle.get("traceability_matrix_summary") or {}
        if traceability:
            traceability_summaries[file_name] = traceability
        parser_trace.append(
            {
                "parser": summary.get("parser_name") or "",
                "status": summary.get("parse_status") or "failed",
                "file_name": file_name,
            }
        )
        content = next(
            (
                str(item.get("content") or "")
                for item in material.get("documents") or []
                if item.get("file_name") == file_name
            ),
            "",
        )
        if content:
            markdown_parts.append(f"# {file_name}\n\n{content[:8000]}")

    for event in trace.parser_fallback_logs or []:
        payload = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        parser_trace.append({**payload, "kind": "parser_fallback"})

    quality_report = evaluation.get("quality_report")
    execution_metrics_snapshot = build_execution_metrics_snapshot(
        dag_result={
            "node_outputs": outputs,
            "batch_summary": batch_summary,
            "quality_report": quality_report,
            "evaluation_metrics": evaluation.get("evaluation_metrics"),
        }
    )
    parser_trace_summary = build_parser_trace_summary(
        parse_artifact=parse_artifact,
        parser_fallback_logs=[
            event.model_dump() if hasattr(event, "model_dump") else dict(event)
            for event in trace.parser_fallback_logs or []
        ],
        parser_traces=parser_trace,
    )

    warnings = list(structuring.get("warnings") or parse_artifact.get("warnings") or [])
    extracted_parameters = list(
        structured_bundle.get("extracted_parameters")
        or parse_artifact.get("extracted_parameters")
        or []
    )
    extracted_objects = list(
        structured_bundle.get("extracted_objects")
        or parse_artifact.get("extracted_objects")
        or []
    )
    trace_link_candidates = list(
        structured_bundle.get("trace_link_candidates")
        or parse_artifact.get("trace_link_candidates")
        or []
    )

    structured_output = {
        "materials": [m.model_dump() for m in materials],
        "check_items": [],
        "findings": [],
        "cross_doc_findings": [],
        "cross_package_compare": None,
        "tdms_metadata": None,
        "extracted_parameters": extracted_parameters,
        "extracted_objects": extracted_objects,
        "trace_link_candidates": trace_link_candidates,
        "traceability_summaries": traceability_summaries,
        "document_ir": document_irs,
        "parse_artifact": parse_artifact,
        "file_results": file_results,
        "batch_summary": batch_summary,
        "execution_metrics_snapshot": execution_metrics_snapshot,
        "parser_trace_summary": parser_trace_summary,
        "quality_report": quality_report,
        "conclusion": None,
        "execution_mode": "dag",
        "plan_id": trace.plan_id,
        "dag_status": trace.status,
        "node_outputs": outputs,
    }

    result = StructuredTaskResult(
        scenario=scenario,
        package_id=package_id,
        materials=materials,
        check_items=[],
        findings=[],
        cross_doc_findings=[],
        review_report_markdown=None,
        review_conclusion=None,
        cross_package_compare=None,
        tdms_metadata=None,
        structured_output=structured_output,
        markdown_output="\n\n---\n\n".join(markdown_parts) if markdown_parts else None,
        section_trees=section_trees,
        evidence_pools=evidence_pools,
        warnings=warnings,
        parser_trace=parser_trace,
    )
    return result.model_dump(mode="json")


_DAG_UNSUPPORTED_SCENARIOS = frozenset(
    {
        TaskScenario.CROSS_PACKAGE_COMPARE,
        TaskScenario.PACKAGE_REVIEW,
    }
)


def should_use_dag_for_scenario(scenario: TaskScenario) -> bool:
    """Return whether Task API ``use_dag`` may run the shared DAG pipeline.

    Supported: ``SINGLE_DOC_PARSE`` (material_parse → data_structuring → …).

    Unsupported (falls back to legacy path even when ``use_dag=true``):
    - ``CROSS_PACKAGE_COMPARE``: dual Review-Plus packages + ``compare_document_packages``.
    - ``PACKAGE_REVIEW``: ten-step Review-Plus Agno workflow (``run_review_plus_package``).
    """
    return scenario not in _DAG_UNSUPPORTED_SCENARIOS
