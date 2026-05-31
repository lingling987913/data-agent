"""Resolve parsed documents for preview/chunking pipelines."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock

def _build_cached_text_document(mat: dict) -> Optional[ParsedDocument]:
    """Build a parsed document from previously extracted text to avoid re-uploading."""
    cached_text = (mat.get("content") or "").strip()
    if not cached_text:
        return None

    file_name = mat.get("name", "cached_document")
    parsed_doc = ParsedDocument(
        document_id=str(uuid.uuid4()),
        file_name=file_name,
        file_type=mat.get("file_type", "design_report") or "design_report",
        parser_name=mat.get("parser_name", "") or "cached_content",
        parse_status=mat.get("parse_status", "") or "ok",
        warnings=list(mat.get("warnings", []) or []),
    )

    blocks = []
    for line in cached_text.splitlines():
        text = line.strip()
        if not text:
            continue
        blocks.append(ParsedDocumentBlock(
            block_id=str(uuid.uuid4()),
            block_type="paragraph",
            text=text,
            order_index=len(blocks),
        ))

    if not blocks:
        blocks.append(ParsedDocumentBlock(
            block_id=str(uuid.uuid4()),
            block_type="paragraph",
            text=cached_text,
            order_index=0,
        ))

    parsed_doc.blocks = blocks
    return parsed_doc


def _structure_artifact_complete(
    section_tree: dict | DocumentSectionTree | None,
    evidence_pool: dict | DocumentEvidencePool | None,
    *,
    document_ir: dict | DocumentIR | None = None,
    parse_artifact: dict | None = None,
) -> bool:
    """Compatibility wrapper for artifact completeness checks.

    New production code should import
    ``data_agent.parsing.artifact_builder.is_structure_artifact_complete``.
    """
    from data_agent.parsing.artifact_builder import is_structure_artifact_complete

    return is_structure_artifact_complete(
        section_tree,
        evidence_pool,
        document_ir=document_ir,
        parse_artifact=parse_artifact,
    )


def _resolve_preview_parsed_document(
    mat: dict,
    *,
    processing_mode: str | None = None,
) -> tuple[Optional[ParsedDocument], str]:
    """Resolve parsed document for preview/chunking; prefer cached material content over file re-parse."""
    if not mat.get("force_reparse"):
        cached_doc = _build_cached_text_document(mat)
        if cached_doc:
            return cached_doc, "cached_content"

    file_path = mat.get("file_path", "")
    file_name = mat.get("name", "")
    if not file_path or not os.path.exists(file_path):
        return None, "missing_file"

    ext = Path(file_name).suffix.lower()
    parser_type = mat.get("parser_type")
    if not parser_type:
        if ext in (".pdf", ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"):
            from data_agent.agents.format_guard.mode_policy import resolve_parser_type

            parser_type = resolve_parser_type(file_name, mat.get("processing_mode") or processing_mode or "OPTIMAL")
        else:
            parser_type = "local"

    from data_agent.parsing.parser_core import parse_uploaded_document

    parsed_doc = parse_uploaded_document(
        file_path,
        file_name,
        parser_type=parser_type,
        processing_mode=mat.get("processing_mode") or processing_mode,
    )
    return parsed_doc, "file_parse"
