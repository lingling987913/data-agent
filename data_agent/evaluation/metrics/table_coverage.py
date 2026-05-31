from __future__ import annotations

import re


def _bounded_ratio(numerator: int, denominator: int, *, default: float = 1.0) -> float:
    if denominator <= 0:
        return default
    return max(0.0, min(1.0, numerator / denominator))


_GFM_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}")


def count_table_rows_from_markdown(markdown: str) -> int:
    """Count data rows in a GFM markdown table (excludes header and separator)."""
    lines = [line.strip() for line in (markdown or "").splitlines() if line.strip()]
    if not lines:
        return 0
    data_rows = 0
    for index, line in enumerate(lines):
        if index == 0:
            continue
        if _GFM_SEPARATOR_RE.match(line):
            continue
        data_rows += 1
    return data_rows if data_rows else len(lines)


def count_table_rows_from_elements(table_elements: list) -> int:
    total = 0
    for element in table_elements or []:
        if isinstance(element, dict):
            markdown = str(element.get("markdown") or element.get("text") or "")
        else:
            markdown = str(getattr(element, "markdown", None) or getattr(element, "text", None) or "")
        total += count_table_rows_from_markdown(markdown)
    return total


def table_coverage_ratio(
    *,
    table_element_count: int,
    table_row_count: int = 0,
    min_table_rows: int | None = None,
    document_count: int,
) -> float:
    """Table coverage against golden reference thresholds or document presence."""
    if min_table_rows is not None and min_table_rows > 0:
        observed = table_row_count if table_row_count > 0 else table_element_count
        return _bounded_ratio(observed, min_table_rows)
    return _bounded_ratio(table_element_count, document_count)
