from __future__ import annotations


def _bounded_ratio(numerator: int, denominator: int, *, default: float = 1.0) -> float:
    if denominator <= 0:
        return default
    return max(0.0, min(1.0, numerator / denominator))


def evidence_coverage_ratio(*, evidence_count: int, section_count: int) -> float:
    """Evidence pool coverage against section anchors."""
    return _bounded_ratio(evidence_count, section_count)


def structure_tree_coverage_ratio(*, section_count: int, document_count: int) -> float:
    """Section tree presence relative to parsed documents."""
    return _bounded_ratio(section_count, document_count)
