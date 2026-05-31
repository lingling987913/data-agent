"""Build comprehensive review document bundles from materials."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from data_agent.parsing.document_ir_consumer import (
    build_document_ir_for_parsed,
    document_ir_attached,
    merge_document_ir,
    prepare_document_ir_for_parsed,
)
from data_agent.parsing.schemas import DocumentIR, ParsedDocument, ReviewDocumentBundle
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
from data_agent.parsing.structuring.stage_mapping import map_chunks_to_review_stages

logger = logging.getLogger(__name__)


def _prepare_document_ir(bundle: ReviewDocumentBundle, parsed_doc: ParsedDocument) -> DocumentIR:
    return prepare_document_ir_for_parsed(bundle.document_ir, parsed_doc)


def _attach_document_ir(bundle: ReviewDocumentBundle) -> None:
    for document in bundle.parsed_documents:
        if document_ir_attached(bundle.document_ir, document.file_name):
            continue
        merge_document_ir(bundle.document_ir, build_document_ir_for_parsed(document))


def build_review_document_bundle(materials: list[dict], review_scope: str = "ad_ac") -> ReviewDocumentBundle:
    """Build the comprehensive document bundle for review.

    同时构建两代数据结构:
      - 第一代 (deprecated): chunks + stage_context_map
      - 第二代: section_tree + evidence_pool
    """
    bundle = ReviewDocumentBundle()

    for mat in materials:
        file_path = mat.get("file_path", "")
        file_name = mat.get("name", "")
        ext = Path(file_name).suffix.lower()
        parser_type = mat.get("parser_type")
        if not parser_type:
            if ext in (".pdf", ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"):
                from data_agent.agents.format_guard.mode_policy import resolve_parser_type

                parser_type = resolve_parser_type(file_name, mat.get("processing_mode") or "OPTIMAL")
            else:
                parser_type = "local"

        if parser_type == "ragflow":
            cached_doc = _build_cached_text_document(mat)
            if cached_doc:
                bundle.parsed_documents.append(cached_doc)
                prepared_doc, toc_entries, toc_block_indexes = _prepare_doc_for_chunking(cached_doc)
                doc_chunks = build_review_chunks(prepared_doc, toc_entries=toc_entries, toc_block_indexes=set())
                bundle.chunks.extend(doc_chunks)
                if toc_entries:
                    bundle.warnings.append(
                        f"[{file_name}] 已识别目录 {len(toc_entries)} 项，已从正文切片中排除，并用于辅助章节对齐"
                    )
                if cached_doc.warnings:
                    bundle.warnings.extend([f"[{file_name}] {w}" for w in cached_doc.warnings])
                continue

        if file_path and os.path.exists(file_path):
            try:
                parsed_doc, _ = _resolve_preview_parsed_document(mat)
                if not parsed_doc:
                    bundle.warnings.append(f"文件不存在或路径无效: {file_name} ({file_path})")
                    continue
                bundle.parsed_documents.append(parsed_doc)

                if parsed_doc.blocks:
                    prepared_doc, toc_entries, toc_block_indexes = _prepare_doc_for_chunking(parsed_doc)
                    # 第一代: 固定长度切块 (deprecated)
                    doc_chunks = build_review_chunks(prepared_doc, toc_entries=toc_entries, toc_block_indexes=set())
                    bundle.chunks.extend(doc_chunks)

                    # 第二代: 章节树 + 证据池
                    tree = build_section_tree(prepared_doc, toc_entries=toc_entries, toc_block_indexes=set())
                    doc_ir = _prepare_document_ir(bundle, prepared_doc)
                    pool = build_document_evidence_pool(tree, prepared_doc, document_ir=doc_ir)
                    # 合并到 bundle 级容器
                    bundle.section_tree.sections.extend(tree.sections)
                    bundle.section_tree.root_section_ids.extend(tree.root_section_ids)
                    bundle.section_tree.toc_entries.extend(tree.toc_entries)
                    bundle.evidence_pool.evidences.extend(pool.evidences)
                    if toc_entries:
                        bundle.warnings.append(
                            f"[{file_name}] 已识别目录 {len(toc_entries)} 项，已从正文切片中排除，并用于辅助章节对齐"
                        )

                if parsed_doc.warnings:
                    bundle.warnings.extend([f"[{file_name}] {w}" for w in parsed_doc.warnings])

            except Exception as e:
                bundle.warnings.append(f"Failed to process {file_name}: {e}")

    # 第一代: 阶段映射 (deprecated)
    stage_map = map_chunks_to_review_stages(bundle.chunks, review_scope)
    bundle.stage_context_map = stage_map
    _attach_document_ir(bundle)
    attach_extracted_structured_objects(bundle)

    logger.info(
        f"[DocumentBundle] 构建完成: "
        f"chunks={len(bundle.chunks)}, "
        f"sections={len(bundle.section_tree.sections)}, "
        f"evidences={len(bundle.evidence_pool.evidences)}, "
        f"parameters={len(bundle.extracted_parameters)}, "
        f"objects={len(bundle.extracted_objects)}, "
        f"trace_links={len(bundle.trace_links)}"
    )
    return bundle
