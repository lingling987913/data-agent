"""Core low-level document parser entrypoint.

Higher-level ingestion, API, task, and review flows should depend on this
module for format parsing. Review preview/structuring lives under
``data_agent.parsing.structuring``.
"""

from __future__ import annotations

import os
import uuid

from data_agent.parsing.finalize import finalize_parsed_document
from data_agent.parsing.orientation import prepare_orientation_normalized_file
from data_agent.parsing.pdf_postprocess import apply_pdf_postprocess
from data_agent.parsing.pdf_router import parse_pdf_auto
from data_agent.parsing.parsers.docx_parser import parse_doc, parse_docx
from data_agent.parsing.parsers.html_parser import parse_html
from data_agent.parsing.parsers.image_parser import parse_image_auto, parse_image_minimal
from data_agent.parsing.parsers.pdf_parser import parse_pdf
from data_agent.parsing.parsers.pptx_parser import parse_pptx
from data_agent.parsing.parsers.text_parser import parse_text
from data_agent.parsing.parsers.xlsx_parser import parse_xlsx
from data_agent.parsing.schemas import ParsedDocument


def parse_uploaded_document(
    file_path: str,
    file_name: str,
    parser_type: str = "local",
    *,
    processing_mode: str | None = None,
    mineru_parse_mode: str | None = None,
    skip_enhancement: bool = False,
    figure_storage_dir: str | None = None,
) -> ParsedDocument:
    """Parse document into structured blocks."""
    doc_id = str(uuid.uuid4())
    ext = os.path.splitext(file_name)[1].lower()

    parsed_doc = ParsedDocument(
        document_id=doc_id,
        file_name=file_name,
        file_type="unknown",
        parser_name="fallback_parser",
        parse_status="ok",
    )

    normalized = prepare_orientation_normalized_file(file_path, file_name)
    effective_file_path = normalized.file_path
    parsed_doc.warnings.extend(normalized.warnings)

    try:
        return _parse_uploaded_document_impl(
            effective_file_path,
            file_name,
            parser_type,
            parsed_doc,
            ext=ext,
            processing_mode=processing_mode,
            mineru_parse_mode=mineru_parse_mode,
            skip_enhancement=skip_enhancement,
            figure_storage_dir=figure_storage_dir,
        )
    finally:
        normalized.cleanup()


def _parse_uploaded_document_impl(
    file_path: str,
    file_name: str,
    parser_type: str,
    parsed_doc: ParsedDocument,
    *,
    ext: str,
    processing_mode: str | None,
    mineru_parse_mode: str | None,
    skip_enhancement: bool,
    figure_storage_dir: str | None,
) -> ParsedDocument:
    if parser_type == "ragflow":
        parsed_doc.file_type = "design_report"
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append("RAGFlow parser is not configured in data-agent.")
        return finalize_parsed_document(
            parsed_doc,
            parser_type=parser_type,
            processing_mode=processing_mode,
            file_path=file_path,
            skip_enhancement=skip_enhancement,
            figure_storage_dir=figure_storage_dir,
        )

    if parser_type == "mineru":
        parsed_doc.file_type = "design_report"
        from data_agent.parsing.parsers.mineru_local_http_parser import (
            mineru_local_supports,
            parse_via_mineru_local_http,
        )

        if mineru_local_supports(file_name):
            parse_via_mineru_local_http(file_path, file_name, parsed_doc, parse_mode=mineru_parse_mode)
        else:
            parsed_doc.parse_status = "failed"
            parsed_doc.warnings.append(f"MinerU 本地解析仅支持 PDF/图片，收到 {ext}")
        return finalize_parsed_document(
            parsed_doc,
            parser_type=parser_type,
            processing_mode=processing_mode,
            file_path=file_path,
            skip_enhancement=skip_enhancement,
            figure_storage_dir=figure_storage_dir,
        )

    if parser_type == "mineru_agent":
        parsed_doc.file_type = "design_report"
        from data_agent.parsing.parsers.mineru_agent_parser import parse_via_mineru_agent

        parse_via_mineru_agent(file_path, file_name, parsed_doc, parse_mode=mineru_parse_mode)
        return finalize_parsed_document(
            parsed_doc,
            parser_type=parser_type,
            processing_mode=processing_mode,
            file_path=file_path,
            skip_enhancement=skip_enhancement,
            figure_storage_dir=figure_storage_dir,
        )

    if parser_type == "auto":
        parsed_doc.file_type = "design_report"
        if ext == ".pdf":
            parse_pdf_auto(file_path, file_name, parsed_doc, processing_mode=processing_mode)
        elif ext in (".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"):
            if (processing_mode or "OPTIMAL").upper() == "HIGH_SPEED":
                parse_image_minimal(file_path, file_name, parsed_doc)
            else:
                parse_image_auto(file_path, file_name, parsed_doc, processing_mode=processing_mode)
        elif ext == ".docx":
            parse_docx(file_path, parsed_doc)
        elif ext == ".doc":
            parse_doc(file_path, parsed_doc)
        elif ext in (".html", ".htm"):
            parse_html(file_path, parsed_doc)
        elif ext == ".pptx":
            parse_pptx(file_path, parsed_doc)
        elif ext in (".xlsx", ".xls"):
            parse_xlsx(file_path, parsed_doc)
        else:
            parse_text(file_path, parsed_doc)
        return finalize_parsed_document(
            parsed_doc,
            parser_type=parser_type,
            processing_mode=processing_mode,
            file_path=file_path,
            skip_enhancement=skip_enhancement,
            figure_storage_dir=figure_storage_dir,
        )

    if ext == ".docx":
        parsed_doc.file_type = "design_report"
        parse_docx(file_path, parsed_doc)
    elif ext == ".doc":
        parsed_doc.file_type = "design_report"
        parse_doc(file_path, parsed_doc)
    elif ext == ".pdf":
        parsed_doc.file_type = "design_report"
        parse_pdf(file_path, parsed_doc)
        apply_pdf_postprocess(parsed_doc)
    elif ext in (".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"):
        parsed_doc.file_type = "image_document"
        mode = (processing_mode or "OPTIMAL").upper()
        if mode == "HIGH_SPEED" or parser_type == "local":
            parse_image_minimal(file_path, file_name, parsed_doc)
        else:
            parse_image_auto(file_path, file_name, parsed_doc, processing_mode=processing_mode)
    elif ext in (".html", ".htm"):
        parsed_doc.file_type = "html_document"
        parse_html(file_path, parsed_doc)
    elif ext == ".pptx":
        parsed_doc.file_type = "presentation"
        parse_pptx(file_path, parsed_doc)
    elif ext in (".txt", ".md", ".csv"):
        parsed_doc.file_type = "attachment" if ext == ".csv" else "design_report"
        parse_text(file_path, parsed_doc)
    elif ext in (".xlsx", ".xls"):
        parsed_doc.file_type = "attachment"
        parse_xlsx(file_path, parsed_doc)
    else:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"Unsupported file extension: {ext}")

    return finalize_parsed_document(
        parsed_doc,
        parser_type=parser_type,
        processing_mode=processing_mode,
        file_path=file_path,
        skip_enhancement=skip_enhancement,
    )
