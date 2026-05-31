from __future__ import annotations


def _bounded_ratio(numerator: int, denominator: int, *, default: float = 1.0) -> float:
    if denominator <= 0:
        return default
    return max(0.0, min(1.0, numerator / denominator))


_STATUS_WEIGHT = {
    "ok": 1.0,
    "degraded": 0.35,
    "failed": 0.0,
}


def ocr_coverage_ratio(
    *,
    parse_status: str = "ok",
    text_block_count: int,
    visual_element_count: int,
    document_count: int,
) -> float:
    """OCR coverage from parse status and extracted text/visual blocks (no fabricated reference)."""
    if document_count <= 0:
        return 1.0
    status_score = _STATUS_WEIGHT.get(str(parse_status or "ok").lower(), 0.5)
    text_score = _bounded_ratio(text_block_count, document_count)
    visual_score = _bounded_ratio(visual_element_count, document_count)
    combined = (status_score * 0.5) + (text_score * 0.25) + (visual_score * 0.25)
    return max(0.0, min(1.0, combined))
