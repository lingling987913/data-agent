from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MaterialRole(str, Enum):
    REVIEW_RULE = "review_rule"
    CHECKLIST = "checklist"
    TASK_BOOK = "task_book"
    SUBJECT_REPORT = "subject_report"
    ACCEPTANCE_REPORT = "acceptance_report"
    MOTOR_SPEC = "motor_spec"
    ENGINEERING_DRAWING = "engineering_drawing"
    TEST_DATA = "test_data"
    UNKNOWN = "unknown"


class TaskScenario(str, Enum):
    SINGLE_DOC_PARSE = "single_doc_parse"
    PACKAGE_REVIEW = "product_assurance_reliability_safety"
    CROSS_PACKAGE_COMPARE = "cross_package_compare"


def classify_material_role(file_name: str, role_hint: str | None = None) -> MaterialRole:
    from data_agent.services.task_classifier import to_material_role

    return to_material_role(role_hint or "", file_name)


def detect_scenario(documents: list[dict]) -> TaskScenario:
    names = [d.get("file_name", "") for d in documents]
    has_xlsx_rule = any("检查需求" in n and n.endswith(".xlsx") for n in names)
    if len(documents) >= 8:
        return TaskScenario.CROSS_PACKAGE_COMPARE
    if len(documents) >= 3 and has_xlsx_rule:
        return TaskScenario.PACKAGE_REVIEW
    return TaskScenario.SINGLE_DOC_PARSE


class ReviewCheckItem(BaseModel):
    item_no: str = ""
    check_subject: str = ""
    check_target: str = ""
    requirement: str = ""
    remark: str = ""


class MaterialSummary(BaseModel):
    file_name: str
    role: MaterialRole
    parser_name: str = ""
    parse_status: str = ""
    block_count: int = 0
    section_count: int = 0


class StructuredTaskResult(BaseModel):
    scenario: TaskScenario
    package_id: str | None = None
    materials: list[MaterialSummary] = Field(default_factory=list)
    check_items: list[ReviewCheckItem] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
    cross_doc_findings: list[dict] = Field(default_factory=list)
    review_report_markdown: str | None = None
    review_conclusion: str | None = None
    structured_output: dict = Field(default_factory=dict)
    markdown_output: str | None = None
    section_trees: dict[str, dict] = Field(default_factory=dict)
    evidence_pools: dict[str, list] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    parser_trace: list[dict] = Field(default_factory=list)
    cross_package_compare: dict | None = None
    tdms_metadata: dict | None = None
