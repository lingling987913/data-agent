"""Consume Document IR v1 as the primary structured source for downstream evidence."""

from __future__ import annotations

import re
import uuid
from typing import Iterable

from data_agent.parsing.schemas import (
    ChartElement,
    DocumentAsset,
    DocumentEvidence,
    DocumentIR,
    DocumentPage,
    DocumentSection,
    DocumentSectionTree,
    GraphElement,
    LayoutBlock,
    ParsedDocument,
    ParsedDocumentBlock,
    TableElement,
    VisualElement,
)


def _visual_confidence_from_block(block: ParsedDocumentBlock, parser_name: str) -> float:
    if block.confidence is not None:
        return float(block.confidence)
    text = block.text or ""
    match = re.search(r"confidence=([0-9.]+)", text)
    if match:
        return float(match.group(1))
    if parser_name == "vision_llm_parser":
        return 0.65
    if parser_name in {"mineru-agent", "mineru-local", "mineru-extract"}:
        return 0.75
    return 0.25


def _visual_requires_human_confirmation(confidence: float, parser_name: str) -> bool:
    if parser_name == "image_minimal_parser":
        return True
    return confidence < 0.7


def _visual_text_from_block(block: ParsedDocumentBlock) -> str:
    vision = (block.vision_description or "").strip()
    if vision:
        return vision
    return (block.text or block.caption or "").strip()


def _calibrations_by_block(document: ParsedDocument) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for record in document.calibration_records or []:
        payload = record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
        grouped.setdefault(record.block_id, []).append(payload)
    return grouped


def _format_calibration_excerpt(record: dict | object) -> str:
    data = record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record or {})
    parts: list[str] = []
    original = str(data.get("original_text") or "").strip()
    suggested = str(data.get("suggested_text") or "").strip()
    reason = str(data.get("reason") or "").strip()
    status = str(data.get("status") or "").strip()
    if original:
        parts.append(f"原文: {original}")
    if suggested:
        parts.append(f"建议: {suggested}")
    if reason:
        parts.append(f"原因: {reason}")
    if status:
        parts.append(f"状态: {status}")
    return "\n".join(parts)


def build_document_ir_for_parsed(document: ParsedDocument) -> DocumentIR:
    """Build Document IR for a single parsed document."""
    ir = DocumentIR()
    ir.assets.append(
        DocumentAsset(
            asset_id=f"asset-{document.document_id}",
            source_file_name=document.file_name,
            asset_type="source_file",
            mime_type=document.file_type,
            metadata={"parser_name": document.parser_name, "parse_status": document.parse_status},
        )
    )
    seen_pages: set[int] = set()
    calibrations_by_block = _calibrations_by_block(document)
    for block in document.blocks:
        page_no = int(block.page_hint or 1)
        if page_no not in seen_pages:
            seen_pages.add(page_no)
            ir.pages.append(
                DocumentPage(
                    page_id=f"{document.document_id}-p{page_no}",
                    source_file_name=document.file_name,
                    page_number=page_no,
                    page_type="slide" if document.file_type == "presentation" else "page",
                )
            )
        block_metadata: dict = {
            "level": block.level,
            "caption": block.caption,
        }
        if block.vision_description:
            block_metadata["vision_description"] = block.vision_description
        if block.image_ref:
            block_metadata["image_ref"] = block.image_ref
        block_calibrations = calibrations_by_block.get(block.block_id) or []
        if block_calibrations:
            block_metadata["calibration_records"] = block_calibrations
        ir.layout_blocks.append(
            LayoutBlock(
                layout_block_id=f"layout-{block.block_id}",
                source_block_id=block.block_id,
                source_file_name=document.file_name,
                page_id=f"{document.document_id}-p{page_no}",
                block_type=block.block_type,
                text=block.text,
                reading_order=block.order_index,
                bbox=block.bbox,
                confidence=block.confidence,
                parser_name=document.parser_name,
                metadata=block_metadata,
            )
        )
        if block.block_type in {"figure", "figure_caption", "image"}:
            text = _visual_text_from_block(block)
            visual_type = "flowchart" if any(k in text for k in ("流程", "框图", "graph", "flow")) else "figure"
            confidence = _visual_confidence_from_block(block, document.parser_name)
            ir.visual_elements.append(
                VisualElement(
                    visual_id=f"visual-{block.block_id}",
                    source_file_name=document.file_name,
                    source_block_id=block.block_id,
                    visual_type=visual_type,
                    description=text,
                    confidence=confidence,
                    requires_human_confirmation=_visual_requires_human_confirmation(
                        confidence, document.parser_name
                    ),
                    metadata={
                        "parser_name": document.parser_name,
                        "extraction_method": document.parser_name,
                    },
                )
            )
            if visual_type == "flowchart" and confidence < 0.5:
                ir.graph_elements.append(
                    GraphElement(
                        graph_id=f"graph-{block.block_id}",
                        source_file_name=document.file_name,
                        source_block_id=block.block_id,
                        confidence=confidence,
                        unparsed_reason="low_confidence_visual_summary_only",
                    )
                )
        if block.block_type == "table" or block.table_markdown:
            markdown = block.table_markdown or block.text
            ir.table_elements.append(
                TableElement(
                    table_id=f"table-{block.block_id}",
                    source_file_name=document.file_name,
                    source_block_id=block.block_id,
                    markdown=markdown,
                    confidence=0.6 if markdown else 0.2,
                )
            )
        if any(k in (block.text or "") for k in ("折线图", "柱状图", "曲线", "chart")):
            ir.chart_elements.append(
                ChartElement(
                    chart_id=f"chart-{block.block_id}",
                    source_file_name=document.file_name,
                    source_block_id=block.block_id,
                    confidence=0.2,
                    unparsed_reason="chart_data_not_recovered",
                )
            )

    if document.file_type == "image_document" and not any(
        v.source_file_name == document.file_name for v in ir.visual_elements
    ):
        primary = next(
            (b for b in document.blocks if _visual_text_from_block(b)),
            None,
        )
        if primary:
            text = _visual_text_from_block(primary)
            confidence = _visual_confidence_from_block(primary, document.parser_name)
            ir.visual_elements.append(
                VisualElement(
                    visual_id=f"visual-{document.document_id}",
                    source_file_name=document.file_name,
                    source_block_id=primary.block_id,
                    visual_type="figure",
                    description=text,
                    confidence=confidence,
                    requires_human_confirmation=_visual_requires_human_confirmation(
                        confidence, document.parser_name
                    ),
                    metadata={
                        "parser_name": document.parser_name,
                        "extraction_method": document.parser_name,
                    },
                )
            )
    return ir


def merge_document_ir(into: DocumentIR, single: DocumentIR) -> None:
    """Merge a per-document IR into a bundle-level IR."""
    into.assets.extend(single.assets)
    into.pages.extend(single.pages)
    into.layout_blocks.extend(single.layout_blocks)
    into.visual_elements.extend(single.visual_elements)
    into.table_elements.extend(single.table_elements)
    into.graph_elements.extend(single.graph_elements)
    into.chart_elements.extend(single.chart_elements)


def document_ir_slice(full: DocumentIR, source_file_name: str) -> DocumentIR:
    """Return a single-document view from a bundle-level Document IR."""
    return DocumentIR(
        assets=[item for item in full.assets if item.source_file_name == source_file_name],
        pages=[item for item in full.pages if item.source_file_name == source_file_name],
        layout_blocks=[item for item in full.layout_blocks if item.source_file_name == source_file_name],
        visual_elements=[item for item in full.visual_elements if item.source_file_name == source_file_name],
        table_elements=[item for item in full.table_elements if item.source_file_name == source_file_name],
        graph_elements=[item for item in full.graph_elements if item.source_file_name == source_file_name],
        chart_elements=[item for item in full.chart_elements if item.source_file_name == source_file_name],
    )


def document_ir_attached(bundle_ir: DocumentIR, source_file_name: str) -> bool:
    return any(asset.source_file_name == source_file_name for asset in bundle_ir.assets)


def prepare_document_ir_for_parsed(bundle_ir: DocumentIR, parsed_doc: ParsedDocument) -> DocumentIR:
    """Build per-document IR once and merge into bundle IR (idempotent per file)."""
    if document_ir_attached(bundle_ir, parsed_doc.file_name):
        return document_ir_slice(bundle_ir, parsed_doc.file_name)
    doc_ir = build_document_ir_for_parsed(parsed_doc)
    merge_document_ir(bundle_ir, doc_ir)
    return doc_ir


def _section_for_order_index(
    section_tree: DocumentSectionTree,
    order_index: int,
    *,
    source_file_name: str = "",
) -> DocumentSection | None:
    for section in section_tree.sections:
        if source_file_name and section.source_file_name and section.source_file_name != source_file_name:
            continue
        if section.start_block_index <= order_index <= section.end_block_index:
            return section
    for section in section_tree.sections:
        if not source_file_name or not section.source_file_name or section.source_file_name == source_file_name:
            return section
    return section_tree.sections[0] if section_tree.sections else None


def _section_for_source_block(
    section_tree: DocumentSectionTree,
    parsed_doc: ParsedDocument,
    source_block_id: str,
) -> DocumentSection | None:
    blocks_by_id = {block.block_id: block.order_index for block in parsed_doc.blocks}
    order_index = blocks_by_id.get(source_block_id)
    if order_index is None:
        return None
    return _section_for_order_index(
        section_tree,
        order_index,
        source_file_name=parsed_doc.file_name,
    )


def _layout_blocks_by_order(document_ir: DocumentIR) -> dict[int, LayoutBlock]:
    return {int(block.reading_order): block for block in document_ir.layout_blocks}


def _section_summary_evidences(
    section_tree: DocumentSectionTree,
    source_file_name: str,
) -> list[DocumentEvidence]:
    evidences: list[DocumentEvidence] = []
    for section in section_tree.sections:
        if source_file_name and section.source_file_name and section.source_file_name != source_file_name:
            continue
        if not section.text.strip():
            continue
        summary_text = section.text[:300].strip()
        if not summary_text:
            continue
        evidences.append(
            DocumentEvidence(
                evidence_id=str(uuid.uuid4())[:12],
                source_type="section_summary",
                section_id=section.section_id,
                source_file_name=source_file_name or section.source_file_name,
                summary=summary_text,
                excerpt=summary_text,
            )
        )
    return evidences


def build_evidences_from_document_ir(
    document_ir: DocumentIR,
    section_tree: DocumentSectionTree,
    parsed_doc: ParsedDocument,
) -> list[DocumentEvidence]:
    """Build evidence pool entries preferring Document IR layout/table elements."""
    source_file_name = parsed_doc.file_name
    evidences = _section_summary_evidences(section_tree, source_file_name)
    seen_keys: set[tuple[str, str, str]] = {
        (item.source_type, item.section_id, item.excerpt[:80]) for item in evidences
    }
    layout_by_order = _layout_blocks_by_order(document_ir)

    for layout in document_ir.layout_blocks:
        if layout.source_file_name and layout.source_file_name != source_file_name:
            continue
        text = (layout.text or "").strip()
        if not text or layout.block_type not in {"paragraph", "heading", "list_item"}:
            continue
        section = _section_for_order_index(
            section_tree,
            int(layout.reading_order),
            source_file_name=source_file_name,
        )
        if section is None:
            continue
        key = ("paragraph_excerpt", section.section_id, text[:80])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        evidences.append(
            DocumentEvidence(
                evidence_id=str(uuid.uuid4())[:12],
                source_type="paragraph_excerpt",
                section_id=section.section_id,
                block_ids=[layout.source_block_id] if layout.source_block_id else [],
                source_file_name=source_file_name,
                excerpt=text,
            )
        )

    for table in document_ir.table_elements:
        if table.source_file_name and table.source_file_name != source_file_name:
            continue
        markdown = (table.markdown or "").strip()
        if not markdown:
            continue
        section = _section_for_source_block(section_tree, parsed_doc, table.source_block_id)
        if section is None:
            section = _section_for_order_index(section_tree, 0, source_file_name=source_file_name)
        if section is None:
            continue
        neighbor_parts: list[str] = []
        order_index = next(
            (idx for idx, block in layout_by_order.items() if block.source_block_id == table.source_block_id),
            None,
        )
        if order_index is not None:
            prev_block = layout_by_order.get(order_index - 1)
            if prev_block and prev_block.block_type == "paragraph" and prev_block.text.strip():
                neighbor_parts.append(f"[表前] {prev_block.text.strip()[:200]}")
        neighbor_parts.append(markdown)
        if order_index is not None:
            next_block = layout_by_order.get(order_index + 1)
            if next_block and next_block.block_type == "paragraph" and next_block.text.strip():
                neighbor_parts.append(f"[表后] {next_block.text.strip()[:200]}")
        excerpt = "\n".join(neighbor_parts)
        key = ("table_text", section.section_id, excerpt[:80])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        evidences.append(
            DocumentEvidence(
                evidence_id=str(uuid.uuid4())[:12],
                source_type="table_text",
                section_id=section.section_id,
                block_ids=[table.source_block_id] if table.source_block_id else [],
                source_file_name=source_file_name,
                excerpt=excerpt,
            )
        )

    for visual in document_ir.visual_elements:
        if visual.source_file_name and visual.source_file_name != source_file_name:
            continue
        description = (visual.description or "").strip()
        if len(description) < 8:
            continue
        section = _section_for_source_block(section_tree, parsed_doc, visual.source_block_id)
        if section is None:
            section = _section_for_order_index(section_tree, 0, source_file_name=source_file_name)
        if section is None:
            continue
        key = ("visual_description", section.section_id, description[:80])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        evidences.append(
            DocumentEvidence(
                evidence_id=str(uuid.uuid4())[:12],
                source_type="visual_description",
                section_id=section.section_id,
                block_ids=[visual.source_block_id] if visual.source_block_id else [],
                source_file_name=source_file_name,
                excerpt=description,
            )
        )

    for record in parsed_doc.calibration_records or []:
        excerpt = _format_calibration_excerpt(record)
        if len(excerpt) < 8:
            continue
        section = _section_for_source_block(section_tree, parsed_doc, record.block_id)
        if section is None:
            section = _section_for_order_index(section_tree, 0, source_file_name=source_file_name)
        if section is None:
            continue
        key = ("parse_calibration", section.section_id, excerpt[:80])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        evidences.append(
            DocumentEvidence(
                evidence_id=str(uuid.uuid4())[:12],
                source_type="parse_calibration",
                section_id=section.section_id,
                block_ids=[record.block_id] if record.block_id else [],
                source_file_name=source_file_name,
                excerpt=excerpt,
            )
        )

    return evidences


def iter_ir_evidence_candidates(document_ir: dict | DocumentIR) -> Iterable[dict[str, str]]:
    """Yield lightweight evidence dicts from serialized or model Document IR."""
    if isinstance(document_ir, DocumentIR):
        payload = document_ir.model_dump(mode="json")
    else:
        payload = document_ir or {}

    for table in payload.get("table_elements") or []:
        markdown = str(table.get("markdown") or "").strip()
        if len(markdown) < 8:
            continue
        yield {
            "evidence_id": str(table.get("table_id") or ""),
            "material_name": str(table.get("source_file_name") or ""),
            "section_id": str(table.get("table_id") or ""),
            "section_title": "结构化表格",
            "text": markdown,
            "summary": "",
            "source_kind": "document_ir_table",
        }

    for layout in payload.get("layout_blocks") or []:
        text = str(layout.get("text") or "").strip()
        block_type = str(layout.get("block_type") or "")
        if len(text) < 8 or block_type not in {"paragraph", "heading", "list_item", "table"}:
            continue
        yield {
            "evidence_id": str(layout.get("layout_block_id") or layout.get("source_block_id") or ""),
            "material_name": str(layout.get("source_file_name") or ""),
            "section_id": str(layout.get("layout_block_id") or ""),
            "section_title": block_type,
            "text": text,
            "summary": "",
            "source_kind": "document_ir_layout",
        }

    for visual in payload.get("visual_elements") or []:
        text = str(visual.get("description") or "").strip()
        if len(text) < 8:
            continue
        yield {
            "evidence_id": str(visual.get("visual_id") or ""),
            "material_name": str(visual.get("source_file_name") or ""),
            "section_id": str(visual.get("visual_id") or ""),
            "section_title": str(visual.get("visual_type") or "visual"),
            "text": text,
            "summary": "",
            "source_kind": "document_ir_visual",
        }

    for layout in payload.get("layout_blocks") or []:
        metadata = layout.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        for record in metadata.get("calibration_records") or []:
            if not isinstance(record, dict):
                continue
            text = _format_calibration_excerpt(record)
            if len(text) < 8:
                continue
            block_id = str(layout.get("source_block_id") or layout.get("layout_block_id") or "")
            yield {
                "evidence_id": f"cal:{block_id}:{record.get('issue_type', '')}",
                "material_name": str(layout.get("source_file_name") or ""),
                "section_id": block_id,
                "section_title": "解析校准",
                "text": text,
                "summary": "",
                "source_kind": "parse_calibration",
            }
