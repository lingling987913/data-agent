"""Shared traceability text heuristics for P0 and legacy services."""

from __future__ import annotations

import re

_CONDITION_TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "steady_state": ("稳态", "稳定状态", "steady", "steady-state"),
    "nominal": ("标称", "额定", "nominal", "baseline case"),
    "maneuver": ("机动", "姿态机动", "maneuver", "slew"),
    "fault": ("故障", "失效", "降级", "单机故障", "fault", "failure", "degraded"),
    "safe_mode": ("安全模式", "安全姿态", "safe mode", "safe attitude"),
    "boundary": (
        "边界", "极限", "最大", "最小", "最不利", "包线", "全包线",
        "boundary", "corner case", "worst case", "envelope",
    ),
    "max_load": ("最大负载", "最大惯量", "最大扰动", "最大力矩", "满载", "max load", "maximum load"),
    "monte_carlo": ("蒙特卡洛", "统计", "随机", "monte carlo", "3σ", "3sigma", "three sigma"),
}


def condition_tags(text: str) -> list[str]:
    sample = (text or "").lower()
    tags: list[str] = []
    for tag, aliases in _CONDITION_TAG_ALIASES.items():
        if any(alias.lower() in sample for alias in aliases):
            tags.append(tag)
    return tags


def normalize_comparator(value: str) -> str:
    mapping = {
        "≤": "<=",
        "不大于": "<=",
        "不超过": "<=",
        "小于": "<",
        "≥": ">=",
        "不小于": ">=",
        "不少于": ">=",
        "大于": ">",
    }
    return mapping.get(value, value)


def infer_verification_method(text: str, role: str = "") -> str:
    sample = (text or "").lower()
    if "仿真" in text or "simulation" in sample:
        return "simulation"
    if "试验" in text or "测试" in text or "test" in sample:
        return "test"
    if "分析" in text or "analysis" in sample:
        return "analysis"
    if role in {"simulation_report", "verification_result"}:
        return "simulation" if "simulation" in role else "test"
    return "review"


def infer_pass_fail(text: str) -> str:
    sample = (text or "").lower()
    if any(token in sample for token in ("不满足", "未通过", "fail", "failed", "不通过")):
        return "fail"
    if any(token in sample for token in ("满足", "通过", "pass", "passed", "合格")):
        return "pass"
    return "unknown"


def looks_like_requirement(text: str) -> bool:
    return bool(re.search(r"应|须|需|要求|shall|must|REQ-", text or "", re.IGNORECASE))


def looks_like_verification(text: str) -> bool:
    return bool(re.search(r"验证|试验|测试|仿真|SIM-|VER-|TEST-", text or "", re.IGNORECASE))
