"""Review-Plus package slot checks shared by gatekeeping and agent harness."""

from __future__ import annotations

from typing import Any

from data_agent.review_plus.schemas import ReviewPlusMaterialRole, ReviewPlusTask

from data_agent.review_plus.text_utils import role_value

REVIEW_PLUS_RULE_SOURCE_ROLES = (
    ReviewPlusMaterialRole.REVIEW_RULE,
    ReviewPlusMaterialRole.CHECKLIST,
)
REVIEW_PLUS_REQUIRED_ROLES = (ReviewPlusMaterialRole.TASK_BOOK,)
REVIEW_PLUS_SUBJECT_ROLES = (
    ReviewPlusMaterialRole.SUBJECT_REPORT,
    ReviewPlusMaterialRole.SUBJECT_DOCUMENT,
)
ROLE_LABELS = {
    ReviewPlusMaterialRole.REVIEW_RULE: "检查需求",
    ReviewPlusMaterialRole.CHECKLIST: "检查单",
    ReviewPlusMaterialRole.TASK_BOOK: "任务书",
    ReviewPlusMaterialRole.SUBJECT_REPORT: "被审报告",
    ReviewPlusMaterialRole.SUBJECT_DOCUMENT: "待审文档",
}


def material_role_set(materials: list[Any]) -> set[str]:
    return {role_value(material) for material in materials if role_value(material)}


def evaluate_review_plus_package_slots(
    task: ReviewPlusTask | Any,
) -> tuple[list[str], list[str], list[str], set[str]]:
    """Return blocking reasons, missing slots, limited warnings, and role set."""
    materials = getattr(task, "materials", []) or []
    role_set = material_role_set(materials)
    blocking: list[str] = []
    missing: list[str] = []
    limited: list[str] = []

    if not (role_set & {item.value for item in REVIEW_PLUS_RULE_SOURCE_ROLES}):
        missing.append("review_rule_or_checklist")
        blocking.append("缺少检查需求或检查单")

    for role in REVIEW_PLUS_REQUIRED_ROLES:
        if role.value not in role_set:
            missing.append(role.value)
            blocking.append(f"缺少{ROLE_LABELS[role]}")

    if not (role_set & {item.value for item in REVIEW_PLUS_SUBJECT_ROLES}):
        missing.append("subject_report")
        blocking.append("缺少被审报告或待审文档")

    unknown_files = [
        material.name
        for material in materials
        if role_value(material) == ReviewPlusMaterialRole.UNKNOWN.value
    ]
    if unknown_files:
        limited.append(f"存在未识别角色材料: {', '.join(unknown_files[:5])}")

    unconfirmed = [
        material.name
        for material in materials
        if not material.role_confirmed
        and role_value(material) != ReviewPlusMaterialRole.UNKNOWN.value
    ]
    if unconfirmed:
        limited.append(f"存在待确认角色材料: {', '.join(unconfirmed[:5])}")

    return blocking, missing, limited, role_set


def assert_review_plus_package_slots(task: Any) -> set[str]:
    """Raise ValueError with a stable error code when required slots are missing."""
    blocking, _, _, role_set = evaluate_review_plus_package_slots(task)
    if not (role_set & {item.value for item in REVIEW_PLUS_RULE_SOURCE_ROLES}):
        raise ValueError("missing_rule_source")
    if ReviewPlusMaterialRole.TASK_BOOK.value not in role_set:
        raise ValueError("missing_task_book")
    if not (role_set & {item.value for item in REVIEW_PLUS_SUBJECT_ROLES}):
        raise ValueError("missing_subject")
    if blocking:
        raise ValueError(blocking[0])
    return role_set
