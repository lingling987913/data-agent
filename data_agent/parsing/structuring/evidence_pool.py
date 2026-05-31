"""Evidence pool and legacy review chunk builders."""

from __future__ import annotations

import logging
import uuid

from data_agent.parsing.schemas import (
    DocumentEvidence,
    DocumentEvidencePool,
    DocumentIR,
    DocumentSection,
    DocumentSectionTree,
    DocumentTocEntry,
    ParsedDocument,
    ReviewDocumentChunk,
)
from data_agent.parsing.document_ir_consumer import _format_calibration_excerpt
from data_agent.parsing.structuring.section_tree import (
    _build_toc_title_map,
    _prepare_doc_for_chunking,
    _resolve_heading_from_block,
)

logger = logging.getLogger(__name__)

def build_document_evidence_pool(
    section_tree: DocumentSectionTree,
    parsed_doc: ParsedDocument,
    *,
    document_ir: DocumentIR | None = None,
) -> DocumentEvidencePool:
    """为章节树中的每个章节生成文档主证据。

    每个章节最多生成三类证据:
      1. section_summary: 章节正文前 300 字作为摘要
      2. paragraph_excerpt: 章节内的段落原文 (按块拆分, 每块一条)
      3. table_text: 章节内的表格文字 + 前后 1 段上下文

    当提供 Document IR 时，优先从 ``layout_blocks`` / ``table_elements`` 消费，
    仅在 IR 为空时回退到 ``ParsedDocumentBlock`` 扫描。
    """
    from data_agent.parsing.document_ir_consumer import (
        build_document_ir_for_parsed,
        build_evidences_from_document_ir,
    )

    doc_ir = document_ir or build_document_ir_for_parsed(parsed_doc)
    if (
        doc_ir.layout_blocks
        or doc_ir.table_elements
        or doc_ir.visual_elements
        or parsed_doc.calibration_records
    ):
        ir_evidences = build_evidences_from_document_ir(doc_ir, section_tree, parsed_doc)
        if ir_evidences:
            logger.info(
                "[EvidencePool] IR 构建完成: %s 条主证据 (layout=%s, table=%s)",
                len(ir_evidences),
                len(doc_ir.layout_blocks),
                len(doc_ir.table_elements),
            )
            return DocumentEvidencePool(evidences=ir_evidences)

    evidences: list[DocumentEvidence] = []
    blocks_by_index = {b.order_index: b for b in parsed_doc.blocks}
    blocks_by_id = {b.block_id: b for b in parsed_doc.blocks}

    def _section_for_block_id(block_id: str) -> DocumentSection | None:
        block = blocks_by_id.get(block_id)
        if block is None:
            return section_tree.sections[0] if section_tree.sections else None
        for section in section_tree.sections:
            if section.start_block_index <= block.order_index <= section.end_block_index:
                return section
        return section_tree.sections[0] if section_tree.sections else None

    for section in section_tree.sections:
        # 跳过无内容章节
        if not section.text.strip():
            continue

        # ── 1. 章节摘要 ──
        summary_text = section.text[:300].strip()
        if summary_text:
            evidences.append(DocumentEvidence(
                evidence_id=str(uuid.uuid4())[:12],
                source_type="section_summary",
                section_id=section.section_id,
                source_file_name=parsed_doc.file_name,
                summary=summary_text,
                excerpt=summary_text,
            ))

        # ── 2. 段落摘录 + 3. 表格文字 + 4. 图片描述 + 5. 校准记录 ──
        for idx in range(section.start_block_index, section.end_block_index + 1):
            block = blocks_by_index.get(idx)
            if not block:
                continue

            if block.block_type in {"figure", "figure_caption", "image"}:
                vision = (block.vision_description or "").strip()
                if not vision:
                    vision = (block.caption or block.text or "").strip()
                if len(vision) >= 8:
                    evidences.append(DocumentEvidence(
                        evidence_id=str(uuid.uuid4())[:12],
                        source_type="visual_description",
                        section_id=section.section_id,
                        block_ids=[block.block_id],
                        source_file_name=parsed_doc.file_name,
                        excerpt=vision,
                    ))
                continue

            if not block.text.strip():
                continue

            if block.block_type == "paragraph" and block.text.strip():
                evidences.append(DocumentEvidence(
                    evidence_id=str(uuid.uuid4())[:12],
                    source_type="paragraph_excerpt",
                    section_id=section.section_id,
                    block_ids=[block.block_id],
                    source_file_name=parsed_doc.file_name,
                    excerpt=block.text.strip(),
                ))

            elif block.block_type == "table" and block.text.strip():
                # 收集表前表后 1 段上下文
                neighbor_parts = []
                prev_block = blocks_by_index.get(idx - 1)
                if prev_block and prev_block.block_type == "paragraph":
                    neighbor_parts.append(f"[表前] {prev_block.text.strip()[:200]}")
                neighbor_parts.append(block.text.strip())
                next_block = blocks_by_index.get(idx + 1)
                if next_block and next_block.block_type == "paragraph":
                    neighbor_parts.append(f"[表后] {next_block.text.strip()[:200]}")

                evidences.append(DocumentEvidence(
                    evidence_id=str(uuid.uuid4())[:12],
                    source_type="table_text",
                    section_id=section.section_id,
                    block_ids=[block.block_id],
                    source_file_name=parsed_doc.file_name,
                    excerpt="\n".join(neighbor_parts),
                ))

    for record in parsed_doc.calibration_records or []:
        excerpt = _format_calibration_excerpt(record)
        if len(excerpt) < 8:
            continue
        section = _section_for_block_id(record.block_id)
        if section is None:
            continue
        evidences.append(DocumentEvidence(
            evidence_id=str(uuid.uuid4())[:12],
            source_type="parse_calibration",
            section_id=section.section_id,
            block_ids=[record.block_id] if record.block_id else [],
            source_file_name=parsed_doc.file_name,
            excerpt=excerpt,
        ))

    logger.info(
        f"[EvidencePool] 构建完成: {len(evidences)} 条主证据 "
        f"(来自 {len([s for s in section_tree.sections if s.text.strip()])} 个有内容章节)"
    )
    return DocumentEvidencePool(evidences=evidences)


def build_review_chunks(
    parsed_doc: ParsedDocument,
    toc_entries: list[DocumentTocEntry] | None = None,
    toc_block_indexes: set[int] | None = None,
) -> list[ReviewDocumentChunk]:
    """Group blocks into sections and chunks."""
    prepared_doc, toc_entries, _ = _prepare_doc_for_chunking(
        parsed_doc,
        toc_entries=toc_entries,
        toc_block_indexes=toc_block_indexes,
    )
    toc_title_map = _build_toc_title_map(toc_entries)

    chunks = []
    current_section_title = ""
    current_section_path = []
    
    current_chunk_blocks = []
    current_chunk_text_length = 0
    MAX_CHUNK_SIZE = 2000
    
    def emit_chunk(title, path):
        nonlocal current_chunk_blocks, current_chunk_text_length
        if not current_chunk_blocks:
            return
        
        text = "\n\n".join([b.text for b in current_chunk_blocks])
        block_ids = [b.block_id for b in current_chunk_blocks]
        
        chunks.append(ReviewDocumentChunk(
            chunk_id=str(uuid.uuid4()),
            document_id=prepared_doc.document_id,
            source_file_name=prepared_doc.file_name,
            section_title=title,
            section_path=path.copy(),
            chunk_text=text,
            order_index=len(chunks),
            block_ids=block_ids
        ))
        current_chunk_blocks = []
        current_chunk_text_length = 0

    for block in prepared_doc.blocks:
        heading_info = _resolve_heading_from_block(block, toc_title_map)
        if heading_info:
            emit_chunk(current_section_title, current_section_path)

            heading_number, heading_title, level = heading_info
            current_section_title = f"{heading_number} {heading_title}".strip()
            if len(current_section_path) >= level:
                current_section_path = current_section_path[:level - 1]
            current_section_path.append(current_section_title)

            # optionally add heading itself to the immediate chunk
            current_chunk_blocks.append(block)
            current_chunk_text_length += len(block.text)
        else:
            current_chunk_blocks.append(block)
            current_chunk_text_length += len(block.text)
            
            if current_chunk_text_length >= MAX_CHUNK_SIZE:
                emit_chunk(current_section_title, current_section_path)
                
    emit_chunk(current_section_title, current_section_path)
    return chunks
