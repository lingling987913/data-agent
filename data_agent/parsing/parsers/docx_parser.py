"""DOCX / DOC format parsers."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import uuid
import zipfile
import xml.etree.ElementTree as ET

from data_agent.parsing.ingestion import markdown_table as _markdown_table
from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock

logger = logging.getLogger(__name__)


def parse_docx(file_path: str, parsed_doc: ParsedDocument, is_fallback: bool = False) -> None:
    parsed_doc.parser_name = "python-docx"
    try:
        import docx
        doc = docx.Document(file_path)
        blocks = []
        for element in doc.element.body:
            if element.tag.endswith('p'):
                para = docx.text.paragraph.Paragraph(element, doc)
                text = para.text.strip()
                if not text:
                    continue
                style_name = para.style.name if para.style else ""

                block_type = "paragraph"
                level = None

                if style_name.startswith("Heading"):
                    block_type = "heading"
                    try:
                        level = int(style_name.replace("Heading", "").strip())
                    except ValueError:
                        level = 1

                blocks.append(ParsedDocumentBlock(
                    block_id=str(uuid.uuid4()),
                    block_type=block_type,
                    text=text,
                    level=level,
                    order_index=len(blocks)
                ))
            elif element.tag.endswith('tbl'):
                table = docx.table.Table(element, doc)
                rows: list[list[str]] = []
                for row in table.rows:
                    row_data = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    if any(cell for cell in row_data):
                        rows.append(row_data)
                if rows:
                    width = max(len(row) for row in rows)
                    padded = [row + [""] * (width - len(row)) for row in rows]
                    text = _markdown_table(padded[0], padded[1:])
                    blocks.append(ParsedDocumentBlock(
                        block_id=str(uuid.uuid4()),
                        block_type="table",
                        text=text,
                        order_index=len(blocks)
                    ))
        parsed_doc.blocks = blocks
        if is_fallback:
            parsed_doc.parse_status = "degraded"
    except ImportError:
        parsed_doc.parser_name = "raw_zip_fallback"
        parsed_doc.parse_status = "degraded"
        parsed_doc.warnings.append("python-docx not installed, using raw zip parsing which loses table and heading structure.")
        _fallback_parse_docx_raw(file_path, parsed_doc)
    except Exception as e:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"DOCX extraction failed: {e}")


def _fallback_parse_docx_raw(file_path: str, parsed_doc: ParsedDocument) -> None:
    try:
        with zipfile.ZipFile(file_path) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        blocks = []
        for p in root.findall(".//w:p", ns):
            texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
            text = "".join(texts).strip()
            if text:
                blocks.append(ParsedDocumentBlock(
                    block_id=str(uuid.uuid4()),
                    block_type="paragraph",
                    text=text,
                    order_index=len(blocks)
                ))
        parsed_doc.blocks = blocks
    except Exception as e:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"Raw DOCX fallback failed: {e}")


def parse_doc(file_path: str, parsed_doc: ParsedDocument) -> None:
    # Try converting to docx via soffice
    parsed_doc.parser_name = "soffice_converter"
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            result = subprocess.run(
                ["soffice", "--headless", "--convert-to", "docx", "--outdir", temp_dir, file_path],
                capture_output=True, text=True, timeout=60
            )
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            converted_docx_path = os.path.join(temp_dir, f"{base_name}.docx")

            if result.returncode == 0 and os.path.exists(converted_docx_path):
                parse_docx(converted_docx_path, parsed_doc, is_fallback=True)
                parsed_doc.warnings.append(".doc file was converted to .docx.")
                return
        except Exception as e:
            parsed_doc.warnings.append(f"soffice conversion failed or timeout: {e}")

    # Fallback to olefile extraction
    parsed_doc.parser_name = "olefile_fallback"
    parsed_doc.parse_status = "degraded"
    parsed_doc.warnings.append("Old .doc files are not fully supported and parsing is unreliable. Please convert to .docx and re-upload.")

    try:
        import olefile
        with open(file_path, "rb") as f:
            ole = olefile.OleFileIO(f)
            blocks = []
            if ole.exists("WordDocument"):
                word_stream = ole.openstream("WordDocument").read()
                current_segment = []
                i = 0
                while i < len(word_stream) - 1:
                    code_point = word_stream[i] | (word_stream[i + 1] << 8)
                    if (0x20 <= code_point < 0x7F or 0x2000 <= code_point < 0xFFF0 or code_point in (0x0A, 0x0D, 0x09)):
                        if not 0xD800 <= code_point <= 0xDFFF:
                            current_segment.append(chr(code_point))
                    else:
                        if len(current_segment) >= 4:
                            text = "".join(current_segment).strip()
                            if text:
                                blocks.append(text)
                        current_segment = []
                    i += 2
                if len(current_segment) >= 4:
                    text = "".join(current_segment).strip()
                    if text:
                        blocks.append(text)

            if not blocks:
                f.seek(0)
                raw_text = f.read().decode("gb18030", errors="ignore")
                cleaned = []
                for ch in raw_text:
                    if ch.isprintable() or ch in ("\n", "\r", "\t"):
                        cleaned.append(ch)
                    elif cleaned and cleaned[-1] != "\n":
                        cleaned.append("\n")
                raw_text_clean = "".join(cleaned).strip()
                if raw_text_clean:
                    for para in raw_text_clean.split("\n"):
                        if para.strip():
                            blocks.append(para.strip())

            for b in blocks:
                parsed_doc.blocks.append(ParsedDocumentBlock(
                    block_id=str(uuid.uuid4()),
                    block_type="paragraph",
                    text=b,
                    order_index=len(parsed_doc.blocks)
                ))
            ole.close()
    except Exception as e:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"olefile extraction failed: {e}")
