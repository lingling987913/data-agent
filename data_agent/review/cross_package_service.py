from __future__ import annotations

import re
from typing import Any

from data_agent.review.schemas import CrossDocFinding, ParsedMaterial

_COMPARE_TOPICS = [
    "FMEA", "FTA", "关键项目", "可靠性", "安全性", "裕度", "飞轮",
    "任务剖面", "寿命试验", "环境适应性", "控制律",
]


def _topic_coverage(materials: list[ParsedMaterial]) -> dict[str, set[str]]:
    coverage: dict[str, set[str]] = {}
    for m in materials:
        text = (m.content or "").lower()
        hits = {t for t in _COMPARE_TOPICS if t.lower() in text}
        coverage[m.name] = hits
    return coverage


def _spacecraft_name(materials: list[ParsedMaterial]) -> str:
    for m in materials:
        for pattern in (r"月兔一号", r"蓬莱一号", r"YT-1", r"PL-1"):
            if re.search(pattern, m.content or ""):
                return pattern
        if "月兔" in m.name:
            return "月兔一号"
        if "蓬莱" in m.name:
            return "蓬莱一号"
    return "unknown"


def compare_document_packages(
    package_a: list[ParsedMaterial],
    package_b: list[ParsedMaterial],
    *,
    label_a: str = "q1",
    label_b: str = "q2",
) -> dict[str, Any]:
    """对比两套文档包（如月兔 vs 蓬莱）的主题覆盖与结构差异。"""
    cov_a = _topic_coverage(package_a)
    cov_b = _topic_coverage(package_b)
    all_a = set().union(*cov_a.values()) if cov_a else set()
    all_b = set().union(*cov_b.values()) if cov_b else set()

    only_a = sorted(all_a - all_b)
    only_b = sorted(all_b - all_a)
    shared = sorted(all_a & all_b)

    findings: list[CrossDocFinding] = []
    if only_a:
        findings.append(
            CrossDocFinding(
                finding_type="package_topic_diff",
                severity="minor",
                title=f"{label_a} 独有主题",
                description=f"{label_a} 覆盖但 {label_b} 未检出: {', '.join(only_a)}",
                doc_a=label_a,
                doc_b=label_b,
                source_quotes=only_a,
            )
        )
    if only_b:
        findings.append(
            CrossDocFinding(
                finding_type="package_topic_diff",
                severity="minor",
                title=f"{label_b} 独有主题",
                description=f"{label_b} 覆盖但 {label_a} 未检出: {', '.join(only_b)}",
                doc_a=label_b,
                doc_b=label_a,
                source_quotes=only_b,
            )
        )

    name_a = _spacecraft_name(package_a)
    name_b = _spacecraft_name(package_b)
    if name_a != "unknown" and name_b != "unknown" and name_a != name_b:
        findings.append(
            CrossDocFinding(
                finding_type="spacecraft_identity",
                severity="info",
                title="跨包型号识别",
                description=f"包 {label_a} 识别为 {name_a}，包 {label_b} 识别为 {name_b}。",
                doc_a=label_a,
                doc_b=label_b,
            )
        )

    return {
        "label_a": label_a,
        "label_b": label_b,
        "spacecraft_a": name_a,
        "spacecraft_b": name_b,
        "shared_topics": shared,
        "only_in_a": only_a,
        "only_in_b": only_b,
        "findings": [f.model_dump(mode="json") for f in findings],
        "material_count_a": len(package_a),
        "material_count_b": len(package_b),
    }
