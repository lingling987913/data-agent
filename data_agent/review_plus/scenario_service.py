"""Review-Plus scenario detection."""

from __future__ import annotations

from typing import Any


def detect_review_plus_scenario(materials: list[Any]) -> dict[str, Any]:
    names = " ".join(getattr(m, "name", "") for m in materials)
    sample = "\n".join((getattr(m, "content", "") or "")[:1500] for m in materials)
    text = f"{names}\n{sample}"
    hits = [
        token
        for token in ("产品保证", "可靠性", "安全性", "FMEA", "FTA", "SCA", "任务书", "检查单")
        if token in text
    ]
    if len(hits) >= 3:
        return {
            "scenario": "product_assurance_reliability_safety",
            "confidence": min(0.95, 0.55 + len(hits) * 0.06),
            "reason": f"命中产品保证/可靠性安全性审查关键词: {', '.join(hits[:8])}",
        }
    return {
        "scenario": "generic_document_package_review",
        "confidence": 0.45,
        "reason": "未命中特定业务场景，按通用多文档包审查处理",
    }
