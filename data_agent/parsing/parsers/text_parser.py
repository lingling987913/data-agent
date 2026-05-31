"""Plain text / markdown format parser."""

from __future__ import annotations

import re
import uuid

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def parse_text(file_path: str, parsed_doc: ParsedDocument) -> None:
    parsed_doc.parser_name = "text_reader"
    try:
        with open(file_path, "rb") as f:
            raw_content = f.read()
        extracted_text = ""
        for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                extracted_text = raw_content.decode(enc)
                break
            except Exception:
                continue

        blocks: list[ParsedDocumentBlock] = []
        pending: list[str] = []
        lines = extracted_text.splitlines()
        line_index = 0

        def _flush_paragraph() -> None:
            text = "\n".join(pending).strip()
            pending.clear()
            if not text:
                return
            blocks.append(
                ParsedDocumentBlock(
                    block_id=str(uuid.uuid4()),
                    block_type="paragraph",
                    text=text,
                    order_index=len(blocks),
                )
            )

        while line_index < len(lines):
            raw_line = lines[line_index]
            stripped = raw_line.strip()
            next_line = lines[line_index + 1].strip() if line_index + 1 < len(lines) else ""
            if "|" in stripped and next_line and re.match(r"^\|?\s*:?-{3,}", next_line):
                _flush_paragraph()
                table_lines = [stripped]
                line_index += 1
                while line_index < len(lines):
                    row = lines[line_index].strip()
                    if not row or "|" not in row:
                        break
                    table_lines.append(row)
                    line_index += 1
                blocks.append(
                    ParsedDocumentBlock(
                        block_id=str(uuid.uuid4()),
                        block_type="table",
                        text="\n".join(table_lines),
                        order_index=len(blocks),
                    )
                )
                continue

            heading_match = _MD_HEADING_RE.match(stripped)
            if heading_match:
                _flush_paragraph()
                blocks.append(
                    ParsedDocumentBlock(
                        block_id=str(uuid.uuid4()),
                        block_type="heading",
                        text=heading_match.group(2).strip(),
                        level=len(heading_match.group(1)),
                        order_index=len(blocks),
                    )
                )
                line_index += 1
                continue
            if not stripped:
                _flush_paragraph()
                line_index += 1
                continue
            pending.append(raw_line.rstrip())
            line_index += 1

        _flush_paragraph()
        parsed_doc.blocks = blocks
    except Exception as e:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"Text parsing failed: {e}")
