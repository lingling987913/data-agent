"""HTML format parser."""

from __future__ import annotations

import re
import uuid
from html.parser import HTMLParser
from pathlib import Path

from data_agent.parsing.ingestion import markdown_table as _markdown_table
from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock


class _SimpleHTMLBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[tuple[str, str, int | None]] = []
        self._tag_stack: list[str] = []
        self._buffer: list[str] = []
        self._link_href = ""
        self._in_table = False
        self._table_rows: list[list[str]] = []
        self._table_current_row: list[str] = []
        self._table_cell_buffer: list[str] = []
        self.metadata: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = {str(k).lower(): str(v or "") for k, v in attrs}
        self._tag_stack.append(tag)
        if tag == "table":
            self._flush()
            self._in_table = True
            self._table_rows = []
            self._table_current_row = []
            self._table_cell_buffer = []
        if tag == "tr" and self._in_table:
            self._table_current_row = []
        if tag in {"td", "th"} and self._in_table:
            self._table_cell_buffer = []
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "title"} and not self._in_table:
            self._flush()
        if tag == "meta":
            name = attrs_dict.get("name") or attrs_dict.get("property")
            content = attrs_dict.get("content")
            if name and content:
                self.metadata[name] = content
        if tag == "a":
            self._link_href = attrs_dict.get("href", "")
        if tag == "img":
            alt = attrs_dict.get("alt") or attrs_dict.get("src") or "image"
            src = attrs_dict.get("src", "")
            self.blocks.append(("figure_caption", f"图片: {alt} {src}".strip(), None))

    def handle_endtag(self, tag: str):
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self._flush(block_type="heading", level=level)
        elif tag in {"td", "th"} and self._in_table:
            cell = " ".join(part for part in self._table_cell_buffer if part).strip()
            self._table_cell_buffer = []
            self._table_current_row.append(cell)
        elif tag == "tr" and self._in_table:
            if any(cell.strip() for cell in self._table_current_row):
                self._table_rows.append(self._table_current_row)
            self._table_current_row = []
        elif tag == "table" and self._in_table:
            if any(cell.strip() for cell in self._table_current_row):
                self._table_rows.append(self._table_current_row)
            if self._table_rows:
                width = max(len(row) for row in self._table_rows)
                padded = [row + [""] * (width - len(row)) for row in self._table_rows]
                self.blocks.append(("table", _markdown_table(padded[0], padded[1:]), None))
            self._in_table = False
            self._table_rows = []
            self._table_current_row = []
            self._table_cell_buffer = []
        elif tag in {"p", "li", "title"}:
            self._flush()
        if tag == "a":
            self._link_href = ""
        if self._tag_stack:
            try:
                idx = len(self._tag_stack) - 1 - self._tag_stack[::-1].index(tag)
                del self._tag_stack[idx:]
            except ValueError:
                pass

    def handle_data(self, data: str):
        text = re.sub(r"\s+", " ", data or "").strip()
        if not text:
            return
        if self._link_href:
            text = f"{text} ({self._link_href})"
        if self._in_table and any(tag in {"td", "th"} for tag in self._tag_stack):
            self._table_cell_buffer.append(text)
            return
        self._buffer.append(text)

    def _flush(self, block_type: str = "paragraph", level: int | None = None) -> None:
        text = " ".join(part for part in self._buffer if part).strip()
        self._buffer = []
        if text:
            self.blocks.append((block_type, text, level))

    def close(self):
        self._flush()
        super().close()


def parse_html(file_path: str, parsed_doc: ParsedDocument) -> None:
    parsed_doc.parser_name = "html_parser"
    parsed_doc.file_type = "html_document"
    try:
        raw = Path(file_path).read_bytes()
        html = ""
        for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                html = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        parser = _SimpleHTMLBlockParser()
        parser.feed(html)
        parser.close()
        blocks: list[ParsedDocumentBlock] = []
        for block_type, text, level in parser.blocks:
            if not text:
                continue
            blocks.append(
                ParsedDocumentBlock(
                    block_id=str(uuid.uuid4()),
                    block_type=block_type,
                    text=text,
                    level=level,
                    order_index=len(blocks),
                )
            )
        parsed_doc.blocks = blocks
        if parser.metadata:
            parsed_doc.enhancement_log.append({"kind": "html_metadata", "metadata": parser.metadata})
        if not blocks:
            parsed_doc.parse_status = "degraded"
            parsed_doc.warnings.append("HTML parsed but no readable content blocks were found.")
    except Exception as e:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"HTML parsing failed: {e}")
