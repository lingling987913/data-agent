"""Material ingestion boundary for standalone parsing.

This module converts uploaded files into the MaterialItem-compatible markdown
payload used by downstream workflows. It deliberately keeps parser invocation
behind a small function boundary so public parsing APIs can depend on ingestion
without importing review or task services.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from data_agent.parsing.schemas import ParsedDocument


@dataclass
class UploadedMaterialParseResult:
    file_type: str
    content: str
    parse_status: str
    parser_name: str
    warnings: list[str]
    parsed_document: ParsedDocument | None = None
    parser_fallback_logs: list[dict] | None = None
    self_healing_records: list[dict] | None = None


def sanitize_material_text(value: str) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value if not 0xD800 <= ord(ch) <= 0xDFFF)


def normalize_material_text(value: str) -> str:
    text = sanitize_material_text(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip():
            normalized.append(line)
            blank_run = 0
        else:
            blank_run += 1
            if blank_run <= 2:
                normalized.append("")
    return "\n".join(normalized).strip()


def material_title(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def material_file_type(file_name: str, parsed_file_type: str = "unknown") -> str:
    ext = os.path.splitext(file_name)[1].lower()
    if ext in (".csv", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
        return "attachment"
    if ext in (".txt", ".md", ".doc", ".docx", ".pdf"):
        return "design_report"
    return parsed_file_type if parsed_file_type != "unknown" else "attachment"


def markdown_from_material_text(filename: str, text: str) -> str:
    body = normalize_material_text(text)
    title = material_title(filename) or "document"
    if not body:
        return f"# {title}\n\n> 未提取到文本内容"
    return f"# {title}\n\n{body}"


def _escape_markdown_table_cell(value: object) -> str:
    return str(value).replace("\n", "<br>").replace("|", "\\|")


def _split_pipe_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|") and stripped.endswith("|"):
        stripped = stripped[1:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _looks_like_gfm_markdown_table(text: str) -> bool:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    for index in range(1, len(lines)):
        if re.match(r"^\|?\s*:?-{3,}", lines[index]):
            return True
    return False


def pipe_delimited_text_to_markdown_table(text: str) -> str:
    normalized = normalize_material_text(text)
    if not normalized or _looks_like_gfm_markdown_table(normalized):
        return text

    rows: list[list[str]] = []
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            if rows:
                break
            continue
        rows.append(_split_pipe_table_row(stripped))

    if len(rows) < 2:
        return text

    width = max(len(row) for row in rows)
    if width < 2:
        return text

    padded = [row + [""] * (width - len(row)) for row in rows]
    return markdown_table(padded[0], padded[1:])


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    safe_headers = [(_escape_markdown_table_cell(h) or " ") for h in headers]
    header_line = "| " + " | ".join(safe_headers) + " |"
    separator_line = "| " + " | ".join(["---"] * len(safe_headers)) + " |"
    body_lines = []
    for row in rows:
        safe_row = [_escape_markdown_table_cell(cell) for cell in row]
        body_lines.append("| " + " | ".join(safe_row) + " |")
    return "\n".join([header_line, separator_line, *body_lines])


def parsed_document_to_markdown(parsed_doc: ParsedDocument) -> str:
    parts: list[str] = []
    for block in parsed_doc.blocks:
        text = (block.text or "").strip()
        if not text:
            continue
        if block.block_type == "heading":
            level = max(2, min(block.level or 2, 6))
            parts.append(f"{'#' * level} {text}")
        elif block.block_type == "table":
            parts.append(pipe_delimited_text_to_markdown_table(text))
        else:
            parts.append(text)
    return markdown_from_material_text(parsed_doc.file_name, "\n\n".join(parts))


def read_text_file_as_markdown(file_path: str, file_name: str) -> str:
    with open(file_path, "rb") as f:
        raw_content = f.read()
    extracted_text = ""
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            extracted_text = raw_content.decode(enc)
            break
        except Exception:
            continue
    return markdown_from_material_text(file_name, extracted_text)


def csv_file_as_markdown(file_path: str, file_name: str) -> str:
    import csv

    with open(file_path, "rb") as f:
        raw_content = f.read()
    extracted_text = ""
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            extracted_text = raw_content.decode(enc)
            break
        except Exception:
            continue
    normalized = normalize_material_text(extracted_text)
    if not normalized:
        return markdown_from_material_text(file_name, extracted_text)

    try:
        rows = list(csv.reader(normalized.splitlines()))
        if not rows:
            return markdown_from_material_text(file_name, extracted_text)
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        table = markdown_table(padded[0], padded[1:])
        return f"# {material_title(file_name)}\n\n{table}"
    except Exception:
        return markdown_from_material_text(file_name, extracted_text)


def ingest_uploaded_material(
    file_path: str,
    file_name: str,
    parser_type: str = "local",
    processing_mode: str | None = None,
    mineru_parse_mode: str | None = None,
    skip_enhancement: bool = False,
    figure_storage_dir: str | None = None,
) -> UploadedMaterialParseResult:
    """Parse an uploaded material and produce the content stored on MaterialItem."""
    from data_agent.parsing.parser_core import parse_uploaded_document

    ext = os.path.splitext(file_name)[1].lower()

    try:
        parsed_doc = parse_uploaded_document(
            file_path,
            file_name,
            parser_type=parser_type,
            processing_mode=processing_mode,
            mineru_parse_mode=mineru_parse_mode,
            skip_enhancement=skip_enhancement,
            figure_storage_dir=figure_storage_dir,
        )
    except Exception as e:
        return UploadedMaterialParseResult(
            file_type="attachment",
            content=markdown_from_material_text(file_name, f"[文档解析失败: {e}]"),
            parse_status="failed",
            parser_name="unknown",
            warnings=[f"System error during parsing: {str(e)}"],
        )

    if ext == ".csv":
        content = csv_file_as_markdown(file_path, file_name)
    elif ext in (".txt", ".md"):
        content = read_text_file_as_markdown(file_path, file_name)
    elif parsed_doc.blocks:
        content = parsed_document_to_markdown(parsed_doc)
    elif parsed_doc.warnings:
        content = markdown_from_material_text(file_name, "\n".join(f"[{w}]" for w in parsed_doc.warnings))
    else:
        content = markdown_from_material_text(file_name, "")

    return UploadedMaterialParseResult(
        file_type=material_file_type(file_name, parsed_doc.file_type),
        content=sanitize_material_text(content),
        parse_status=parsed_doc.parse_status,
        parser_name=parsed_doc.parser_name,
        warnings=list(parsed_doc.warnings),
        parsed_document=parsed_doc,
        parser_fallback_logs=list(parsed_doc.parser_fallback_logs),
        self_healing_records=list(parsed_doc.self_healing_records),
    )
