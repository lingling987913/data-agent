"""Preview/chunking pipeline for review preparation."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from data_agent.evaluation.metrics.table_coverage import count_table_rows_from_elements
from data_agent.parsing.document_ir_consumer import (
    build_document_ir_for_parsed,
    document_ir_attached,
    merge_document_ir,
    prepare_document_ir_for_parsed,
)
from data_agent.parsing.schemas import (
    DocumentEvidence,
    DocumentIR,
    DocumentSection,
    ParsedDocument,
    ParsedDocumentBlock,
    ReviewDocumentBundle,
)
from data_agent.parsing.structuring.evidence_pool import (
    build_document_evidence_pool,
    build_review_chunks,
)
from data_agent.parsing.structuring.extraction import attach_extracted_structured_objects
from data_agent.parsing.structuring.preview_resolution import (
    _build_cached_text_document,
    _resolve_preview_parsed_document,
)
from data_agent.parsing.structuring.section_tree import (
    _prepare_doc_for_chunking,
    build_section_tree,
)
from data_agent.parsing.structuring.semantic_chunking import llm_semantic_chunking
from data_agent.parsing.structuring.stage_mapping import map_chunks_to_review_stages

logger = logging.getLogger(__name__)


def _prepare_document_ir(bundle: ReviewDocumentBundle, parsed_doc: ParsedDocument) -> DocumentIR:
    return prepare_document_ir_for_parsed(bundle.document_ir, parsed_doc)


def _attach_document_ir(bundle: ReviewDocumentBundle) -> None:
    for document in bundle.parsed_documents:
        if document_ir_attached(bundle.document_ir, document.file_name):
            continue
        merge_document_ir(bundle.document_ir, build_document_ir_for_parsed(document))


def _preview_document_ir_stats(blocks: list[ParsedDocumentBlock]) -> dict[str, int]:
    table_count = sum(1 for block in blocks if block.block_type == "table")
    visual_count = sum(1 for block in blocks if block.block_type in {"figure", "figure_caption", "image"})
    graph_count = sum(
        1
        for block in blocks
        if block.block_type in {"figure", "figure_caption"}
        and any(token in (block.text or "") for token in ("流程", "框图", "graph", "flow"))
    )
    chart_count = sum(
        1
        for block in blocks
        if block.block_type in {"figure", "figure_caption"}
        and any(token in (block.text or "") for token in ("图表", "曲线", "chart", "plot"))
    )
    page_numbers = sorted({int(block.page_hint or 1) for block in blocks})
    return {
        "layout_block_count": len(blocks),
        "page_count": len(page_numbers),
        "visual_element_count": visual_count,
        "table_element_count": table_count,
        "graph_element_count": graph_count,
        "chart_element_count": chart_count,
    }


def _preview_file_result(
    *,
    file_name: str,
    parser_name: str,
    parse_status: str,
    warnings: list[str],
    blocks: list[ParsedDocumentBlock],
    parser_fallback_logs: list[dict] | None = None,
) -> dict:
    parser_chain: list[str] = []
    for event in parser_fallback_logs or []:
        for key in ("source_parser", "fallback_parser"):
            value = str(event.get(key) or "")
            if value and value not in parser_chain:
                parser_chain.append(value)
    if parser_name and parser_name not in parser_chain:
        parser_chain.append(parser_name)
    from data_agent.parsing.parse_artifacts import meaningful_parse_warnings

    meaningful_warnings = meaningful_parse_warnings(list(warnings or []))
    degraded = parse_status != "ok" or bool(meaningful_warnings)
    return {
        "file_name": file_name,
        "file_type": Path(file_name).suffix.lower().lstrip("."),
        "parser_selected": parser_name,
        "parser_chain": parser_chain,
        "parse_status": parse_status,
        "capability_passed": parse_status == "ok" and not degraded,
        "degraded": degraded,
        "warnings": list(meaningful_warnings),
        "document_ir_stats": _preview_document_ir_stats(blocks),
    }


def _preview_batch_summary(file_results: list[dict]) -> dict:
    file_count = len(file_results)
    parsed_count = sum(1 for item in file_results if item.get("parse_status") != "failed")
    degraded_count = sum(1 for item in file_results if item.get("degraded"))
    failed_count = sum(1 for item in file_results if item.get("parse_status") == "failed")
    capability_count = sum(1 for item in file_results if item.get("capability_passed"))
    return {
        "file_count": file_count,
        "parsed_count": parsed_count,
        "degraded_count": degraded_count,
        "failed_count": failed_count,
        "execution_pass_rate": round(parsed_count / file_count, 4) if file_count else 0.0,
        "capability_pass_rate": round(capability_count / file_count, 4) if file_count else 0.0,
        "degradation_rate": round(degraded_count / file_count, 4) if file_count else 0.0,
    }


def _resolve_material_parsed_document(
    mat: dict,
    *,
    processing_mode: str | None = None,
) -> tuple[Optional[ParsedDocument], str, str]:
    """Resolve parsed document; prefer embedded parse-only payload over file re-parse."""
    if mat.get("parsed_document"):
        return ParsedDocument.model_validate(mat["parsed_document"]), "parsed_artifact", mat.get("parser_type") or "local"

    file_path = mat.get("file_path", "")
    file_name = mat.get("name", "") or mat.get("file_name", "")
    ext = Path(file_name).suffix.lower()
    parser_type = mat.get("parser_type")
    if not parser_type:
        if ext in (".pdf", ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"):
            from data_agent.agents.format_guard.mode_policy import resolve_parser_type

            parser_type = resolve_parser_type(file_name, mat.get("processing_mode") or processing_mode or "OPTIMAL")
        else:
            parser_type = "local"

    if parser_type == "ragflow":
        cached_doc = _build_cached_text_document(mat)
        if cached_doc:
            return cached_doc, "cached_content", parser_type

    parsed_doc, resolve_source = _resolve_preview_parsed_document(
        mat,
        processing_mode=mat.get("processing_mode") or processing_mode,
    )
    return parsed_doc, resolve_source, parser_type


async def _build_preview_result(
    *,
    materials: list[dict],
    strategy: str,
    review_scope: str,
    model_id: str,
    parse_artifact: dict | None = None,
    pipeline_step: str = "parse_and_structure",
) -> dict:
    from data_agent.parsing.artifact_builder import is_parse_artifact_complete

    bundle = ReviewDocumentBundle()
    file_results: list[dict] = []

    if parse_artifact and is_parse_artifact_complete(parse_artifact):
        for item in parse_artifact.get("parsed_documents") or []:
            if not isinstance(item, dict):
                continue
            document_payload = item.get("document")
            if not document_payload:
                continue
            parsed_doc = ParsedDocument.model_validate(document_payload)
            file_name = str(item.get("file_name") or parsed_doc.file_name or "")
            bundle.parsed_documents.append(parsed_doc)
            file_results.append(
                _preview_file_result(
                    file_name=file_name,
                    parser_name=parsed_doc.parser_name,
                    parse_status=parsed_doc.parse_status,
                    warnings=parsed_doc.warnings,
                    blocks=parsed_doc.blocks,
                    parser_fallback_logs=parsed_doc.parser_fallback_logs,
                )
            )
    else:
        for mat in materials:
            file_path = mat.get("file_path", "")
            file_name = mat.get("name", "") or mat.get("file_name", "")

            try:
                parsed_doc, _resolve_source, parser_type = _resolve_material_parsed_document(mat)
                if not parsed_doc:
                    bundle.warnings.append(f"文件不存在或路径无效: {file_name} ({file_path})")
                    file_results.append(
                        _preview_file_result(
                            file_name=file_name,
                            parser_name=parser_type,
                            parse_status="failed",
                            warnings=[f"文件不存在或路径无效: {file_path}"],
                            blocks=[],
                        )
                    )
                    continue
                bundle.parsed_documents.append(parsed_doc)
                file_results.append(
                    _preview_file_result(
                        file_name=file_name,
                        parser_name=parsed_doc.parser_name,
                        parse_status=parsed_doc.parse_status,
                        warnings=parsed_doc.warnings,
                        blocks=parsed_doc.blocks,
                        parser_fallback_logs=parsed_doc.parser_fallback_logs,
                    )
                )
                if parsed_doc.warnings:
                    bundle.warnings.extend([f"[{file_name}] {w}" for w in parsed_doc.warnings])
            except Exception as e:
                bundle.warnings.append(f"解析失败 {file_name}: {e}")
                file_results.append(
                    _preview_file_result(
                        file_name=file_name,
                        parser_name=str(mat.get("parser_type") or "local"),
                        parse_status="failed",
                        warnings=[str(e)],
                        blocks=[],
                    )
                )

    for parsed_doc in bundle.parsed_documents:
        file_name = parsed_doc.file_name
        if not parsed_doc.blocks:
            continue
        prepared_doc, toc_entries, _ = _prepare_doc_for_chunking(parsed_doc)
        doc_chunks = build_review_chunks(prepared_doc, toc_entries=toc_entries, toc_block_indexes=set())
        bundle.chunks.extend(doc_chunks)

        if strategy == "llm_semantic":
            tree = await llm_semantic_chunking(
                prepared_doc,
                model_id=model_id,
                toc_entries=toc_entries,
                toc_block_indexes=set(),
            )
        else:
            tree = build_section_tree(prepared_doc, toc_entries=toc_entries, toc_block_indexes=set())

        doc_ir = _prepare_document_ir(bundle, prepared_doc)
        pool = build_document_evidence_pool(tree, prepared_doc, document_ir=doc_ir)
        bundle.section_tree.sections.extend(tree.sections)
        bundle.section_tree.root_section_ids.extend(tree.root_section_ids)
        bundle.section_tree.toc_entries.extend(tree.toc_entries)
        bundle.evidence_pool.evidences.extend(pool.evidences)
        if toc_entries:
            bundle.warnings.append(
                f"[{file_name}] 已识别目录 {len(toc_entries)} 项，已从正文切片中排除，并用于辅助章节对齐"
            )

    if not bundle.section_tree.sections and bundle.chunks:
        for chunk in bundle.chunks:
            section_id = f"sec-{chunk.chunk_id}"
            section = DocumentSection(
                section_id=section_id,
                title=chunk.section_title or chunk.source_file_name or "document",
                level=1,
                start_block_index=chunk.order_index,
                end_block_index=chunk.order_index,
                text=chunk.chunk_text,
                source_file_name=chunk.source_file_name,
            )
            bundle.section_tree.sections.append(section)
            bundle.section_tree.root_section_ids.append(section_id)
            bundle.evidence_pool.evidences.append(
                DocumentEvidence(
                    evidence_id=str(uuid.uuid4())[:12],
                    source_type="paragraph_excerpt",
                    section_id=section_id,
                    block_ids=list(chunk.block_ids),
                    source_file_name=chunk.source_file_name,
                    excerpt=chunk.chunk_text,
                )
            )

    stage_map = map_chunks_to_review_stages(bundle.chunks, review_scope)
    bundle.stage_context_map = stage_map
    _attach_document_ir(bundle)
    attach_extracted_structured_objects(bundle)
    batch_summary = _preview_batch_summary(file_results)
    parse_artifact_payload = {
        "artifact_id": f"parse-{uuid.uuid4().hex[:12]}",
        "pipeline_step": pipeline_step,
        "file_results": file_results,
        "batch_summary": batch_summary,
        "parsed_documents": [
            {
                "file_name": document.file_name,
                "file_type": document.file_type,
                "parse_status": document.parse_status,
                "parser_name": document.parser_name,
                "document": document.model_dump(mode="json"),
            }
            for document in bundle.parsed_documents
        ],
        "document_ir": bundle.document_ir.model_dump(),
        "section_tree": bundle.section_tree.model_dump(),
        "evidence_pool": bundle.evidence_pool.model_dump(),
        "extracted_parameters": [item.model_dump() for item in bundle.extracted_parameters],
        "extracted_objects": [item.model_dump() for item in bundle.extracted_objects],
        "trace_link_candidates": [item.model_dump() for item in bundle.trace_link_candidates],
        "parse_quality_report": {
            "status": "degraded" if batch_summary["degraded_count"] or batch_summary["failed_count"] else "ok",
            "warnings": list(bundle.warnings),
            "execution_pass_rate": batch_summary["execution_pass_rate"],
            "capability_pass_rate": batch_summary["capability_pass_rate"],
            "degradation_rate": batch_summary["degradation_rate"],
        },
    }

    logger.info(
        f"[PreviewChunks] strategy={strategy}, "
        f"sections={len(bundle.section_tree.sections)}, "
        f"toc={len(bundle.section_tree.toc_entries)}, "
        f"evidences={len(bundle.evidence_pool.evidences)}, "
        f"chunks={len(bundle.chunks)}"
    )

    return {
        "strategy": strategy,
        "section_tree": bundle.section_tree.model_dump(),
        "evidence_pool": bundle.evidence_pool.model_dump(),
        "extracted_parameters": [item.model_dump() for item in bundle.extracted_parameters],
        "extracted_objects": [item.model_dump() for item in bundle.extracted_objects],
        "trace_link_candidates": [item.model_dump() for item in bundle.trace_link_candidates],
        "requirements": [item.model_dump() for item in bundle.requirements],
        "design_elements": [item.model_dump() for item in bundle.design_elements],
        "verification_items": [item.model_dump() for item in bundle.verification_items],
        "traceability_matrix_summary": bundle.traceability_matrix_summary.model_dump(),
        "document_ir": bundle.document_ir.model_dump(),
        "parse_artifact": parse_artifact_payload,
        "file_results": file_results,
        "batch_summary": batch_summary,
        "chunks": [c.model_dump() for c in bundle.chunks],
        "stage_context_map": {k: v.model_dump() for k, v in bundle.stage_context_map.items()},
        "stats": {
            "section_count": len(bundle.section_tree.sections),
            "toc_entry_count": len(bundle.section_tree.toc_entries),
            "evidence_count": len(bundle.evidence_pool.evidences),
            "chunk_count": len(bundle.chunks),
            "document_count": len(bundle.parsed_documents),
            "extracted_parameter_count": len(bundle.extracted_parameters),
            "extracted_object_count": len(bundle.extracted_objects),
            "trace_link_candidate_count": len(bundle.trace_link_candidates),
            "requirement_count": len(bundle.requirements),
            "design_element_count": len(bundle.design_elements),
            "verification_item_count": len(bundle.verification_items),
            "layout_block_count": len(bundle.document_ir.layout_blocks),
            "visual_element_count": len(bundle.document_ir.visual_elements),
            "table_element_count": len(bundle.document_ir.table_elements),
            "table_row_count": count_table_rows_from_elements(bundle.document_ir.table_elements),
            "graph_element_count": len(bundle.document_ir.graph_elements),
            "chart_element_count": len(bundle.document_ir.chart_elements),
            "parsed_count": batch_summary["parsed_count"],
            "degraded_count": batch_summary["degraded_count"],
            "failed_count": batch_summary["failed_count"],
            "execution_pass_rate": batch_summary["execution_pass_rate"],
            "capability_pass_rate": batch_summary["capability_pass_rate"],
            "degradation_rate": batch_summary["degradation_rate"],
        },
        "warnings": bundle.warnings,
    }


async def preview_structure(
    materials: list[dict],
    *,
    parse_artifact: dict,
    strategy: str = "code_based",
    review_scope: str = "ad_ac",
    model_id: str = "",
) -> dict:
    """Build section tree / evidence pool from an existing parse-only artifact (no re-parse)."""
    return await _build_preview_result(
        materials=materials,
        strategy=strategy,
        review_scope=review_scope,
        model_id=model_id,
        parse_artifact=parse_artifact,
        pipeline_step="document_structure",
    )


async def preview_parse_only(
    materials: list[dict],
    *,
    review_scope: str = "ad_ac",
) -> dict:
    """Parse materials only; returns parse-only artifact without structuring."""
    from data_agent.parsing.application_service import ParseDocumentCommand, parse_document
    from data_agent.parsing.parse_artifacts import build_parse_only_artifact_from_parsed

    async def _parse_one(mat: dict) -> dict:
        file_path = str(mat.get("file_path", "") or mat.get("path", ""))
        file_name = str(mat.get("name", "") or mat.get("file_name", "") or Path(file_path).name)
        payload = await asyncio.to_thread(
            parse_document,
            ParseDocumentCommand(
                file_path=file_path,
                file_name=file_name,
                parser_type=str(mat.get("parser_type") or "auto"),
                processing_mode=mat.get("processing_mode") or "HIGH_SPEED",
                include_document=True,
                include_artifact=False,
                skip_enhancement=bool(mat.get("skip_enhancement", True)),
            ),
        )
        document_payload = payload.get("document")
        block_count = len(document_payload.get("blocks") or []) if isinstance(document_payload, dict) else 0
        return {
            "file_name": file_name,
            "file_type": payload.get("file_type") or "",
            "parse_status": payload.get("parse_status") or "failed",
            "parser_name": payload.get("parser_name") or "",
            "block_count": block_count,
            "content": payload.get("content") or "",
            "warnings": list(payload.get("warnings") or []),
            "structuring_warnings": [],
            "parser_fallback_logs": list(payload.get("parser_fallback_logs") or []),
            "self_healing_records": list(payload.get("self_healing_records") or []),
            "document": document_payload,
        }

    documents = await asyncio.gather(*[_parse_one(mat) for mat in materials])
    parse_only = build_parse_only_artifact_from_parsed({
        "documents": documents,
        "document": documents[0].get("document") if documents else None,
        "parser_fallback_logs": [
            log
            for item in documents
            for log in item.get("parser_fallback_logs", [])
        ],
    })
    payload = parse_only.model_dump(mode="json")
    payload["pipeline_step"] = "document_parse"
    return {
        "parse_artifact": payload,
        "file_results": payload.get("file_results") or [],
        "batch_summary": payload.get("batch_summary") or {},
        "document_ir": payload.get("document_ir") or {},
        "warnings": payload.get("warnings") or [],
        "review_scope": review_scope,
    }


async def preview_document_chunks(
    materials: list[dict],
    strategy: str = "code_based",
    review_scope: str = "ad_ac",
    model_id: str = "",
    *,
    parse_artifact: dict | None = None,
) -> dict:
    """
    审查准备阶段的预切片统一入口。

    根据 strategy 选择切分路径：
      - "code_based": 代码规则路径 (build_section_tree)
      - "llm_semantic": LLM 语义路径 (llm_semantic_chunking, 异步并发)

    若提供完整 parse-only ``parse_artifact``，则跳过解析路径，仅执行结构化。
    """
    from data_agent.parsing.artifact_builder import is_parse_artifact_complete

    if parse_artifact and is_parse_artifact_complete(parse_artifact):
        return await preview_structure(
            materials,
            parse_artifact=parse_artifact,
            strategy=strategy,
            review_scope=review_scope,
            model_id=model_id,
        )

    return await _build_preview_result(
        materials=materials,
        strategy=strategy,
        review_scope=review_scope,
        model_id=model_id,
        parse_artifact=None,
        pipeline_step="parse_and_structure",
    )
