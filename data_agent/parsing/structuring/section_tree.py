"""Section tree construction from parsed documents."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from data_agent.parsing.schemas import (
    DocumentSection,
    DocumentSectionTree,
    DocumentTocEntry,
    ParsedDocument,
    ParsedDocumentBlock,
)

logger = logging.getLogger(__name__)

# 编号标题正则: 匹配 "1", "1.1", "3.2.4" 等开头的行
_NUMBERED_HEADING_RE = re.compile(
    r"^(\d+(?:\.\d+)*)\s+(.+)$"
)
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

_TOC_TITLE_MARKERS = {"目录", "目 录", "contents", "table of contents"}
_TOC_SPLIT_RE = re.compile(r"(?:\.{2,}|…{2,}|·{2,}|-{2,}|_{2,}|\s{2,}|\t+)")
_TOC_TRAILING_PAGE_RE = re.compile(r"^(?P<content>.+?)\s*(?P<page>\d{1,4})$")


@dataclass
class _TocDetectionResult:
    toc_entries: list[DocumentTocEntry]
    toc_block_indexes: set[int]


def _condense_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip().lower()


def _normalize_title_for_match(text: str) -> str:
    text = (text or "").strip()
    num_info = _detect_numbered_heading(text)
    if num_info:
        text = num_info[1]
    text = re.sub(r"^[第]\s*[一二三四五六七八九十百千0-9]+\s*[章节篇部卷]\s*", "", text)
    return re.sub(r"[\s\-\._:：、,，;；()（）【】\[\]《》<>\"'“”‘’·]+", "", text).lower()


def _split_block_into_lines(block: ParsedDocumentBlock) -> list[str]:
    return [line.strip() for line in re.split(r"[\r\n]+", block.text or "") if line.strip()]


def _parse_toc_entry_line(line: str) -> tuple[str, str, int, int | None] | None:
    """解析单行目录项。

    返回 (number, title, level, page_number)；若不是目录项返回 None。
    """
    raw = (line or "").strip()
    if not raw or len(raw) > 120:
        return None

    if _condense_text(raw) in _TOC_TITLE_MARKERS:
        return None

    page_match = _TOC_TRAILING_PAGE_RE.match(raw)
    if not page_match:
        return None

    content = page_match.group("content").strip()
    page_number = int(page_match.group("page"))
    if page_number <= 0:
        return None

    leader_split = _TOC_SPLIT_RE.split(content, maxsplit=1)
    if leader_split:
        content = leader_split[0].strip()

    content = content.rstrip(".。:：-—_ ").strip()
    if len(content) < 2:
        return None

    number = ""
    level = 1
    title = content

    num_info = _detect_numbered_heading(content)
    if num_info:
        number, title, level = num_info
    elif re.match(r"^第\s*[一二三四五六七八九十百千0-9]+\s*[章节篇部卷]", content):
        prefix = re.match(r"^(第\s*[一二三四五六七八九十百千0-9]+\s*[章节篇部卷])", content).group(1)
        number = re.sub(r"\s+", "", prefix)
        title = re.sub(r"^第\s*[一二三四五六七八九十百千0-9]+\s*[章节篇部卷]\s*", "", content).strip()
        level = 1

    title = title.strip()
    if not title or len(title) > 80:
        return None

    has_leader = bool(_TOC_SPLIT_RE.search(page_match.group("content")))
    if not has_leader and len(title) > 40:
        return None

    return number, title, level, page_number


def _detect_toc_entries(parsed_doc: ParsedDocument, max_scan_blocks: int = 40) -> _TocDetectionResult:
    """识别文档开头的目录区，并提取目录项。"""
    candidate_lines: list[tuple[int, str]] = []
    toc_heading_line_idx: int | None = None
    toc_heading_block_idx: int | None = None

    for block_idx, block in enumerate(parsed_doc.blocks[:max_scan_blocks]):
        if block.page_hint and block.page_hint > 2:
            break

        for line in _split_block_into_lines(block):
            if not line:
                continue
            line_idx = len(candidate_lines)
            candidate_lines.append((block_idx, line))
            if _condense_text(line) in _TOC_TITLE_MARKERS and toc_heading_line_idx is None:
                toc_heading_line_idx = line_idx
                toc_heading_block_idx = block_idx

    if not candidate_lines:
        return _TocDetectionResult(toc_entries=[], toc_block_indexes=set())

    parsed_candidates = [
        (block_idx, line, _parse_toc_entry_line(line))
        for block_idx, line in candidate_lines
    ]
    entry_positions = [idx for idx, (_, _, entry) in enumerate(parsed_candidates) if entry is not None]
    if len(entry_positions) < 3:
        return _TocDetectionResult(toc_entries=[], toc_block_indexes=set())

    start_line_idx = toc_heading_line_idx + 1 if toc_heading_line_idx is not None else entry_positions[0]
    toc_entries: list[DocumentTocEntry] = []
    toc_block_indexes: set[int] = set()
    consecutive_misses = 0
    seen_entries = 0

    for idx in range(start_line_idx, len(parsed_candidates)):
        block_idx, line, parsed_entry = parsed_candidates[idx]
        if parsed_entry is not None:
            number, title, level, page_number = parsed_entry
            toc_entries.append(DocumentTocEntry(
                entry_id=str(uuid.uuid4())[:12],
                title=title,
                raw_text=line,
                number=number,
                level=level,
                page_number=page_number,
                source_file_name=parsed_doc.file_name,
            ))
            toc_block_indexes.add(block_idx)
            seen_entries += 1
            consecutive_misses = 0
            continue

        if not _condense_text(line):
            continue

        if seen_entries == 0 and idx - start_line_idx > 2:
            break

        consecutive_misses += 1
        if seen_entries >= 3 and consecutive_misses >= 2:
            break

    if len(toc_entries) < 3:
        return _TocDetectionResult(toc_entries=[], toc_block_indexes=set())

    if toc_heading_block_idx is not None:
        toc_block_indexes.add(toc_heading_block_idx)

    logger.info(f"[SectionTree] 检测到目录区: {len(toc_entries)} 项, file={parsed_doc.file_name}")
    return _TocDetectionResult(toc_entries=toc_entries, toc_block_indexes=toc_block_indexes)


def _clone_parsed_doc_with_blocks(parsed_doc: ParsedDocument, blocks: list[ParsedDocumentBlock]) -> ParsedDocument:
    normalized_blocks: list[ParsedDocumentBlock] = []
    for idx, block in enumerate(blocks):
        normalized_blocks.append(ParsedDocumentBlock(
            block_id=block.block_id,
            block_type=block.block_type,
            text=block.text,
            level=block.level,
            page_hint=block.page_hint,
            order_index=idx,
        ))

    return ParsedDocument(
        document_id=parsed_doc.document_id,
        file_name=parsed_doc.file_name,
        file_type=parsed_doc.file_type,
        parser_name=parsed_doc.parser_name,
        parse_status=parsed_doc.parse_status,
        blocks=normalized_blocks,
        warnings=list(parsed_doc.warnings),
    )


def _prepare_doc_for_chunking(
    parsed_doc: ParsedDocument,
    toc_entries: list[DocumentTocEntry] | None = None,
    toc_block_indexes: set[int] | None = None,
) -> tuple[ParsedDocument, list[DocumentTocEntry], set[int]]:
    if toc_entries is None or toc_block_indexes is None:
        detected = _detect_toc_entries(parsed_doc)
        if toc_entries is None:
            toc_entries = detected.toc_entries
        if toc_block_indexes is None:
            toc_block_indexes = detected.toc_block_indexes

    filtered_blocks = [
        block
        for idx, block in enumerate(parsed_doc.blocks)
        if idx not in (toc_block_indexes or set())
    ]
    return _clone_parsed_doc_with_blocks(parsed_doc, filtered_blocks), (toc_entries or []), (toc_block_indexes or set())


def _build_toc_title_map(toc_entries: list[DocumentTocEntry]) -> dict[str, DocumentTocEntry]:
    title_map: dict[str, DocumentTocEntry] = {}
    for entry in toc_entries:
        key = _normalize_title_for_match(entry.title)
        if key and key not in title_map:
            title_map[key] = entry
    return title_map


def _resolve_heading_from_block(
    block: ParsedDocumentBlock,
    toc_title_map: dict[str, DocumentTocEntry],
) -> tuple[str, str, int] | None:
    """统一的标题识别入口。"""
    raw_text = (block.text or "").strip()
    if not raw_text:
        return None

    if block.block_type == "heading" and block.level is not None:
        heading_level = block.level
        heading_title = raw_text
        heading_number = ""
        num_info = _detect_numbered_heading(heading_title)
        if num_info:
            heading_number = num_info[0]
            heading_title = num_info[1]
            heading_level = num_info[2]
        return heading_number, heading_title, heading_level

    num_info = _detect_numbered_heading(raw_text)
    if num_info:
        return num_info

    normalized = _normalize_title_for_match(raw_text)
    toc_entry = toc_title_map.get(normalized)
    if toc_entry and len(raw_text) <= 120:
        return toc_entry.number, toc_entry.title, toc_entry.level

    return None


def _attach_toc_matches(
    toc_entries: list[DocumentTocEntry],
    sections: list[DocumentSection],
) -> list[DocumentTocEntry]:
    if not toc_entries or not sections:
        return toc_entries

    sections_by_title: dict[str, list[DocumentSection]] = {}
    for section in sections:
        sections_by_title.setdefault(_normalize_title_for_match(section.title), []).append(section)

    updated_entries: list[DocumentTocEntry] = []
    for entry in toc_entries:
        matched_section_id: str | None = None
        candidates = sections_by_title.get(_normalize_title_for_match(entry.title), [])
        if entry.number:
            for candidate in candidates:
                if candidate.number == entry.number:
                    matched_section_id = candidate.section_id
                    break
        if matched_section_id is None and candidates:
            matched_section_id = candidates[0].section_id
        updated_entries.append(entry.model_copy(update={"matched_section_id": matched_section_id}))
    return updated_entries


def _detect_numbered_heading(text: str) -> tuple[str, str, int] | None:
    """尝试从段落文本中识别编号标题。

    返回 (number, title_text, level) 或 None。
    level 由编号中的点号数决定: "1" -> 1, "1.1" -> 2, "3.2.4" -> 3
    """
    text = text.strip()
    if not text or len(text) > 200:  # 标题不应过长
        return None
    m = _NUMBERED_HEADING_RE.match(text)
    if not m:
        return None
    number = m.group(1)
    title_text = m.group(2).strip()
    level = number.count(".") + 1
    # 排除纯数字行或过短无意义标题
    if not title_text or len(title_text) < 2:
        return None
    return number, title_text, level


def _build_presentation_section_tree(parsed_doc: ParsedDocument) -> DocumentSectionTree:
    """Build one root section per slide for presentation documents."""
    slides: dict[int, list[ParsedDocumentBlock]] = {}
    for block in parsed_doc.blocks:
        page_no = int(block.page_hint or 1)
        slides.setdefault(page_no, []).append(block)

    sections: list[DocumentSection] = []
    root_ids: list[str] = []
    for slide_no in sorted(slides):
        blocks = slides[slide_no]
        text_parts: list[str] = []
        title = f"Slide {slide_no}"
        for block in blocks:
            text = (block.text or "").strip()
            if not text:
                continue
            if title == f"Slide {slide_no}" and block.block_type in {"heading", "paragraph"}:
                title = text.split("\n", 1)[0].strip() or title
            text_parts.append(text)

        section_id = str(uuid.uuid4())[:12]
        order_indexes = [block.order_index for block in blocks]
        sections.append(
            DocumentSection(
                section_id=section_id,
                title=title,
                level=1,
                start_block_index=min(order_indexes),
                end_block_index=max(order_indexes),
                page_hint_start=slide_no,
                page_hint_end=slide_no,
                text="\n\n".join(text_parts),
                source_file_name=parsed_doc.file_name,
            )
        )
        root_ids.append(section_id)

    logger.info(
        "[SectionTree] PPT 章节树: %s 张幻灯片, %s 个根节点",
        len(sections),
        len(root_ids),
    )
    return DocumentSectionTree(sections=sections, root_section_ids=root_ids)


def build_section_tree(
    parsed_doc: ParsedDocument,
    toc_entries: list[DocumentTocEntry] | None = None,
    toc_block_indexes: set[int] | None = None,
) -> DocumentSectionTree:
    """从 ParsedDocument 的 blocks 构建章节树。

    识别方式:
      1. block_type == "heading" 且有 level (来自 Word Heading 样式)
      2. block_type == "paragraph" 但文本匹配编号标题正则 (如 "1.1 xxx")
      3. file_type == "presentation" 时每张幻灯片独立成节

    章节树构建规则:
      - 遇到标题块时, 创建新 DocumentSection
      - 标题块之后的 paragraph/table 块归属到该 section
      - 父子关系由 level 比较决定: 遇到同级或更高级标题时回退
      - 每个 section 的 text 字段是其直属内容块的拼接
    """
    prepared_doc, toc_entries, _ = _prepare_doc_for_chunking(
        parsed_doc,
        toc_entries=toc_entries,
        toc_block_indexes=toc_block_indexes,
    )
    if prepared_doc.file_type == "presentation":
        return _build_presentation_section_tree(prepared_doc)
    toc_title_map = _build_toc_title_map(toc_entries)

    sections: list[DocumentSection] = []
    root_ids: list[str] = []

    # 栈: [(section_id, level)] — 用于追踪当前层级链
    stack: list[tuple[str, int]] = []
    current_section: DocumentSection | None = None
    current_text_parts: list[str] = []

    def _finalize_section():
        nonlocal current_section, current_text_parts
        if current_section is not None:
            current_section.text = "\n\n".join(current_text_parts)
            current_text_parts = []

    for block in prepared_doc.blocks:
        heading_info = _resolve_heading_from_block(block, toc_title_map)
        heading_level: int | None = heading_info[2] if heading_info else None
        heading_number: str = heading_info[0] if heading_info else ""
        heading_title: str = heading_info[1] if heading_info else ""

        if heading_level is not None and heading_title:
            # ── 创建新章节 ──
            _finalize_section()

            section_id = str(uuid.uuid4())[:12]

            # 回退栈到正确的父级
            while stack and stack[-1][1] >= heading_level:
                stack.pop()

            parent_id = stack[-1][0] if stack else None

            section = DocumentSection(
                section_id=section_id,
                title=heading_title,
                level=heading_level,
                number=heading_number,
                parent_section_id=parent_id,
                start_block_index=block.order_index,
                end_block_index=block.order_index,  # 会被后续块更新
                page_hint_start=block.page_hint,
                source_file_name=prepared_doc.file_name,
            )
            sections.append(section)

            # 维护父子关系
            if parent_id:
                parent = next((s for s in sections if s.section_id == parent_id), None)
                if parent:
                    parent.children_ids.append(section_id)
            else:
                root_ids.append(section_id)

            stack.append((section_id, heading_level))
            current_section = section
            current_text_parts = []
        else:
            # ── 内容块: 归属到当前章节 ──
            if current_section is not None:
                current_section.end_block_index = block.order_index
                current_section.page_hint_end = block.page_hint
                current_text_parts.append(block.text)

    _finalize_section()

    matched_toc_entries = _attach_toc_matches(toc_entries, sections)

    logger.info(
        f"[SectionTree] 构建完成: {len(sections)} 个章节, "
        f"{len(root_ids)} 个根节点, toc={len(matched_toc_entries)}"
    )
    return DocumentSectionTree(
        sections=sections,
        root_section_ids=root_ids,
        toc_entries=matched_toc_entries,
    )
