"""Review objective helpers: default vs custom, GNC intent detection."""

from __future__ import annotations

from typing import Any

from data_agent.core.domain_registry import route_signals_for_domain

DEFAULT_OBJECTIVES = frozenset(
    {
        "",
        "对上传材料执行智能审查",
        "等待上传材料后执行智能审查。",
        "等待上传材料后执行智能审查",
    }
)

_GNC_INTENT_TOKENS = ("gnc", "姿态", "轨控", "卫星", "飞轮", "星敏", "陀螺", "导航", "控制")
_GENERIC_REVIEW_TOKENS = (
    "不正确",
    "有没有错",
    "错误",
    "问题",
    "有用",
    "指标信息",
    "产品指标",
    "提取",
    "整理",
    "总结",
    "摘要",
    "通用",
)


def normalize_objective(text: str | None) -> str:
    return str(text or "").strip()


def _objective_text(source: Any) -> str:
    if isinstance(source, str):
        return normalize_objective(source)
    return normalize_objective(getattr(source, "objective", ""))


def has_custom_objective(source: Any) -> bool:
    text = _objective_text(source)
    return bool(text) and text not in DEFAULT_OBJECTIVES


def objective_implies_gnc(objective: str | None, *, domain_id: str | None = None) -> bool:
    text = normalize_objective(objective).lower()
    if not text:
        return False
    if any(token in text for token in _GNC_INTENT_TOKENS):
        return True
    if domain_id:
        signals = route_signals_for_domain(domain_id)
        tokens = tuple(signals.get("gnc_strong") or ()) + tuple(signals.get("gnc_weak") or ())
        if any(token in text for token in tokens):
            return True
    return False


def objective_suppresses_gnc(objective: str | None, *, domain_id: str | None = None) -> bool:
    """Return whether a custom objective should stay in generic/smart review despite GNC terms in text."""
    text = normalize_objective(objective).lower()
    if not text:
        return False
    if objective_implies_gnc(text, domain_id=domain_id):
        return False
    return any(token in text for token in _GENERIC_REVIEW_TOKENS) or has_custom_objective(text)
