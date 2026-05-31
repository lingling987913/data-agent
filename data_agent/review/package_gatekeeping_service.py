"""Controlled review package gatekeeping for P0 traceability review."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from data_agent.review.p0_schemas import GatekeepingResult, MaterialItem, ReviewTask
from data_agent.review.material_role_service import infer_material_role
from data_agent.review.p0_shared_constants import (
    P0_GATEKEEPING_ROLE_LABELS,
    material_summary as build_material_summary,
)


REQUIRED_ROLES = frozenset({
    "top_requirement",
    "decomposed_requirement",
    "design_solution",
    "interface_control",
    "simulation_report",
    "verification_plan",
    "verification_result",
})


def evaluate_package_gatekeeping(task: ReviewTask) -> GatekeepingResult:
    """Evaluate whether the controlled package can enter P0 closure review."""
    _suggest_missing_roles(task)
    materials = [
        material
        for material in (task.materials.materials if task.materials else [])
        if material.included_in_formal_review
    ]
    role_set = {material.document_role for material in materials if material.document_role}
    missing: list[str] = []
    blocking: list[str] = []
    limited: list[str] = []
    warnings: list[str] = []

    failed = [
        material.name
        for material in materials
        if (material.parse_status or "").lower() == "failed"
    ]
    unconfirmed = [material.name for material in materials if not material.role_confirmed]

    if not materials:
        blocking.append("未上传纳入正式审查的送审材料")
    if "top_requirement" not in role_set:
        missing.append("top_requirement")
        blocking.append("缺少上级需求文档，不能开展需求闭环审查")
    if "decomposed_requirement" not in role_set:
        missing.append("decomposed_requirement")
        limited.append("缺少需求分解文档，不能判定分解完整性")
    if "design_solution" not in role_set:
        missing.append("design_solution")
        limited.append("缺少设计方案文档，不能判定设计闭合")
    if "interface_control" not in role_set:
        missing.append("interface_control")
        limited.append("缺少接口控制文件，不能判定接口约束闭合")
    if "verification_plan" not in role_set:
        missing.append("verification_plan")
        limited.append("缺少验证计划，不能判定验证矩阵完整性")
    if not ({"simulation_report", "verification_result"} & role_set):
        missing.append("simulation_report_or_verification_result")
        limited.append("缺少仿真/验证结果，不能判定验证通过")
    if failed:
        blocking.append(f"存在不可解析材料: {', '.join(failed)}")
    if unconfirmed:
        warnings.append(f"存在未确认文档角色材料: {', '.join(unconfirmed[:5])}")
    missing_document_versions = [
        material.name
        for material in materials
        if material.document_role in REQUIRED_ROLES and not (material.document_version or "").strip()
    ]
    if missing_document_versions:
        warnings.append(
            "正式材料缺少文档版本: "
            + ", ".join(missing_document_versions[:5])
            + (" 等" if len(missing_document_versions) > 5 else "")
        )
    if not task.template_id:
        warnings.append("未绑定评审模板，审定结论应标记为受限")
    if not any([
        task.baseline.requirements_version,
        task.baseline.design_version,
        task.baseline.simulation_version,
        task.baseline.verification_version,
    ]):
        warnings.append("未确认版本基线，不能形成正式审定结论")

    if blocking:
        status = "blocked"
    elif limited or missing:
        status = "limited_pass"
    elif warnings:
        status = "pass_with_note"
    else:
        status = "pass"

    return GatekeepingResult(
        review_id=task.review_id,
        gate_status=status,
        gate_summary="；".join(blocking or limited or warnings or ["送审包具备 P0 需求闭环审查上下文"]),
        can_start_review=status != "blocked",
        blocking_reasons=blocking,
        limited_scope=limited,
        missing_materials=missing,
        parsing_failed_materials=failed,
        warnings=warnings,
        materials=[_material_summary(material) for material in materials],
        checked_at=datetime.now().isoformat(),
    )


def traceability_gate_payload(task: ReviewTask) -> dict[str, Any]:
    """Return gate fields aligned with GatekeepingResult four-state vocabulary."""
    result = evaluate_package_gatekeeping(task)
    return {
        "gate_status": result.gate_status,
        "gate_summary": result.gate_summary,
        "blocking_reasons": result.blocking_reasons,
        "limited_scope": result.limited_scope,
        "missing_materials": result.missing_materials,
        "parsing_failed_materials": result.parsing_failed_materials,
        "warnings": result.warnings,
    }


def _suggest_missing_roles(task: ReviewTask) -> None:
    for material in task.materials.materials if task.materials else []:
        if material.document_role:
            continue
        suggestion = infer_material_role(material.name, material.content, material.file_type)
        material.document_role = suggestion.document_role
        material.role_confidence = suggestion.confidence
        material.role_reason = suggestion.reason


def _material_summary(material: MaterialItem) -> dict[str, Any]:
    return build_material_summary(material, role_labels=P0_GATEKEEPING_ROLE_LABELS)
