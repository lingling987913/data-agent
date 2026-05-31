"""Shared text and material helpers for Review-Plus services."""

from __future__ import annotations

import re
from typing import Any

from data_agent.review_plus.schemas import ReviewPlusMaterialRole

STOP_WORDS = frozenset({
    "是否", "进行", "进行了", "符合", "要求", "检查", "内容", "文件", "文档",
    "情况", "不存在", "可以", "通过", "分析", "设计", "报告", "任务书",
})


def role_value(material: Any) -> str:
    role = getattr(material, "role", "")
    return role.value if hasattr(role, "value") else str(role or "")


def dict_items(value: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw_items = value.get(key) or []
    else:
        raw_items = getattr(value, key, []) or []
    return [item for item in raw_items if isinstance(item, dict)]


def tokens(text: str) -> set[str]:
    result: set[str] = set()
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_\-]+", text or ""):
        result.add(word.lower())
    for seg in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        if seg in STOP_WORDS:
            continue
        if 2 <= len(seg) <= 10:
            result.add(seg)
        for size in (2, 3, 4):
            if len(seg) >= size:
                for index in range(len(seg) - size + 1):
                    token = seg[index:index + size]
                    if token not in STOP_WORDS:
                        result.add(token)
    return result


def lexical_score(left: str, right: str) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    return len(overlap) / max(len(left_tokens), 1)


def material_snapshot(material: Any, *, max_chars: int = 6000) -> str:
    return " ".join([
        str(getattr(material, "name", "") or ""),
        str(getattr(material, "role_reason", "") or ""),
        str(getattr(material, "content", "") or "")[:max_chars],
    ])


def all_review_text(task: Any, *, max_chars_per_material: int = 5000) -> str:
    parts: list[str] = []
    for material in getattr(task, "materials", []) or []:
        if getattr(material, "included_in_formal_review", True) is False:
            continue
        parts.append(material_snapshot(material, max_chars=max_chars_per_material))
    return "\n".join(parts)


def iter_material_lines(
    task: Any,
    *,
    exclude_roles: set[str] | None = None,
    min_line_length: int = 6,
) -> list[dict[str, Any]]:
    """Yield raw-line evidence dicts from review materials."""
    excluded = exclude_roles or {
        ReviewPlusMaterialRole.REVIEW_RULE.value,
        ReviewPlusMaterialRole.CHECKLIST.value,
    }
    evidence: list[dict[str, Any]] = []
    for material in getattr(task, "materials", []) or []:
        if role_value(material) in excluded:
            continue
        if getattr(material, "included_in_formal_review", True) is False:
            continue
        material_name = getattr(material, "name", "")
        for line_no, raw in enumerate((getattr(material, "content", "") or "").splitlines(), start=1):
            text = raw.strip().strip("|*- \t")
            if len(text) < min_line_length:
                continue
            evidence.append({
                "evidence_id": f"ev:{material_name}:line-{line_no}",
                "material_name": material_name,
                "role": role_value(material),
                "section_id": f"{material_name}:line-{line_no}",
                "section_title": material_name,
                "line_no": line_no,
                "text": text,
                "tokens": tokens(text),
                "source_kind": "material_line",
            })
    return evidence
