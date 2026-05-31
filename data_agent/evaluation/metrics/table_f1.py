from __future__ import annotations

import re

from data_agent.evaluation.metrics.table_coverage import count_table_rows_from_markdown

_GFM_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}")


def _split_pipe_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _row_signature(row: list[str] | str) -> str:
    if isinstance(row, str):
        cells = _split_pipe_row(row) if "|" in row else [row]
    else:
        cells = [str(cell) for cell in row]
    normalized = [re.sub(r"\s+", " ", cell.strip()) for cell in cells if cell.strip()]
    return "|".join(normalized).lower()


def parse_table_data_row_signatures(markdown: str) -> list[str]:
    """Return normalized data-row signatures from a GFM markdown table."""
    lines = [line.strip() for line in (markdown or "").splitlines() if line.strip()]
    if not lines:
        return []

    data_start = 1
    if len(lines) > 1 and _GFM_SEPARATOR_RE.match(lines[1]):
        data_start = 2

    signatures: list[str] = []
    for line in lines[data_start:]:
        if _GFM_SEPARATOR_RE.match(line):
            continue
        signature = _row_signature(_split_pipe_row(line))
        if signature:
            signatures.append(signature)
    if signatures:
        return signatures

    # Fallback: treat every non-separator line as a row when header-only tables appear.
    for line in lines:
        if _GFM_SEPARATOR_RE.match(line):
            continue
        signature = _row_signature(_split_pipe_row(line))
        if signature:
            signatures.append(signature)
    return signatures


def extract_table_row_signatures_from_result(result: dict) -> list[str]:
    signatures: list[str] = []
    document_ir = result.get("document_ir") or {}
    for element in document_ir.get("table_elements") or []:
        if isinstance(element, dict):
            markdown = str(element.get("markdown") or element.get("text") or "")
        else:
            markdown = str(getattr(element, "markdown", None) or getattr(element, "text", None) or "")
        signatures.extend(parse_table_data_row_signatures(markdown))

    if signatures:
        return signatures

    for chunk in result.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("chunk_text") or chunk.get("text") or "")
        if "|" in text and "\n|" in text:
            signatures.extend(parse_table_data_row_signatures(text))
    return signatures


def table_f1_score(
    *,
    predicted_rows: list[str],
    expected_rows: list[list[str] | str] | None = None,
    table_row_count: int = 0,
    min_table_rows: int | None = None,
) -> dict[str, float | None]:
    """Row-level F1 when golden reference rows exist; otherwise expose coverage proxy."""
    predicted = {_row_signature(row) for row in predicted_rows if _row_signature(row)}
    coverage_denominator = min_table_rows if min_table_rows else max(len(predicted), 1)
    observed_rows = len(predicted) if predicted else table_row_count
    coverage_proxy = min(1.0, observed_rows / coverage_denominator) if coverage_denominator else 1.0

    if not expected_rows:
        return {
            "f1": None,
            "precision": None,
            "recall": None,
            "coverage_proxy": round(coverage_proxy, 4),
        }

    expected = {_row_signature(row) for row in expected_rows if _row_signature(row)}
    if not expected:
        return {
            "f1": None,
            "precision": None,
            "recall": None,
            "coverage_proxy": round(coverage_proxy, 4),
        }

    true_positive = len(predicted & expected)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(expected)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "f1": round(f1, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "coverage_proxy": round(coverage_proxy, 4),
    }


def table_f1_scalar(metrics: dict[str, float | None]) -> float:
    f1 = metrics.get("f1")
    if f1 is not None:
        return float(f1)
    return float(metrics.get("coverage_proxy") or 0.0)
