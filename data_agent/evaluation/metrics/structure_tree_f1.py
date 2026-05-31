from __future__ import annotations

from data_agent.evaluation.metrics.structure_coverage import structure_tree_coverage_ratio


def _section_titles(sections: list[dict]) -> set[str]:
    titles: set[str] = set()
    for section in sections:
        title = str(section.get("title") or "").strip().lower()
        if title:
            titles.add(title)
    return titles


def structure_tree_f1_score(
    *,
    predicted_sections: list[dict],
    expected_sections: list[dict] | None = None,
    section_count: int = 0,
    document_count: int = 0,
) -> dict[str, float | None]:
    """Section-title F1 when expected tree exists; otherwise expose coverage proxy only."""
    coverage_proxy = structure_tree_coverage_ratio(
        section_count=section_count or len(predicted_sections),
        document_count=document_count,
    )
    if not expected_sections:
        return {
            "f1": None,
            "precision": None,
            "recall": None,
            "coverage_proxy": coverage_proxy,
        }

    predicted = _section_titles(predicted_sections)
    expected = _section_titles(expected_sections)
    if not expected:
        return {
            "f1": None,
            "precision": None,
            "recall": None,
            "coverage_proxy": coverage_proxy,
        }

    true_positive = len(predicted & expected)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(expected)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "f1": round(f1, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "coverage_proxy": coverage_proxy,
    }


def structure_tree_f1_scalar(metrics: dict[str, float | None]) -> float:
    """Single score for aggregation/gates: F1 when reference exists, else coverage proxy."""
    f1 = metrics.get("f1")
    if f1 is not None:
        return float(f1)
    return float(metrics.get("coverage_proxy") or 0.0)
