from __future__ import annotations

import os
import re
from typing import Iterable

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_HTML_ROW_RE = re.compile(r"<tr\b", re.IGNORECASE)
_HTML_ROWSPAN_RE = re.compile(r"\browspan\s*=\s*['\"]?(\d+)", re.IGNORECASE)
_CONTINUATION_HINTS = ("续表", "（续）", "(续)", "续上表", "接上表")
_MAX_HTML_TABLE_ROWS = int(os.getenv("PARSING_MAX_HTML_TABLE_ROWS", "80"))
_MAX_HTML_TABLE_ROWSPAN = int(os.getenv("PARSING_MAX_HTML_TABLE_ROWSPAN", "50"))


def _table_columns(markdown: str) -> int | None:
    lines = [ln.strip() for ln in markdown.splitlines() if ln.strip()]
    for line in lines:
        if _TABLE_ROW_RE.match(line):
            return line.count("|") - 1
    return None


def _is_table_continuation(prev: ParsedDocumentBlock, curr: ParsedDocumentBlock) -> bool:
    if prev.block_type != "table" or curr.block_type != "table":
        return False
    prev_cols = _table_columns(prev.table_markdown or prev.text)
    curr_cols = _table_columns(curr.table_markdown or curr.text)
    if not prev_cols or not curr_cols or prev_cols != curr_cols:
        return False
    if prev.page_hint and curr.page_hint and curr.page_hint == prev.page_hint + 1:
        return True
    if any(h in curr.text[:80] for h in _CONTINUATION_HINTS):
        return True
    # 无页码时：相邻 table 块且列数一致，视为跨页续表
    return prev.page_hint is None or curr.page_hint is None


def _merge_table_markdown(a: str, b: str) -> str:
    lines_a = [ln for ln in a.splitlines() if ln.strip()]
    lines_b = [ln for ln in b.splitlines() if ln.strip()]
    if not lines_a:
        return b
    if not lines_b:
        return a
    # 去掉 B 的表头分隔行（---）若存在
    if len(lines_b) >= 2 and set(lines_b[1].replace("|", "").replace("-", "").strip()) <= {""}:
        lines_b = lines_b[2:]
    elif lines_b and any(h in lines_b[0] for h in _CONTINUATION_HINTS):
        lines_b = lines_b[1:]
    return "\n".join(lines_a + lines_b)


def _has_layout_bbox(block: ParsedDocumentBlock) -> bool:
    return isinstance(block.bbox, list) and len(block.bbox) >= 4


def _can_merge_table_blocks(prev: ParsedDocumentBlock, curr: ParsedDocumentBlock) -> bool:
    """Only merge text-only table continuations.

    Layout-aware parsers (MinerU) attach bbox/page_hint per page. Merging those
    blocks collapses later pages into the previous page and drops positioning.
    """
    if _has_layout_bbox(prev) or _has_layout_bbox(curr):
        return False
    if prev.page_hint is not None and curr.page_hint is not None and prev.page_hint != curr.page_hint:
        return False
    return _is_table_continuation(prev, curr)


def merge_cross_page_tables(blocks: list[ParsedDocumentBlock]) -> tuple[list[ParsedDocumentBlock], int]:
    """合并跨页表格块，返回新 blocks 与合并次数。"""
    if not blocks:
        return blocks, 0

    merged: list[ParsedDocumentBlock] = []
    merge_count = 0
    i = 0
    while i < len(blocks):
        current = blocks[i]
        if current.block_type == "table" and i + 1 < len(blocks):
            nxt = blocks[i + 1]
            if _can_merge_table_blocks(current, nxt):
                text_a = current.table_markdown or current.text
                text_b = nxt.table_markdown or nxt.text
                combined = _merge_table_markdown(text_a, text_b)
                merged.append(
                    ParsedDocumentBlock(
                        block_id=current.block_id,
                        block_type="table",
                        text=combined,
                        table_markdown=combined,
                        page_hint=current.page_hint,
                        order_index=len(merged),
                        children=[*current.children, *nxt.children],
                    )
                )
                merge_count += 1
                i += 2
                continue
        copy = current.model_copy(update={"order_index": len(merged)})
        merged.append(copy)
        i += 1
    return merged, merge_count


def detect_scanned_pdf(parsed_doc: ParsedDocument) -> bool:
    """启发式：pdftotext 无有效块或仅 form-feed。"""
    if parsed_doc.parser_name != "pdftotext":
        return False
    if parsed_doc.blocks:
        return False
    return parsed_doc.parse_status == "degraded"


def _html_table_structure_stats(text: str) -> tuple[int, int] | None:
    value = (text or "").strip()
    if not value.lower().startswith("<table") or "</table>" not in value.lower():
        return None
    row_count = len(_HTML_ROW_RE.findall(value))
    rowspans = [int(item) for item in _HTML_ROWSPAN_RE.findall(value)]
    max_rowspan = max(rowspans) if rowspans else 0
    return row_count, max_rowspan


def detect_table_structure_anomalies(blocks: list[ParsedDocumentBlock]) -> int:
    """Mark tables that MinerU likely over-split into excessive rows/cells."""
    count = 0
    for block in blocks:
        if "table" not in (block.block_type or "").lower():
            continue
        stats = _html_table_structure_stats(block.table_markdown or block.text)
        if stats is None:
            continue
        row_count, max_rowspan = stats
        if row_count <= _MAX_HTML_TABLE_ROWS and max_rowspan <= _MAX_HTML_TABLE_ROWSPAN:
            continue
        if "table_structure_anomaly" not in block.format_damage_types:
            block.format_damage_types.append("table_structure_anomaly")
        count += 1
    return count


_SCANNED_PDF_WARNING = (
    "检测到扫描型 PDF，建议启用 MinerU OCR（MINERU_LOCAL_PARSE_METHOD=ocr 或 MINERU_AGENT_IS_OCR=true）。"
)
_SCANNED_PDF_MINERU_ATTEMPTED_WARNING = (
    "扫描型 PDF：MinerU OCR 已尝试但未能提取有效文本，请检查 MinerU Token、服务状态或本地 MinerU 配置。"
)
_SCANNED_PDF_CONFIGURED_BUT_SKIPPED_WARNING = (
    "扫描型 PDF：已配置 MinerU Token/OCR，但未执行 MinerU 解析（请确认 MINERU_API_MODE 非 disabled、"
    "解析层级非 lite，并重启后端以加载 .env）。"
)


def _env_bool(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _mineru_configured() -> bool:
    from data_agent.parsing.mineru_config import mineru_online_configured

    return mineru_online_configured()


def _scanned_pdf_warning(parsed_doc: ParsedDocument) -> str:
    logs = parsed_doc.parser_fallback_logs or []
    mineru_attempted = any(
        str(log.get("source_parser") or "").startswith("mineru")
        for log in logs
    )
    if mineru_attempted:
        return _SCANNED_PDF_MINERU_ATTEMPTED_WARNING
    if _mineru_configured():
        return _SCANNED_PDF_CONFIGURED_BUT_SKIPPED_WARNING
    return _SCANNED_PDF_WARNING


def _append_warning_once(parsed_doc: ParsedDocument, message: str) -> None:
    if message not in parsed_doc.warnings:
        parsed_doc.warnings.append(message)


def apply_pdf_postprocess(parsed_doc: ParsedDocument) -> ParsedDocument:
    """PDF 解析后处理：跨页表格合并 + 扫描件/表格结构异常提示。"""
    if not parsed_doc.blocks:
        if detect_scanned_pdf(parsed_doc):
            _append_warning_once(parsed_doc, _scanned_pdf_warning(parsed_doc))
        return parsed_doc

    merged_blocks, count = merge_cross_page_tables(parsed_doc.blocks)
    parsed_doc.blocks = merged_blocks
    if count:
        parsed_doc.warnings.append(f"已合并 {count} 组跨页表格。")
    anomaly_count = detect_table_structure_anomalies(parsed_doc.blocks)
    if anomaly_count:
        _append_warning_once(
            parsed_doc,
            f"检测到 {anomaly_count} 个疑似表格结构异常：OCR 结果行数或 rowspan 过大，建议检查页面方向后重新解析。",
        )
    return parsed_doc
