"""PDF pdftotext format parser."""

from __future__ import annotations

import subprocess
import uuid

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock


def parse_pdf(file_path: str, parsed_doc: ParsedDocument) -> None:
    parsed_doc.parser_name = "pdftotext"
    try:
        result = subprocess.run(
            ["pdftotext", file_path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        text = result.stdout
        if not text or not text.strip():
            parsed_doc.parse_status = "degraded"
            parsed_doc.warnings.append("PDF text extraction resulted in empty output.")
            return

        blocks = []
        for line in text.split("\n\n"):
            line = line.strip()
            if not line or all(ch in "\f\r\n\t " for ch in line):
                continue

            block_type = "paragraph"
            # simple heuristic for headings in pdfs
            if len(line) < 100 and any(char.isdigit() for char in line[:3]) and "\n" not in line:
                block_type = "heading"

            blocks.append(ParsedDocumentBlock(
                block_id=str(uuid.uuid4()),
                block_type=block_type,
                text=line,
                order_index=len(blocks)
            ))
        parsed_doc.blocks = blocks
        parsed_doc.parse_status = "ok" if blocks else "degraded"
        if not blocks:
            parsed_doc.warnings.append("PDF text extraction produced no readable blocks (likely scanned PDF).")
    except Exception as e:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"PDF extraction failed: {e}")
