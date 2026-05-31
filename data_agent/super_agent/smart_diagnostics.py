"""SMART committee diagnostics: format helpers + business-facing notes."""

from __future__ import annotations

from typing import Any

from data_agent.super_agent.diagnostics_sanitizer import (
    is_internal_diagnostic_text,
    sanitize_business_lines,
    sanitize_business_report_text,
    sanitize_report_markdown,
    sanitize_smart_diagnostic_text,
)

# Backward-compatible aliases
is_smart_internal_diagnostic = is_internal_diagnostic_text
filter_business_degradation = sanitize_business_lines


def format_committee_limited_note() -> str:
    return "当前审查为受限模式（含确定性预审、降级执行或引用/证据覆盖不足）"


def format_committee_limited_warning() -> str:
    return "当前为受限审查：确定性预审或降级执行结果不应视为完整 LLM 审查"


def format_citation_coverage_warning(coverage: float, source: str | None = None) -> str:
    pct = int(round(float(coverage or 0.0) * 100))
    src = source or "unknown"
    return f"引用/证据覆盖率 {pct}%（{src}），部分结论可能缺少充分引用"


def format_execution_mode_summary_lines(summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(summary, dict) or not summary:
        return []
    harness = int(summary.get("harness_count") or 0)
    generic_llm = int(summary.get("generic_llm_harness_count") or 0)
    deterministic = int(summary.get("deterministic_count") or 0)
    failed = int(summary.get("failed_count") or 0)
    blocked = int(summary.get("blocked_count") or 0)

    lines: list[str] = []
    expert_total = harness + generic_llm + deterministic
    if expert_total:
        if generic_llm and not harness:
            lines.append(f"本次智能审查由 {generic_llm} 个通用 LLM 专家完成。")
        elif harness and not generic_llm:
            lines.append(f"本次智能审查由 {harness} 个 Harness 专家完成。")
        elif harness and generic_llm:
            lines.append(
                f"本次智能审查由 {harness} 个 Harness 专家与 {generic_llm} 个通用 LLM 专家完成。"
            )
        if deterministic:
            lines.append(f"另有 {deterministic} 项采用确定性预审。")

    if harness == 0 and generic_llm > 0:
        lines.append("未启用 Review-Plus Harness，已使用 Generic LLM Harness。")
    elif harness > 0 and generic_llm == 0:
        lines.append("已启用 Review-Plus Harness 专家审查。")

    if failed:
        lines.append(f"有 {failed} 个专家任务执行失败。")
    if blocked:
        lines.append(f"有 {blocked} 个专家任务被阻塞。")
    return lines


__all__ = [
    "filter_business_degradation",
    "format_citation_coverage_warning",
    "format_committee_limited_note",
    "format_committee_limited_warning",
    "format_execution_mode_summary_lines",
    "is_smart_internal_diagnostic",
    "sanitize_business_report_text",
    "sanitize_report_markdown",
    "sanitize_smart_diagnostic_text",
]
