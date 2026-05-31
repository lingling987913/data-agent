"""Deterministic pre-screening rules for parse rationality calibration."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from data_agent.agents.parse_calibrator.schemas import CalibrationContext
from data_agent.parsing.schemas import ParsedDocumentBlock, ParseCalibrationRecord

_TEMP_RANGE_RE = re.compile(
    r"(?P<base>-?\d+(?:\.\d+)?)\s*(?:°\s*C|℃)\s*[±]\s*"
    r"(?P<tol>\d+(?:\.\d+)?)\s*(?:°\s*C|℃)?",
    re.IGNORECASE,
)
_TEMP_VALUE_RE = re.compile(r"(?<![\d.])(?P<value>-?\d+(?:\.\d+)?)\s*(?:°\s*C|℃)", re.IGNORECASE)
_TEMP_RESULT_KEYWORDS = ("实测", "检测结果", "检查结果", "试验结果", "结果", "记录值", "测量值")
_DIAMETER_KEYWORDS = ("外径", "内径", "直径", "孔径", "轴径", "转子", "定子")
_DIAMETER_REF_RE = re.compile(r"[Φφ]\s*(?P<num>\d+(?:\.\d+)?)")
_DIAMETER_COMPACT_CONFUSION_RE = re.compile(r"(?<![\d.])4\s*\d{4,6}(?![\d.])")
_DIAMETER_CONFUSION_SHORT_RE = re.compile(r"(?<![\d.])4\s*(?P<num>\d{2,3}(?:\.\d+)?)(?![\d.])")
_DIAMETER_LLM_REVIEW_CONFUSION_RE = re.compile(
    r"(?<![\d.])(?:[+＋]\s*\d{2,3}(?:\.\d+)?|[#＃]{2,}(?:\.\d+)?|[#＃]+\s*\d{2,3}(?:\.\d+)?)(?![\d.])"
)
_TABLE_ROW_RE = re.compile(r"<tr\b[^>]*>(?P<body>.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TABLE_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(?P<body>.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_PRODUCT_SERIAL_RE = re.compile(
    r"\b(?P<prefix>[A-Z0-9]{1,2})H-(?P<series>\d{4})-(?P<suffix>\d{2,})\b",
    re.IGNORECASE,
)
_OCR_PREFIX_CHAR_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"L", "4"}),
        frozenset({"I", "1"}),
        frozenset({"O", "0"}),
    }
)


@dataclass(frozen=True)
class _SerialMatch:
    block: ParsedDocumentBlock
    raw_match: str
    full_prefix: str
    series: str
    suffix: str


def build_calibration_contexts(
    blocks: list[ParsedDocumentBlock],
    *,
    context_window: int = 2,
    max_blocks: int = 50,
) -> list[CalibrationContext]:
    ordered = sorted(blocks, key=lambda b: b.order_index)
    contexts: list[CalibrationContext] = []
    seen: set[tuple[str, str]] = set()
    for ctx in _document_serial_consistency_contexts(ordered, context_window=context_window):
        key = (ctx.block.block_id, ctx.issue_type)
        if key in seen:
            continue
        seen.add(key)
        contexts.append(ctx)
        if len(contexts) >= max_blocks:
            return contexts
    for idx, block in enumerate(ordered):
        if not _should_calibrate_block(block, ordered, idx, context_window=context_window):
            continue
        before = ordered[max(0, idx - context_window) : idx]
        after = ordered[idx + 1 : idx + 1 + context_window]
        for ctx in _contexts_for_block(block, before, after):
            key = (ctx.block.block_id, ctx.issue_type)
            if key in seen:
                continue
            seen.add(key)
            contexts.append(ctx)
            if len(contexts) >= max_blocks:
                return contexts
    return contexts


def _normalize_calibration_text(text: str) -> str:
    if not text:
        return ""
    stripped = _HTML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", stripped).strip()


def _document_serial_consistency_contexts(
    ordered: list[ParsedDocumentBlock],
    *,
    context_window: int,
) -> list[CalibrationContext]:
    from data_agent.core.config import (
        get_parsing_serial_consensus_min_majority,
        get_parsing_serial_consensus_ratio,
    )

    matches = _collect_product_serial_matches(ordered)
    if not matches:
        return []

    min_majority = get_parsing_serial_consensus_min_majority()
    min_ratio = get_parsing_serial_consensus_ratio()
    block_index = {block.block_id: idx for idx, block in enumerate(ordered)}

    outliers_by_block: dict[str, list[tuple[_SerialMatch, str, int]]] = {}
    by_series: dict[str, list[_SerialMatch]] = {}
    for match in matches:
        by_series.setdefault(match.series, []).append(match)

    for series, series_matches in by_series.items():
        prefix_counts: dict[str, int] = {}
        for match in series_matches:
            prefix_counts[match.full_prefix] = prefix_counts.get(match.full_prefix, 0) + 1

        majority_prefix = max(prefix_counts, key=prefix_counts.get)
        majority_count = prefix_counts[majority_prefix]
        total = len(series_matches)
        if majority_count < min_majority or majority_count / total < min_ratio:
            continue
        if _series_has_conflicting_prefixes(prefix_counts, majority_prefix, min_majority):
            continue

        for match in series_matches:
            if match.full_prefix == majority_prefix:
                continue
            if not _is_ocr_confusable_prefix(match.full_prefix, majority_prefix):
                continue
            corrected = f"{majority_prefix}-{series}-{match.suffix}"
            outliers_by_block.setdefault(match.block.block_id, []).append(
                (match, corrected, majority_count)
            )

    contexts: list[CalibrationContext] = []
    for block_id, replacements in outliers_by_block.items():
        idx = block_index.get(block_id)
        if idx is None:
            continue
        block = ordered[idx]
        before = ordered[max(0, idx - context_window) : idx]
        after = ordered[idx + 1 : idx + 1 + context_window]
        ctx = _serial_consistency_context(block, before, after, replacements)
        if ctx:
            contexts.append(ctx)
    return contexts


def _collect_product_serial_matches(
    ordered: list[ParsedDocumentBlock],
) -> list[_SerialMatch]:
    matches: list[_SerialMatch] = []
    for block in ordered:
        text = block.text or ""
        if not text:
            continue
        for match in _PRODUCT_SERIAL_RE.finditer(text):
            prefix_lead = match.group("prefix").upper()
            matches.append(
                _SerialMatch(
                    block=block,
                    raw_match=match.group(0),
                    full_prefix=f"{prefix_lead}H",
                    series=match.group("series"),
                    suffix=match.group("suffix"),
                )
            )
    return matches


def _series_has_conflicting_prefixes(
    prefix_counts: dict[str, int],
    majority_prefix: str,
    min_majority: int,
) -> bool:
    for prefix, count in prefix_counts.items():
        if prefix == majority_prefix:
            continue
        if count < min_majority:
            continue
        if not _is_ocr_confusable_prefix(prefix, majority_prefix):
            return True
    return False


def _serial_prefix_lead(full_prefix: str) -> str:
    if full_prefix.upper().endswith("H") and len(full_prefix) >= 2:
        return full_prefix[:-1].upper()
    return full_prefix.upper()


def _is_ocr_confusable_prefix(outlier_prefix: str, majority_prefix: str) -> bool:
    outlier = outlier_prefix.upper()
    majority = majority_prefix.upper()
    if outlier == majority:
        return False

    outlier_lead = _serial_prefix_lead(outlier)
    majority_lead = _serial_prefix_lead(majority)
    if outlier_lead == majority_lead:
        return False

    if len(outlier_lead) == len(majority_lead) == 1:
        return frozenset({outlier_lead, majority_lead}) in _OCR_PREFIX_CHAR_PAIRS

    if len(outlier_lead) == len(majority_lead) and outlier_lead[1:] == majority_lead[1:]:
        return frozenset({outlier_lead[0], majority_lead[0]}) in _OCR_PREFIX_CHAR_PAIRS

    return False


def _serial_consistency_context(
    block: ParsedDocumentBlock,
    before: list[ParsedDocumentBlock],
    after: list[ParsedDocumentBlock],
    replacements: list[tuple[_SerialMatch, str, int]],
) -> CalibrationContext | None:
    if not replacements:
        return None

    block_text = block.text or ""
    suggested = block_text
    evidence: list[str] = []
    seen_raw: set[str] = set()

    first_match, first_corrected, majority_count = replacements[0]
    majority_prefix = first_corrected.rsplit("-", 2)[0]
    series = first_match.series
    outlier_prefixes: list[str] = []

    for match, corrected, _count in sorted(
        replacements, key=lambda item: len(item[0].raw_match), reverse=True
    ):
        raw = match.raw_match
        if raw in seen_raw:
            continue
        seen_raw.add(raw)
        if raw not in suggested:
            raw_token = _find_raw_token(suggested, raw)
            if not raw_token:
                continue
            raw = raw_token
        suggested = suggested.replace(raw, corrected, 1)
        outlier_prefixes.append(match.full_prefix)
        evidence.extend([majority_prefix, match.raw_match, corrected])

    if suggested == block_text:
        return None

    outlier_label = "、".join(dict.fromkeys(outlier_prefixes))
    reason = (
        f"同文档 -{series}- 系列产品序号前缀以 {majority_prefix} 为主（{majority_count} 处），"
        f"此处 {outlier_label} 疑似 OCR 字符混淆（如 L/4），建议复核为 {majority_prefix}。"
    )
    return CalibrationContext(
        block=block,
        before_blocks=before,
        after_blocks=after,
        issue_type="symbol_confusion",
        reason=reason,
        evidence=evidence,
        heuristic_record=ParseCalibrationRecord(
            block_id=block.block_id,
            page_hint=block.page_hint,
            issue_type="symbol_confusion",
            severity="warning",
            original_text=block.text,
            suggested_text=suggested,
            reason=reason,
            evidence=evidence,
            confidence=0.92,
            status="needs_review",
        ),
    )


def _should_calibrate_block(
    block: ParsedDocumentBlock,
    ordered: list[ParsedDocumentBlock],
    idx: int,
    *,
    context_window: int,
) -> bool:
    if _has_calibration_signal(block):
        return True
    return _has_contextual_diameter_confusion(block, ordered, idx, context_window=context_window)


def _has_calibration_signal(block: ParsedDocumentBlock) -> bool:
    text = _normalize_calibration_text(block.text or "")
    if not text:
        return False
    return (
        "°C" in text
        or "℃" in text
        or "±" in text
        or "Φ" in text
        or "φ" in text
        or any(keyword in text for keyword in _TEMP_RESULT_KEYWORDS + _DIAMETER_KEYWORDS)
    )


def _has_contextual_diameter_confusion(
    block: ParsedDocumentBlock,
    ordered: list[ParsedDocumentBlock],
    idx: int,
    *,
    context_window: int,
) -> bool:
    block_norm = _normalize_calibration_text(block.text or "")
    if not block_norm:
        return False
    if not (
        _DIAMETER_COMPACT_CONFUSION_RE.search(block_norm)
        or _DIAMETER_CONFUSION_SHORT_RE.search(block_norm)
        or _DIAMETER_LLM_REVIEW_CONFUSION_RE.search(block_norm)
    ):
        return False
    neighbors = ordered[max(0, idx - context_window) : idx + 1 + context_window]
    context_norm = " ".join(_normalize_calibration_text(b.text or "") for b in neighbors)
    if "Φ" in context_norm or "φ" in context_norm:
        return True
    return any(keyword in context_norm for keyword in _DIAMETER_KEYWORDS)


def _contexts_for_block(
    block: ParsedDocumentBlock,
    before: list[ParsedDocumentBlock],
    after: list[ParsedDocumentBlock],
) -> list[CalibrationContext]:
    contexts: list[CalibrationContext] = []
    temp = _temperature_outlier_context(block, before, after)
    if temp:
        contexts.append(temp)
    diameter = _diameter_symbol_context(block, before, after)
    if diameter:
        contexts.append(diameter)
    return contexts


def _temperature_outlier_context(
    block: ParsedDocumentBlock,
    before: list[ParsedDocumentBlock],
    after: list[ParsedDocumentBlock],
) -> CalibrationContext | None:
    table_rows = _table_rows(block.text or "")
    if table_rows:
        return _temperature_table_context(block, before, after, table_rows)

    context_text = "\n".join(
        _normalize_calibration_text(b.text or "") for b in [*before, block, *after] if b.text
    )
    ranges = []
    for match in _TEMP_RANGE_RE.finditer(context_text):
        base = float(match.group("base"))
        tol = abs(float(match.group("tol")))
        ranges.append((base - tol, base + tol, match.group(0)))
    if not ranges:
        return None

    block_text = block.text or ""
    range_spans = [match.span() for match in _TEMP_RANGE_RE.finditer(block_text)]
    for value_match in _TEMP_VALUE_RE.finditer(block_text):
        if any(start <= value_match.start() < end for start, end in range_spans):
            continue
        value = float(value_match.group("value"))
        for low, high, range_text in ranges:
            if low <= value <= high:
                continue
            nearest_gap = min(abs(value - low), abs(value - high))
            if nearest_gap < max(5.0, (high - low) * 0.5):
                continue
            value_text = value_match.group(0)
            reason = f"温度值 {value_text} 超出上下文要求 {range_text} 对应范围 {low:g}°C-{high:g}°C。"
            suggested = block.text.replace(value_text, f"[需复核：{value_text}]", 1)
            return CalibrationContext(
                block=block,
                before_blocks=before,
                after_blocks=after,
                issue_type="numeric_outlier",
                reason=reason,
                evidence=[range_text, value_text],
                heuristic_record=ParseCalibrationRecord(
                    block_id=block.block_id,
                    page_hint=block.page_hint,
                    issue_type="numeric_outlier",
                    severity="critical",
                    original_text=block.text,
                    suggested_text=(
                        f"{suggested}\n\n"
                        f"校准提示：{value_text} 超出上下文要求范围 {low:g}°C-{high:g}°C，需人工复核。"
                    ),
                    reason=reason,
                    evidence=[range_text, value_text],
                    confidence=0.88,
                    status="needs_review",
                ),
            )
    return None


def _temperature_table_context(
    block: ParsedDocumentBlock,
    before: list[ParsedDocumentBlock],
    after: list[ParsedDocumentBlock],
    rows: list[str],
) -> CalibrationContext | None:
    for row_html in rows:
        cells = _table_cells(row_html)
        if len(cells) < 2:
            continue
        for range_idx, range_cell in enumerate(cells):
            row_ranges = _temperature_ranges(range_cell)
            if not row_ranges:
                continue
            for low, high, range_text in row_ranges:
                for value_text, value in _temperature_result_values_in_row(cells, range_idx):
                    if low <= value <= high:
                        continue
                    nearest_gap = min(abs(value - low), abs(value - high))
                    if nearest_gap < max(5.0, (high - low) * 0.5):
                        continue
                    reason = (
                        f"同一表格行内温度值 {value_text} 超出要求 {range_text} "
                        f"对应范围 {low:g}°C-{high:g}°C。"
                    )
                    suggested = block.text.replace(value_text, f"[需复核：{value_text}]", 1)
                    return CalibrationContext(
                        block=block,
                        before_blocks=before,
                        after_blocks=after,
                        issue_type="numeric_outlier",
                        reason=reason,
                        evidence=[range_text, value_text],
                        heuristic_record=ParseCalibrationRecord(
                            block_id=block.block_id,
                            page_hint=block.page_hint,
                            issue_type="numeric_outlier",
                            severity="critical",
                            original_text=block.text,
                            suggested_text=(
                                f"{suggested}\n\n"
                                f"校准提示：{value_text} 超出同一表格行要求范围 {low:g}°C-{high:g}°C，需人工复核。"
                            ),
                            reason=reason,
                            evidence=[range_text, value_text],
                            confidence=0.86,
                            status="needs_review",
                        ),
                    )
    return None


def _temperature_ranges(text: str) -> list[tuple[float, float, str]]:
    ranges: list[tuple[float, float, str]] = []
    for match in _TEMP_RANGE_RE.finditer(text):
        base = float(match.group("base"))
        tol = abs(float(match.group("tol")))
        ranges.append((base - tol, base + tol, match.group(0)))
    return ranges


def _temperature_result_values_in_row(
    cells: list[str],
    range_idx: int,
) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    for cell in cells[range_idx + 1 :]:
        for value_match in _TEMP_VALUE_RE.finditer(cell):
            if _TEMP_RANGE_RE.search(cell):
                continue
            values.append((value_match.group(0), float(value_match.group("value"))))
    return values


def _diameter_symbol_context(
    block: ParsedDocumentBlock,
    before: list[ParsedDocumentBlock],
    after: list[ParsedDocumentBlock],
) -> CalibrationContext | None:
    block_text = block.text or ""
    block_norm = _normalize_calibration_text(block_text)
    context_text = "\n".join(
        _normalize_calibration_text(b.text or "") for b in [*before, block, *after] if b.text
    )
    has_diameter_context = any(keyword in context_text for keyword in _DIAMETER_KEYWORDS) or bool(
        _DIAMETER_REF_RE.search(context_text)
    )
    if not has_diameter_context:
        return None

    refs = {match.group("num") for match in _DIAMETER_REF_RE.finditer(context_text)}
    if not refs:
        return None

    table_context = _diameter_table_context(block, before, after, refs)
    if table_context:
        return table_context

    replacements = _diameter_symbol_replacements(block_text, block_norm, refs)
    if replacements:
        suggested = block_text
        for confused, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
            suggested = suggested.replace(confused, replacement, 1)
        evidence = [part for pair in replacements for part in pair]
        reason = "同页/相邻上下文存在直径符号 Φ，当前块出现多个以 4 开头的相近尺寸值，疑似 Φ 被识别为 4。"
        return CalibrationContext(
            block=block,
            before_blocks=before,
            after_blocks=after,
            issue_type="symbol_confusion",
            reason=reason,
            evidence=evidence,
            heuristic_record=ParseCalibrationRecord(
                block_id=block.block_id,
                page_hint=block.page_hint,
                issue_type="symbol_confusion",
                severity="warning",
                original_text=block.text,
                suggested_text=suggested,
                reason=reason,
                evidence=evidence,
                confidence=0.82,
                status="needs_review",
            ),
        )
    compact_match = _DIAMETER_COMPACT_CONFUSION_RE.search(block_norm)
    if compact_match:
        confused = compact_match.group(0).replace(" ", "")
        replacement_pair = _compact_diameter_replacement(confused, refs)
        if replacement_pair:
            confused_raw, replacement = replacement_pair
            suggested = block_text.replace(confused_raw, replacement, 1)
            if suggested == block_text and confused != confused_raw:
                suggested = block_text.replace(confused, replacement, 1)
            evidence = [confused_raw, replacement]
            reason = (
                "同页/相邻上下文存在直径符号 Φ，当前块出现以 4 开头的紧凑尺寸值，"
                f"疑似 {confused_raw} 表示 {replacement}（Φ 被识别为 4 且小数点丢失）。"
            )
            return CalibrationContext(
                block=block,
                before_blocks=before,
                after_blocks=after,
                issue_type="symbol_confusion",
                reason=reason,
                evidence=evidence,
                heuristic_record=ParseCalibrationRecord(
                    block_id=block.block_id,
                    page_hint=block.page_hint,
                    issue_type="symbol_confusion",
                    severity="warning",
                    original_text=block.text,
                    suggested_text=suggested,
                    reason=reason,
                    evidence=evidence,
                    confidence=0.84,
                    status="needs_review",
                ),
            )
    llm_review_match = _DIAMETER_LLM_REVIEW_CONFUSION_RE.search(block_norm)
    if llm_review_match:
        confused = llm_review_match.group(0).replace(" ", "")
        plus_pair = _plus_diameter_replacement(confused, refs)
        if plus_pair:
            confused_norm, replacement = plus_pair
            confused_raw = _find_raw_token(block_text, confused_norm) or confused_norm
            suggested = block_text.replace(confused_raw, replacement, 1)
            if suggested == block_text and confused_norm != confused:
                suggested = block_text.replace(confused, replacement, 1)
            evidence = [*sorted(refs), confused_raw, replacement]
            reason = (
                "同页/相邻上下文存在直径符号 Φ，当前块出现以 +/＋ 开头且与基准接近的尺寸值，"
                f"疑似 {confused_raw} 表示 {replacement}（Φ 被识别为 +/＋）。"
            )
            return CalibrationContext(
                block=block,
                before_blocks=before,
                after_blocks=after,
                issue_type="symbol_confusion",
                reason=reason,
                evidence=evidence,
                heuristic_record=ParseCalibrationRecord(
                    block_id=block.block_id,
                    page_hint=block.page_hint,
                    issue_type="symbol_confusion",
                    severity="warning",
                    original_text=block.text,
                    suggested_text=suggested,
                    reason=reason,
                    evidence=evidence,
                    confidence=0.84,
                    status="needs_review",
                ),
            )

        ref_hint = _closest_ref_label(refs)
        reason = f"同页/相邻上下文存在直径符号 {ref_hint}，当前块出现乱码占位 {confused}，疑似直径符号或数字 OCR 严重损坏。"
        suggested = (
            f"{block_text}\n\n"
            f"校准提示：{confused} 与上下文 {ref_hint} 直径要求冲突，"
            "疑似直径符号/数字 OCR 损坏，需人工复核。"
        )
        evidence = [ref_hint, confused]
        return CalibrationContext(
            block=block,
            before_blocks=before,
            after_blocks=after,
            issue_type="symbol_confusion",
            reason=reason,
            evidence=evidence,
            heuristic_record=ParseCalibrationRecord(
                block_id=block.block_id,
                page_hint=block.page_hint,
                issue_type="symbol_confusion",
                severity="warning",
                original_text=block.text,
                suggested_text=suggested,
                reason=reason,
                evidence=evidence,
                confidence=0.72,
                status="needs_review",
            ),
        )
    return None


def _diameter_table_context(
    block: ParsedDocumentBlock,
    before: list[ParsedDocumentBlock],
    after: list[ParsedDocumentBlock],
    context_refs: set[str],
) -> CalibrationContext | None:
    block_text = block.text or ""
    rows = _table_rows(block_text)
    if not rows:
        return None

    replacements: list[tuple[str, str]] = []
    review_terms: list[tuple[str, str]] = []
    seen_replacements: set[tuple[str, str]] = set()
    seen_reviews: set[tuple[str, str]] = set()
    for row_text in rows:
        row_norm = _normalize_calibration_text(row_text)
        row_refs = {match.group("num") for match in _DIAMETER_REF_RE.finditer(row_norm)}
        if not row_refs:
            continue
        if not _row_has_diameter_context(row_norm):
            continue

        for confused, replacement in _diameter_symbol_replacements(row_text, row_norm, row_refs):
            key = (confused, replacement)
            if key not in seen_replacements:
                seen_replacements.add(key)
                replacements.append(key)

        for match in _DIAMETER_COMPACT_CONFUSION_RE.finditer(row_norm):
            confused = match.group(0).replace(" ", "")
            replacement_pair = _compact_diameter_replacement(confused, row_refs)
            if not replacement_pair:
                continue
            confused_norm, replacement = replacement_pair
            confused_raw = _find_raw_token(row_text, confused_norm) or confused_norm
            key = (confused_raw, replacement)
            if key not in seen_replacements:
                seen_replacements.add(key)
                replacements.append(key)

        for match in _DIAMETER_LLM_REVIEW_CONFUSION_RE.finditer(row_norm):
            confused = match.group(0).replace(" ", "")
            plus_pair = _plus_diameter_replacement(confused, row_refs)
            if plus_pair:
                confused_norm, replacement = plus_pair
                confused_raw = _find_raw_token(row_text, confused_norm) or confused_norm
                key = (confused_raw, replacement)
                if key not in seen_replacements:
                    seen_replacements.add(key)
                    replacements.append(key)
                continue

            confused_raw = _find_raw_token(row_text, confused) or confused
            ref_hint = _closest_ref_label(row_refs)
            key = (ref_hint, confused_raw)
            if key not in seen_reviews:
                seen_reviews.add(key)
                review_terms.append(key)

    if not replacements and not review_terms:
        return None

    suggested = block_text
    for confused, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        suggested = suggested.replace(confused, replacement, 1)
    if review_terms:
        hints = "；".join(
            f"{confused} 与上下文 {ref_hint} 直径要求冲突，疑似直径符号/数字 OCR 损坏"
            for ref_hint, confused in review_terms
        )
        suggested = f"{suggested}\n\n校准提示：{hints}，需人工复核。"

    evidence = [part for pair in replacements for part in pair]
    for ref_hint, confused in review_terms:
        evidence.extend([ref_hint, confused])
    reason_parts = []
    if replacements:
        reason_parts.append("表格行内要求值存在直径符号 Φ，同行实测值出现 4/+ 等符号混淆。")
    if review_terms:
        reason_parts.append("表格行内要求值存在直径符号 Φ，同行实测值出现 ### 等乱码占位。")
    reason = " ".join(reason_parts)
    return CalibrationContext(
        block=block,
        before_blocks=before,
        after_blocks=after,
        issue_type="symbol_confusion",
        reason=reason,
        evidence=evidence,
        heuristic_record=ParseCalibrationRecord(
            block_id=block.block_id,
            page_hint=block.page_hint,
            issue_type="symbol_confusion",
            severity="warning",
            original_text=block.text,
            suggested_text=suggested,
            reason=reason,
            evidence=evidence,
            confidence=0.86 if replacements else 0.74,
            status="needs_review",
        ),
    )


def _table_rows(text: str) -> list[str]:
    if "<tr" not in text.lower():
        return []
    return [match.group("body") for match in _TABLE_ROW_RE.finditer(text)]


def _table_cells(row_html: str) -> list[str]:
    cells = []
    for match in _TABLE_CELL_RE.finditer(row_html):
        text = _normalize_calibration_text(html.unescape(match.group("body")))
        if text:
            cells.append(text)
    return cells


def _row_has_diameter_context(row_text: str) -> bool:
    return bool(_DIAMETER_REF_RE.search(row_text)) and any(
        keyword in row_text for keyword in _DIAMETER_KEYWORDS
    )


def _compact_diameter_replacement(confused: str, refs: set[str]) -> tuple[str, str] | None:
    normalized = re.sub(r"\s+", "", confused)
    if not normalized.startswith("4"):
        return None
    rest = normalized[1:]
    if not rest.isdigit():
        return None

    ref_candidates: list[tuple[str, str]] = []
    for ref in refs:
        ref_norm = ref.replace(" ", "")
        int_part = ref_norm.split(".")[0]
        if int_part:
            ref_candidates.append((int_part, ref_norm))
    ref_candidates.sort(key=lambda item: len(item[0]), reverse=True)

    for int_part, ref_norm in ref_candidates:
        if not rest.startswith(int_part):
            continue
        suffix = rest[len(int_part) :]
        if not suffix:
            return (normalized, f"Φ{ref_norm}")
        if suffix.isdigit():
            return (normalized, f"Φ{int_part}.{suffix}")
    return None


def _plus_diameter_replacement(confused: str, refs: set[str]) -> tuple[str, str] | None:
    normalized = re.sub(r"\s+", "", confused)
    if not normalized.startswith(("+", "＋")):
        return None
    raw_num = normalized[1:]
    try:
        value = float(raw_num)
    except ValueError:
        return None

    ref_values = _diameter_ref_values(refs)
    if not ref_values:
        return None
    _ref, ref_value = min(ref_values, key=lambda item: abs(item[1] - value))
    tolerance = max(0.2, abs(ref_value) * 0.002)
    if abs(ref_value - value) > tolerance:
        return None
    return (normalized, f"Φ{raw_num}")


def _closest_ref_label(refs: set[str]) -> str:
    if not refs:
        return "Φ"
    return f"Φ{sorted(refs, key=len, reverse=True)[0]}"


def _diameter_ref_values(refs: set[str]) -> list[tuple[str, float]]:
    ref_values: list[tuple[str, float]] = []
    for ref in refs:
        try:
            ref_values.append((ref, float(ref)))
        except ValueError:
            continue
    return ref_values


def _diameter_symbol_replacements(
    block_text: str,
    block_norm: str,
    refs: set[str],
) -> list[tuple[str, str]]:
    ref_values = _diameter_ref_values(refs)
    if not ref_values:
        return []

    replacements: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _DIAMETER_CONFUSION_SHORT_RE.finditer(block_norm):
        confused_norm = re.sub(r"\s+", "", match.group(0))
        if confused_norm in seen:
            continue
        raw_num = match.group("num")
        try:
            value = float(raw_num)
        except ValueError:
            continue
        ref, ref_value = min(ref_values, key=lambda item: abs(item[1] - value))
        tolerance = max(0.15, abs(ref_value) * 0.002)
        if abs(ref_value - value) > tolerance:
            continue
        normalized_num = raw_num.replace(" ", "")
        replacement = f"Φ{normalized_num}"
        confused_raw = _find_raw_token(block_text, confused_norm) or match.group(0)
        replacements.append((confused_raw, replacement))
        seen.add(confused_norm)
    return replacements


def _find_raw_token(block_text: str, normalized_token: str) -> str | None:
    if normalized_token in block_text:
        return normalized_token
    pattern = re.compile(
        r"(?<![\d.])"
        + r"\s*".join(re.escape(char) for char in normalized_token)
        + r"(?![\d.])",
    )
    match = pattern.search(block_text)
    return match.group(0) if match else None
