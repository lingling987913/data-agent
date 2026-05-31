"""Serialize unified workbench detail for user-facing report export."""

from __future__ import annotations

from typing import Any

from data_agent.review_workbench.issue_taxonomy import count_problem_buckets
from data_agent.review_workbench.schemas import UnifiedReviewWorkbenchDetail

WORKBENCH_PHASE_LABELS: dict[str, str] = {
    "pre_review": "送审准备",
    "startup": "启动中",
    "executing": "执行中",
    "arbitration": "待仲裁",
    "completed": "已完成",
    "failed": "失败",
}

RUN_STATUS_LABELS: dict[str, str] = {
    "completed": "已完成",
    "limited": "已完成（受限）",
    "running": "执行中",
    "pending": "待开始",
    "failed": "失败",
    "draft": "草稿",
    "cancelled": "已取消",
}


def _phase_label(phase: str) -> str:
    key = str(phase or "").strip().lower()
    return WORKBENCH_PHASE_LABELS.get(key, phase or "—")


def _run_status_label(status: str) -> str:
    key = str(status or "").strip().lower()
    return RUN_STATUS_LABELS.get(key, status or "已完成")


def _quality_status_label(*, workbench_phase: str, error: str) -> str:
    if str(workbench_phase or "").lower() == "failed":
        return "异常"
    if str(error or "").strip():
        return "需关注"
    return "正常"


def detail_to_report_snapshot(detail: UnifiedReviewWorkbenchDetail) -> dict[str, Any]:
    """Flatten workbench detail into JSON-safe fields aligned with overview UI."""
    overview = detail.conclusion_overview
    scope = dict(overview.review_scope) if overview else {}
    buckets = dict(overview.issue_buckets) if overview else {}
    pending_confirm = int(detail.metrics.pending_confirm or 0)
    if not pending_confirm:
        pending_confirm = int(detail.metrics.open_rid_count or 0) + int(buckets.get("manual_review") or 0)
    issue_count = int(detail.metrics.problem_count or detail.metrics.finding_count or 0)
    if not issue_count and buckets:
        issue_count = count_problem_buckets(buckets)

    material_count = int(detail.metrics.material_count or 0)
    if not material_count:
        names = scope.get("material_names") or []
        if isinstance(names, list):
            material_count = len(names)

    return {
        "task_name": detail.name or "",
        "run_status": _run_status_label(detail.status),
        "workbench_phase": _phase_label(
            detail.workbench_phase.value
            if hasattr(detail.workbench_phase, "value")
            else str(detail.workbench_phase or "")
        ),
        "current_step": detail.current_step or "",
        "material_count": material_count,
        "review_route_label": str(
            scope.get("review_mode_label") or detail.summary.review_mode_label or ""
        ).strip(),
        "issue_count": issue_count,
        "pending_confirm": pending_confirm,
        "quality_status": _quality_status_label(
            workbench_phase=str(
                detail.workbench_phase.value
                if hasattr(detail.workbench_phase, "value")
                else detail.workbench_phase or ""
            ),
            error=detail.error,
        ),
        "verdict_label_zh": str(
            overview.verdict_label_zh if overview else detail.summary.verdict_label_zh or ""
        ).strip(),
        "rationale_zh": str(
            overview.rationale_zh if overview else detail.summary.rationale_zh or ""
        ).strip(),
        "one_line_conclusion": str(
            overview.one_line_conclusion if overview else detail.summary.one_line_conclusion or ""
        ).strip(),
        "headline_verdict": str(
            overview.headline_zh or overview.headline_verdict if overview else detail.summary.headline_verdict or ""
        ).strip(),
        "review_subject_lines": list(scope.get("material_summary_lines") or scope.get("material_names") or []),
        "review_plan_lines": list(scope.get("review_plan_lines") or scope.get("actual_scope") or []),
    }
