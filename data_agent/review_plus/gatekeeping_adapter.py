"""Adapter to bridge Review-Plus task with the existing gatekeeping service."""

from __future__ import annotations

from data_agent.review.package_gatekeeping_service import evaluate_package_gatekeeping
from data_agent.review_plus.package_slots import evaluate_review_plus_package_slots
from data_agent.review_plus.p0_task_adapter import to_legacy_review_task
from data_agent.review_plus.schemas import ReviewPlusGatekeepingResult, ReviewPlusTask


_PASSED_STATUSES = {"pass", "pass_with_note"}
_LIMITED_STATUSES = {"limited_pass", "limited"}


def evaluate_review_plus_gatekeeping(task: ReviewPlusTask) -> ReviewPlusGatekeepingResult:
    """
    将 ReviewPlusTask 适配到旧 package_gatekeeping_service 进行门禁检查。

    Review-Plus 的材料角色是通用角色；旧门禁需要 P0 文档角色。适配器会将
    Review-Plus 材料转换为临时 ReviewTask，再复用旧门禁的必需角色、解析状态、
    版本基线检查逻辑，并将结果归一化为 Review-Plus 的 blocked/limited/passed。
    """
    legacy_task = to_legacy_review_task(task)
    legacy_result = evaluate_package_gatekeeping(legacy_task)

    warnings = list(legacy_result.warnings)
    warnings.extend(_confirmed_material_metadata_warnings(task))
    slot_blocking, slot_missing, slot_limited, _ = evaluate_review_plus_package_slots(task)
    blocking_reasons = list(legacy_result.blocking_reasons) + slot_blocking
    missing_materials = list(legacy_result.missing_materials) + slot_missing
    limited_scope = list(legacy_result.limited_scope) + slot_limited

    gate_status = _normalize_gate_status(legacy_result.gate_status, warnings)
    if slot_blocking:
        gate_status = "blocked"
    elif slot_limited and gate_status == "passed":
        gate_status = "limited"
    gate_summary = legacy_result.gate_summary
    if slot_blocking:
        gate_summary = f"送审包未齐套：{'；'.join(slot_blocking[:4])}"
    elif slot_limited and gate_status == "limited":
        gate_summary = f"送审包可受限启动：{'；'.join(slot_limited[:4])}"
    return ReviewPlusGatekeepingResult(
        review_id=task.review_plus_id,
        gate_status=gate_status,
        gate_summary=gate_summary,
        can_start_review=gate_status != "blocked",
        blocking_reasons=blocking_reasons,
        limited_scope=limited_scope,
        missing_materials=missing_materials,
        warnings=warnings,
    )


def _confirmed_material_metadata_warnings(task: ReviewPlusTask) -> list[str]:
    warnings: list[str] = []
    for material in task.materials:
        if not material.included_in_formal_review or not material.role_confirmed:
            continue
        if not (material.document_version or "").strip():
            warnings.append(f"已确认角色材料缺少文档版本: {material.name}")
        if not (material.baseline_id or "").strip():
            warnings.append(f"已确认角色材料缺少基线标识: {material.name}")
    return warnings


def _normalize_gate_status(status: str, warnings: list[str]) -> str:
    if status == "blocked":
        return "blocked"
    if status in _LIMITED_STATUSES:
        return "limited"
    if status in _PASSED_STATUSES:
        return "limited" if warnings else "passed"
    return "limited"
