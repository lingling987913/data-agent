"""Bridge Review-Plus task/material models to legacy P0 ReviewTask semantics."""

from __future__ import annotations

from data_agent.review.material_role_service import infer_material_role
from data_agent.review.p0_schemas import MaterialItem, MaterialPackage, ReviewBaseline, ReviewTask
from data_agent.review_plus.schemas import ReviewPlusMaterialRole, ReviewPlusTask


def to_legacy_review_task(task: ReviewPlusTask) -> ReviewTask:
    materials = [to_legacy_material(material) for material in task.materials]
    return ReviewTask(
        review_id=task.review_plus_id,
        name=task.name,
        materials=MaterialPackage(materials=materials),
        baseline=baseline_from_materials(materials),
    )


def to_legacy_material(material) -> MaterialItem:
    document_role, role_confidence, role_reason = legacy_document_role(material)
    return MaterialItem(
        name=material.name,
        file_type=material.file_type,
        content=material.content,
        file_path=material.file_path,
        parser_type=material.parser_type,
        parse_status=material.parse_status,
        parser_name=material.parser_name,
        warnings=list(material.warnings),
        document_role=document_role,
        document_version=material.document_version,
        baseline_id=material.baseline_id,
        source_system=material.source_system,
        external_document_id=material.external_document_id,
        included_in_formal_review=material.included_in_formal_review,
        role_confirmed=material.role_confirmed,
        role_confidence=role_confidence,
        role_reason=role_reason,
    )


def legacy_document_role(material) -> tuple[str, float, str]:
    role_value = material.role.value if isinstance(material.role, ReviewPlusMaterialRole) else str(material.role or "")
    if role_value in {
        ReviewPlusMaterialRole.REVIEW_RULE.value,
        ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT.value,
    }:
        return (
            "supporting_attachment",
            material.role_confidence,
            material.role_reason or "Review-Plus 通用角色映射为旧链路支撑附件",
        )

    suggestion = infer_material_role(material.name, material.content, material.file_type)
    if suggestion.document_role:
        return suggestion.document_role, suggestion.confidence, suggestion.reason

    return "", material.role_confidence, material.role_reason


def baseline_from_materials(materials: list[MaterialItem]) -> ReviewBaseline:
    baseline = ReviewBaseline()
    for material in materials:
        version = (material.baseline_id or material.document_version or "").strip()
        if not version:
            continue
        if material.document_role in {"top_requirement", "decomposed_requirement"} and not baseline.requirements_version:
            baseline.requirements_version = version
        elif material.document_role == "design_solution" and not baseline.design_version:
            baseline.design_version = version
        elif material.document_role == "interface_control" and not baseline.icd_version:
            baseline.icd_version = version
        elif material.document_role == "simulation_report" and not baseline.simulation_version:
            baseline.simulation_version = version
        elif material.document_role in {"verification_plan", "verification_result"} and not baseline.verification_version:
            baseline.verification_version = version
    return baseline
