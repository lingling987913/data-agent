"""Parse-only artifact models and builders.

This module is intentionally independent from task/review service orchestration.
It accepts already parsed batch payloads and builds the reusable parse artifact
shape consumed by structuring and review workflows.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from data_agent.agents.format_guard.mode_policy import resolve_parser_type
from data_agent.parsing.materials import material_file_name
from data_agent.parsing.schemas import DocumentEvidence, DocumentIR, DocumentSection, ParsedDocument, ReviewDocumentBundle

PARSE_PREVIEW_INFO_WARNINGS = frozenset({"postprocess skipped for parse preview"})

_INFO_ONLY_PARSE_WARNING_PATTERNS = (
    re.compile(r"^MinerU local backend=", re.IGNORECASE),
    re.compile(r"^已合并 \d+ 组跨页表格。$"),
    re.compile(r"^解析前已将.+校正为纵向.*"),
    re.compile(r"^解析前已将.+旋转为纵向。$"),
)


def is_info_only_parse_warning(warning: str) -> bool:
    """Warnings that must not mark a parse as degraded (observability / success notes)."""
    normalized = warning.strip()
    if not normalized:
        return True
    if normalized in PARSE_PREVIEW_INFO_WARNINGS:
        return True
    return any(pattern.search(normalized) for pattern in _INFO_ONLY_PARSE_WARNING_PATTERNS)


logger = logging.getLogger(__name__)


class ParseFileResult(BaseModel):
    file_name: str
    file_type: str = ""
    parser_selected: str = ""
    parser_chain: list[str] = Field(default_factory=list)
    parse_status: str = "failed"
    capability_passed: bool = False
    degraded: bool = False
    warnings: list[str] = Field(default_factory=list)
    document_ir_stats: dict[str, int] = Field(default_factory=dict)


class ParseBatchSummary(BaseModel):
    file_count: int = 0
    parsed_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0
    execution_pass_rate: float = 0.0
    capability_pass_rate: float = 0.0
    degradation_rate: float = 0.0


class ParseOnlyArtifact(BaseModel):
    """Step 3 output: parse + Document IR only (no section tree / evidence pool)."""

    artifact_id: str = Field(default_factory=lambda: f"parse-{uuid.uuid4().hex[:12]}")
    pipeline_step: str = "document_parse"
    file_results: list[ParseFileResult] = Field(default_factory=list)
    batch_summary: ParseBatchSummary = Field(default_factory=ParseBatchSummary)
    parsed_documents: list[dict[str, Any]] = Field(default_factory=list)
    document_ir: dict[str, Any] = Field(default_factory=dict)
    parser_trace: list[dict[str, Any]] = Field(default_factory=list)
    parse_quality_report: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class StructureArtifact(BaseModel):
    """Step 3.5 output: structuring built from a parse-only artifact."""

    structure_artifact_id: str = Field(default_factory=lambda: f"struct-{uuid.uuid4().hex[:12]}")
    parse_artifact_id: str = ""
    pipeline_step: str = "document_structuring"
    section_tree: dict[str, Any] = Field(default_factory=dict)
    evidence_pool: dict[str, Any] = Field(default_factory=dict)
    extracted_parameters: list[dict[str, Any]] = Field(default_factory=list)
    extracted_objects: list[dict[str, Any]] = Field(default_factory=list)
    trace_link_candidates: list[dict[str, Any]] = Field(default_factory=list)
    traceability_matrix_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ParseArtifact(BaseModel):
    """Combined parse + structure artifact (backward-compatible aggregate)."""

    artifact_id: str = Field(default_factory=lambda: f"parse-{uuid.uuid4().hex[:12]}")
    pipeline_step: str = "parse_and_structure"
    file_results: list[ParseFileResult] = Field(default_factory=list)
    batch_summary: ParseBatchSummary = Field(default_factory=ParseBatchSummary)
    parsed_documents: list[dict[str, Any]] = Field(default_factory=list)
    document_ir: dict[str, Any] = Field(default_factory=dict)
    section_tree: dict[str, Any] = Field(default_factory=dict)
    evidence_pool: dict[str, Any] = Field(default_factory=dict)
    extracted_parameters: list[dict[str, Any]] = Field(default_factory=list)
    extracted_objects: list[dict[str, Any]] = Field(default_factory=list)
    trace_link_candidates: list[dict[str, Any]] = Field(default_factory=list)
    traceability_matrix_summary: dict[str, Any] = Field(default_factory=dict)
    parse_quality_report: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def meaningful_parse_warnings(warnings: list[str]) -> list[str]:
    return [warning for warning in warnings if not is_info_only_parse_warning(warning)]


def document_ir_stats(document: ParsedDocument | None) -> dict[str, int]:
    from data_agent.parsing.artifact_builder import attach_document_ir

    if not document:
        return {}
    bundle = ReviewDocumentBundle(parsed_documents=[document])
    attach_document_ir(bundle)
    ir: DocumentIR = bundle.document_ir
    return {
        "layout_block_count": len(ir.layout_blocks),
        "page_count": len(ir.pages),
        "visual_element_count": len(ir.visual_elements),
        "table_element_count": len(ir.table_elements),
        "graph_element_count": len(ir.graph_elements),
        "chart_element_count": len(ir.chart_elements),
    }


def calibration_quality_summary(documents: list[ParsedDocument]) -> dict[str, Any]:
    records = [
        record
        for document in documents
        for record in (document.calibration_records or [])
    ]
    compact_records = [
        {
            "file_name": document.file_name,
            "block_id": record.block_id,
            "page_hint": record.page_hint,
            "issue_type": record.issue_type,
            "severity": record.severity,
            "suggested_text": record.suggested_text,
            "reason": record.reason,
            "confidence": record.confidence,
            "status": record.status,
        }
        for document in documents
        for record in (document.calibration_records or [])
    ]
    return {
        "issue_count": len(records),
        "high_severity_count": sum(1 for record in records if record.severity == "critical"),
        "needs_review_count": sum(1 for record in records if record.status == "needs_review"),
        "records": compact_records[:50],
    }


def parser_chain(item: dict[str, Any]) -> list[str]:
    chain: list[str] = []
    for event in item.get("parser_fallback_logs") or []:
        source = str(event.get("source_parser") or "")
        fallback = str(event.get("fallback_parser") or "")
        if source and source not in chain:
            chain.append(source)
        if fallback and fallback not in chain:
            chain.append(fallback)
    parser_name = str(item.get("parser_name") or "")
    if parser_name and parser_name not in chain:
        chain.append(parser_name)
    return chain


def collect_parse_batch(
    parsed: dict[str, Any],
) -> tuple[list[ParsedDocument], list[ParseFileResult], list[dict[str, Any]], list[str]]:
    documents: list[ParsedDocument] = []
    file_results: list[ParseFileResult] = []
    parsed_documents: list[dict[str, Any]] = []
    warnings: list[str] = []

    for item in parsed.get("documents") or []:
        document_payload = item.get("document")
        document = ParsedDocument.model_validate(document_payload) if document_payload else None
        if document:
            documents.append(document)
        parsed_documents.append(dict(item))
        item_warnings = list(item.get("warnings") or []) + list(item.get("structuring_warnings") or [])
        meaningful_warnings = meaningful_parse_warnings(item_warnings)
        warnings.extend(f"[{item.get('file_name', '')}] {warning}" for warning in meaningful_warnings)
        status = str(item.get("parse_status") or "failed")
        degraded = status != "ok" or bool(meaningful_warnings)
        file_results.append(
            ParseFileResult(
                file_name=str(item.get("file_name") or ""),
                file_type=str(item.get("file_type") or ""),
                parser_selected=str(item.get("parser_name") or ""),
                parser_chain=parser_chain(item),
                parse_status=status,
                capability_passed=status == "ok" and not degraded,
                degraded=degraded,
                warnings=item_warnings,
                document_ir_stats=document_ir_stats(document),
            )
        )
    return documents, file_results, parsed_documents, warnings


def batch_summary_from_file_results(file_results: list[ParseFileResult]) -> ParseBatchSummary:
    file_count = len(file_results)
    parsed_count = sum(1 for item in file_results if item.parse_status != "failed")
    degraded_count = sum(1 for item in file_results if item.degraded)
    failed_count = sum(1 for item in file_results if item.parse_status == "failed")
    capability_count = sum(1 for item in file_results if item.capability_passed)
    return ParseBatchSummary(
        file_count=file_count,
        parsed_count=parsed_count,
        degraded_count=degraded_count,
        failed_count=failed_count,
        execution_pass_rate=round(parsed_count / file_count, 4) if file_count else 0.0,
        capability_pass_rate=round(capability_count / file_count, 4) if file_count else 0.0,
        degradation_rate=round(degraded_count / file_count, 4) if file_count else 0.0,
    )


def document_ir_only_bundle(documents: list[ParsedDocument]) -> ReviewDocumentBundle:
    from data_agent.parsing.artifact_builder import attach_document_ir

    bundle = ReviewDocumentBundle(parsed_documents=list(documents))
    attach_document_ir(bundle)
    return bundle


def build_parse_only_artifact_from_parsed(parsed: dict[str, Any]) -> ParseOnlyArtifact:
    """Build a parse-only artifact from a parsed batch payload."""
    documents, file_results, parsed_documents, warnings = collect_parse_batch(parsed)
    ir_bundle = document_ir_only_bundle(documents)
    summary = batch_summary_from_file_results(file_results)
    calibration = calibration_quality_summary(documents)
    parser_trace: list[dict[str, Any]] = []
    for item in parsed.get("documents") or []:
        parser_trace.extend(item.get("parser_fallback_logs") or [])
    return ParseOnlyArtifact(
        file_results=file_results,
        batch_summary=summary,
        parsed_documents=parsed_documents,
        document_ir=ir_bundle.document_ir.model_dump(mode="json"),
        parser_trace=parser_trace,
        parse_quality_report={
            "status": "degraded" if summary.degraded_count or summary.failed_count else "ok",
            "warnings": warnings,
            "execution_pass_rate": summary.execution_pass_rate,
            "capability_pass_rate": summary.capability_pass_rate,
            "degradation_rate": summary.degradation_rate,
            "calibration": calibration,
        },
        warnings=warnings,
    )


def _tdms_batch_item(file_name: str, file_path: str) -> dict[str, Any]:
    from data_agent.domain.tdms_extractor import extract_tdms_metadata

    tdms_metadata = extract_tdms_metadata(file_path)
    tdms_warnings = [
        str(value)
        for key in ("warning", "error")
        if (value := tdms_metadata.get(key))
    ]
    return {
        "file_name": file_name,
        "file_type": "engineering_data",
        "parse_status": str(tdms_metadata.get("parse_status") or "degraded"),
        "parser_name": str(tdms_metadata.get("parser_name") or "tdms_metadata"),
        "block_count": int(tdms_metadata.get("channel_count") or 0),
        "content": (
            "[TDMS metadata] "
            f"file={tdms_metadata.get('file_name')} "
            f"size={tdms_metadata.get('file_size_bytes')} "
            f"channels={tdms_metadata.get('channel_count', 'unknown')}"
        ),
        "warnings": tdms_warnings,
        "structuring_warnings": [],
        "parser_fallback_logs": [
            {
                "source_parser": "tdms",
                "fallback_parser": str(tdms_metadata.get("parser_name") or "tdms_metadata"),
                "reason": "engineering data handled by TDMS metadata adapter",
            }
        ],
        "self_healing_records": [],
        "document": None,
        "tdms_metadata": tdms_metadata,
    }


def _parse_material_to_batch_item(item: dict[str, Any]) -> dict[str, Any]:
    from data_agent.parsing.application_service import ParseDocumentCommand, parse_document

    file_path = str(item.get("file_path") or item.get("path") or "").strip()
    content = item.get("content")
    temp_path = ""
    if not file_path and content is not None:
        suffix = Path(material_file_name(item)).suffix or ".md"
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(content))
        file_path = temp_path

    file_name = material_file_name(item, file_path)
    parser_type = str(item.get("parser_type") or "")
    processing_mode = item.get("processing_mode") or "HIGH_SPEED"
    if not parser_type:
        parser_type = resolve_parser_type(file_name, str(processing_mode))

    from data_agent.parsing.material_parser_route import resolve_material_parser_route

    route = resolve_material_parser_route(
        file_name,
        parser_type,
        str(processing_mode) if processing_mode else None,
    )
    parser_type = route.parser_type
    processing_mode = route.processing_mode or processing_mode

    try:
        if file_name.lower().endswith(".tdms"):
            return _tdms_batch_item(file_name, file_path)

        payload = parse_document(
            ParseDocumentCommand(
                file_path=file_path,
                file_name=file_name,
                parser_type=parser_type,
                processing_mode=str(processing_mode) if processing_mode else None,
                mineru_parse_mode=str(item.get("mineru_parse_mode") or "") or None,
                include_document=True,
                include_artifact=False,
                skip_enhancement=bool(item.get("skip_enhancement", True) or item.get("parse_preview")),
                figure_storage_dir=str(item.get("figure_storage_dir") or "") or None,
            )
        )
    except Exception as exc:
        logger.warning("failed to parse material %s: %s", file_name, exc)
        return {
            "file_name": file_name,
            "file_type": Path(file_name).suffix.lower().lstrip("."),
            "parse_status": "failed",
            "parser_name": parser_type or "auto",
            "block_count": 0,
            "content": "",
            "warnings": [f"parse_error: {exc}"],
            "structuring_warnings": [],
            "parser_fallback_logs": [
                {
                    "source_parser": parser_type or "auto",
                    "fallback_parser": "none",
                    "reason": str(exc),
                }
            ],
            "self_healing_records": [],
            "document": None,
        }
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                logger.debug("failed to remove temporary material %s", temp_path)

    document_payload = payload.get("document")
    document = ParsedDocument.model_validate(document_payload) if document_payload else None
    document_warnings = list(document.warnings or []) if document else []
    document_structuring_warnings = list(document.structuring_warnings or []) if document else []
    warnings = list(payload.get("warnings") or document_warnings)
    return {
        "file_name": file_name,
        "file_type": str(payload.get("file_type") or ""),
        "parse_status": str(payload.get("parse_status") or "failed"),
        "parser_name": str(payload.get("parser_name") or ""),
        "block_count": len(document.blocks) if document else 0,
        "content": str(payload.get("content") or ""),
        "warnings": warnings,
        "structuring_warnings": document_structuring_warnings,
        "parser_fallback_logs": list(payload.get("parser_fallback_logs") or []),
        "self_healing_records": list(payload.get("self_healing_records") or []),
        "document": document_payload,
    }


def parse_materials_to_batch(
    materials: list[dict[str, Any]],
    *,
    max_workers: int | None = None,
    default_parser_type: str = "",
    default_processing_mode: str | None = None,
) -> dict[str, Any]:
    """Parse materials concurrently and return the normalized parsed-batch payload."""
    if not materials:
        return {
            "parser_used": "",
            "blocks": 0,
            "material_count": 0,
            "warning_count": 0,
            "documents": [],
            "document": None,
            "parser_fallback_logs": [],
        }

    parse_inputs: list[dict[str, Any]] = []
    for material in materials:
        item = dict(material)
        if default_parser_type and not item.get("parser_type"):
            item["parser_type"] = default_parser_type
        if default_processing_mode and not item.get("processing_mode"):
            item["processing_mode"] = default_processing_mode
        parse_inputs.append(item)

    if len(parse_inputs) == 1:
        parsed_items = [_parse_material_to_batch_item(parse_inputs[0])]
    else:
        from contextvars import copy_context

        worker_count = max_workers or min(8, max(1, len(parse_inputs)))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            parsed_items = list(
                pool.map(
                    lambda item: copy_context().run(_parse_material_to_batch_item, item),
                    parse_inputs,
                )
            )

    fallback_logs = [
        log
        for item in parsed_items
        for log in item.get("parser_fallback_logs", [])
    ]
    first = parsed_items[0] if parsed_items else {}
    return {
        "parser_used": first.get("parser_name", ""),
        "blocks": sum(int(item.get("block_count") or 0) for item in parsed_items),
        "material_count": len(parsed_items),
        "warning_count": sum(
            len(item.get("warnings") or []) + len(item.get("structuring_warnings") or [])
            for item in parsed_items
        ),
        "documents": parsed_items,
        "document": first.get("document"),
        "parser_fallback_logs": fallback_logs,
    }


def build_parse_only_artifact_from_materials(
    materials: list[dict[str, Any]],
    *,
    max_workers: int | None = None,
) -> ParseOnlyArtifact:
    """Parse materials concurrently and build a parse-only artifact."""
    return build_parse_only_artifact_from_parsed(
        parse_materials_to_batch(materials, max_workers=max_workers)
    )


def build_structured_bundle_from_documents(documents: list[ParsedDocument]) -> ReviewDocumentBundle:
    from data_agent.parsing.artifact_builder import (
        attach_document_ir,
        attach_extracted_structured_objects,
        build_evidence_pool,
        build_sections,
        prepare_document_ir,
    )

    bundle = ReviewDocumentBundle()
    for document in documents:
        bundle.parsed_documents.append(document)
        if not document.blocks:
            continue
        tree = build_sections(document)
        if not tree.sections:
            text = "\n\n".join(block.text for block in document.blocks if block.text).strip()
            if text:
                section_id = f"sec-{uuid.uuid4().hex[:12]}"
                tree.sections.append(
                    DocumentSection(
                        section_id=section_id,
                        title=document.file_name or "document",
                        level=1,
                        start_block_index=0,
                        end_block_index=max(len(document.blocks) - 1, 0),
                        text=text,
                        source_file_name=document.file_name,
                    )
                )
                tree.root_section_ids.append(section_id)
        doc_ir = prepare_document_ir(bundle, document)
        pool = build_evidence_pool(tree, document, document_ir=doc_ir)
        if not pool.evidences and tree.sections:
            section = tree.sections[0]
            pool.evidences.append(
                DocumentEvidence(
                    evidence_id=uuid.uuid4().hex[:12],
                    source_type="document_excerpt",
                    section_id=section.section_id,
                    block_ids=[block.block_id for block in document.blocks[:8]],
                    source_file_name=document.file_name,
                    excerpt=section.text[:1200],
                )
            )
        bundle.section_tree.sections.extend(tree.sections)
        bundle.section_tree.root_section_ids.extend(tree.root_section_ids)
        bundle.section_tree.toc_entries.extend(tree.toc_entries)
        bundle.evidence_pool.evidences.extend(pool.evidences)
    attach_document_ir(bundle)
    attach_extracted_structured_objects(bundle)
    return bundle


def merge_healed_parse_artifact(
    upstream: dict[str, Any],
    *,
    structured_bundle: dict[str, Any],
    document_summaries: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    """Merge upstream parse_artifact with post-SelfHealing structured bundle stats."""
    stats = structured_bundle.get("stats") or {}
    file_results = list(upstream.get("file_results") or [])
    file_count = len(file_results) or int(stats.get("document_count") or 0) or len(document_summaries)
    failed_count = sum(1 for item in file_results if item.get("parse_status") == "failed")
    if not failed_count:
        failed_count = sum(1 for item in document_summaries if item.get("parse_status") == "failed")
    parsed_count = max(0, file_count - failed_count)
    damaged_blocks = int(stats.get("damaged_blocks") or 0)
    degradation_count = int(stats.get("degradation_count") or 0)
    if not degradation_count:
        degradation_count = sum(
            1
            for item in document_summaries
            if item.get("parse_status") != "ok" or item.get("warnings") or item.get("damaged_blocks")
        )
    if damaged_blocks and degradation_count < file_count:
        degradation_count = max(degradation_count, min(file_count, damaged_blocks))
    capability_count = sum(
        1
        for item in document_summaries
        if item.get("parse_status") == "ok" and not item.get("warnings") and not item.get("damaged_blocks")
    )
    if not capability_count and parsed_count and not degradation_count:
        capability_count = parsed_count
    merged_warnings = list(dict.fromkeys([*(upstream.get("warnings") or []), *warnings]))
    batch_summary = {
        "file_count": file_count,
        "parsed_count": parsed_count,
        "degraded_count": degradation_count,
        "failed_count": failed_count,
        "execution_pass_rate": round(parsed_count / file_count, 4) if file_count else 0.0,
        "capability_pass_rate": round(capability_count / file_count, 4) if file_count else 0.0,
        "degradation_rate": round(degradation_count / file_count, 4) if file_count else 0.0,
    }
    return {
        **upstream,
        "batch_summary": batch_summary,
        "section_tree": structured_bundle.get("section_tree") or upstream.get("section_tree") or {},
        "evidence_pool": structured_bundle.get("evidence_pool") or upstream.get("evidence_pool") or {},
        "document_ir": structured_bundle.get("document_ir") or upstream.get("document_ir") or {},
        "extracted_parameters": structured_bundle.get("extracted_parameters") or upstream.get("extracted_parameters") or [],
        "extracted_objects": structured_bundle.get("extracted_objects") or upstream.get("extracted_objects") or [],
        "trace_link_candidates": structured_bundle.get("trace_link_candidates")
        or upstream.get("trace_link_candidates")
        or [],
        "traceability_matrix_summary": structured_bundle.get("traceability_matrix_summary")
        or upstream.get("traceability_matrix_summary")
        or {},
        "parse_quality_report": {
            "status": "degraded" if degradation_count or failed_count else "ok",
            "warnings": merged_warnings,
            **batch_summary,
        },
        "warnings": merged_warnings,
        "healing_stats": {
            "damaged_blocks": damaged_blocks,
            "repaired_blocks": int(stats.get("repaired_blocks") or 0),
            "blocks_total": int(stats.get("blocks_total") or 0),
        },
    }


def build_structure_artifact(
    parse_artifact: ParseOnlyArtifact | dict[str, Any],
    *,
    documents: list[ParsedDocument] | None = None,
) -> StructureArtifact:
    """Build section tree and evidence pool from a parse-only artifact."""
    if isinstance(parse_artifact, ParseOnlyArtifact):
        parse_id = parse_artifact.artifact_id
        parsed_documents = parse_artifact.parsed_documents
        base_warnings = list(parse_artifact.warnings)
    else:
        parse_id = str(parse_artifact.get("artifact_id") or "")
        parsed_documents = list(parse_artifact.get("parsed_documents") or parse_artifact.get("documents") or [])
        base_warnings = list(parse_artifact.get("warnings") or [])

    if documents is None:
        documents = []
        for item in parsed_documents:
            document_payload = item.get("document") if isinstance(item, dict) else None
            if document_payload:
                documents.append(ParsedDocument.model_validate(document_payload))

    bundle = build_structured_bundle_from_documents(documents)
    return StructureArtifact(
        parse_artifact_id=parse_id,
        section_tree=bundle.section_tree.model_dump(mode="json"),
        evidence_pool=bundle.evidence_pool.model_dump(mode="json"),
        extracted_parameters=[item.model_dump(mode="json") for item in bundle.extracted_parameters],
        extracted_objects=[item.model_dump(mode="json") for item in bundle.extracted_objects],
        trace_link_candidates=[item.model_dump(mode="json") for item in bundle.trace_link_candidates],
        traceability_matrix_summary=bundle.traceability_matrix_summary.model_dump(mode="json"),
        warnings=base_warnings,
    )


def merge_parse_and_structure(
    parse_only: ParseOnlyArtifact | dict[str, Any],
    structure: StructureArtifact | dict[str, Any],
) -> ParseArtifact:
    """Combine parse-only and structure artifacts into the legacy aggregate shape."""
    if isinstance(parse_only, ParseOnlyArtifact):
        parse_payload = parse_only.model_dump(mode="json")
    else:
        parse_payload = dict(parse_only)
    if isinstance(structure, StructureArtifact):
        structure_payload = structure.model_dump(mode="json")
    else:
        structure_payload = dict(structure)
    merged_warnings = list(
        dict.fromkeys([*(parse_payload.get("warnings") or []), *(structure_payload.get("warnings") or [])])
    )
    return ParseArtifact(
        artifact_id=str(parse_payload.get("artifact_id") or ""),
        pipeline_step="parse_and_structure",
        file_results=parse_payload.get("file_results") or [],
        batch_summary=parse_payload.get("batch_summary") or {},
        parsed_documents=parse_payload.get("parsed_documents") or [],
        document_ir=parse_payload.get("document_ir") or {},
        section_tree=structure_payload.get("section_tree") or {},
        evidence_pool=structure_payload.get("evidence_pool") or {},
        extracted_parameters=structure_payload.get("extracted_parameters") or [],
        extracted_objects=structure_payload.get("extracted_objects") or [],
        trace_link_candidates=structure_payload.get("trace_link_candidates") or [],
        traceability_matrix_summary=structure_payload.get("traceability_matrix_summary") or {},
        parse_quality_report=parse_payload.get("parse_quality_report") or {},
        warnings=merged_warnings,
    )


def per_file_structure_slices(
    artifact: ParseArtifact | dict[str, Any],
    file_name: str,
) -> dict[str, Any]:
    """Extract per-file section tree / evidence pool / document IR from a combined artifact."""
    if isinstance(artifact, ParseArtifact):
        section_tree = artifact.section_tree
        evidence_pool = artifact.evidence_pool
        document_ir = artifact.document_ir
    else:
        section_tree = artifact.get("section_tree") or {}
        evidence_pool = artifact.get("evidence_pool") or {}
        document_ir = artifact.get("document_ir") or {}

    sections = [
        section
        for section in (section_tree.get("sections") or [])
        if str(section.get("source_file_name") or "") in {"", file_name}
    ]
    if not sections:
        sections = list(section_tree.get("sections") or [])
    section_ids = {str(section.get("section_id") or "") for section in sections}
    evidences = [
        evidence
        for evidence in (evidence_pool.get("evidences") or [])
        if str(evidence.get("section_id") or "") in section_ids
        or str(evidence.get("source_file_name") or "") in {"", file_name}
    ]
    layout_blocks = [
        block
        for block in (document_ir.get("layout_blocks") or [])
        if str(block.get("source_file_name") or block.get("file_name") or "") in {"", file_name}
    ]
    sliced_ir = {**document_ir, "layout_blocks": layout_blocks or document_ir.get("layout_blocks") or []}
    return {
        "section_tree": {
            **section_tree,
            "sections": sections,
            "root_section_ids": [
                sid
                for sid in (section_tree.get("root_section_ids") or [])
                if sid in section_ids
            ]
            or [str(section.get("section_id") or "") for section in sections[:1]],
        },
        "evidence_pool": {"evidences": evidences},
        "document_ir": sliced_ir,
        "section_count": len(sections),
    }
