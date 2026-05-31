"""
Review-Plus 结构化数据模型

独立的审查链路数据结构，与现有 GNC 评审模型完全解耦。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _gen_id() -> str:
    return str(uuid.uuid4())[:12]


class ReviewPlusMaterialRole(str, Enum):
    REVIEW_RULE = "review_rule"
    CHECKLIST = "checklist"
    TASK_BOOK = "task_book"
    SUBJECT_REPORT = "subject_report"
    SUBJECT_DOCUMENT = "subject_document"
    SUPPORTING_ATTACHMENT = "supporting_attachment"
    UNKNOWN = "unknown"


class ReviewPlusMaterialItem(BaseModel):
    name: str = ""
    file_type: str = ""
    content: str = ""
    file_path: str = ""
    parser_type: str = "local"
    parser_name: str = ""
    warnings: list[str] = Field(default_factory=list)
    parse_status: str = ""
    role: ReviewPlusMaterialRole = ReviewPlusMaterialRole.UNKNOWN
    role_confidence: float = 0.0
    role_reason: str = ""
    document_version: str = ""
    baseline_id: str = ""
    source_system: str = ""
    external_document_id: str = ""
    included_in_formal_review: bool = True
    role_confirmed: bool = False
    parser_trace: list[dict[str, Any]] = Field(default_factory=list)


class ReviewPlusCheckItem(BaseModel):
    check_item_id: str = Field(default_factory=_gen_id)
    item_no: str = ""
    title: str = ""
    requirement_text: str = ""
    acceptance_criteria: str = ""
    applicable_scope: str = ""
    severity: str = "minor"
    category: str = ""
    source_material_name: str = ""
    source_role: str = ""
    source_sheet: str = ""
    source_row: int | None = None
    source_page: int | None = None
    source_quote: str = ""
    confidence: float = 0.0


class ReviewPlusJudgment(str, Enum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"
    NOT_CHECKED = "not_checked"


class ReviewPlusFindingSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class ReviewPlusSectionMapping(BaseModel):
    """检查项与文档章节的映射关系"""
    check_item_id: str = ""
    section_ids: list[str] = Field(default_factory=list)
    section_titles: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    method: str = "keyword"  # keyword | semantic | manual
    rationale: str = ""


class ReviewPlusFinding(BaseModel):
    """逐项审查产出的审查发现"""
    finding_id: str = Field(default_factory=_gen_id)
    check_item_id: str = ""
    judgment: ReviewPlusJudgment = ReviewPlusJudgment.NOT_CHECKED
    severity: ReviewPlusFindingSeverity = ReviewPlusFindingSeverity.MINOR
    title: str = ""
    reasoning: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    source_quotes: list[str] = Field(default_factory=list)
    recommendation: str = ""
    confidence: float = 0.0
    section_ids: list[str] = Field(default_factory=list)
    source_quote: str = ""
    checklist_source_role: str = ""
    checklist_source_material_name: str = ""
    task_book_evidence_refs: list[str] = Field(default_factory=list)
    subject_evidence_refs: list[str] = Field(default_factory=list)
    coverage_status: str = ""


class ReviewPlusChiefEngineeringConclusion(BaseModel):
    """总审查员综合判断 — 单条工程结论"""
    conclusion_id: str = Field(default_factory=_gen_id)
    title: str = ""
    description: str = ""
    evidence_sources: list[str] = Field(default_factory=list)
    involved_documents: list[str] = Field(default_factory=list)
    risk_impact: str = ""
    recommendation: str = ""
    severity: str = "major"
    confidence: float = 0.0


class ReviewPlusChiefComprehensiveReview(BaseModel):
    """总审查员综合判断 — 基于全文/证据/专家 findings 的工程审查结论"""
    status: str = "unavailable"  # ok | degraded | unavailable
    method: str = ""  # llm_chief | heuristic_fallback
    overall_assessment: str = ""
    release_recommendation: str = ""  # approve | conditional | reject | needs_human_review
    engineering_conclusions: list[ReviewPlusChiefEngineeringConclusion] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    rationale: str = ""
    degraded: bool = False
    degrade_reason: str = ""


class ReviewPlusReport(BaseModel):
    """最终审查报告"""
    report_id: str = Field(default_factory=_gen_id)
    total_check_items: int = 0
    satisfied_count: int = 0
    not_satisfied_count: int = 0
    insufficient_evidence_count: int = 0
    not_checked_count: int = 0
    critical_count: int = 0
    findings: list[ReviewPlusFinding] = Field(default_factory=list)
    conclusion: str = ""
    summary: str = ""
    residual_risks: list[str] = Field(default_factory=list)
    cross_references: list[dict[str, Any]] = Field(default_factory=list)
    cross_document_items: list[dict[str, Any]] = Field(default_factory=list)
    chief_comprehensive_review: ReviewPlusChiefComprehensiveReview | None = None
    markdown: str = ""


class ReviewPlusGatekeepingResult(BaseModel):
    review_id: str = ""
    gate_status: str = "blocked"  # blocked | limited | passed
    gate_summary: str = ""
    can_start_review: bool = False
    blocking_reasons: list[str] = Field(default_factory=list)
    limited_scope: list[str] = Field(default_factory=list)
    missing_materials: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReviewPlusStatus(str, Enum):
    DRAFT = "draft"
    MATERIALS_UPLOADED = "materials_uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    CLASSIFYING = "classifying"
    CLASSIFIED = "classified"
    SCENARIO_DETECTED = "scenario_detected"
    GATEKEEPING = "gatekeeping"
    TRACEABILITY_BUILDING = "traceability_building"
    STRUCTURING = "structuring"
    RULE_EXTRACTING = "rule_extracting"
    READY = "ready"
    BLOCKED = "blocked"
    LIMITED_PASS = "limited_pass"
    MAPPING = "mapping"
    REVIEWING = "reviewing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewPlusParserType(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    MINERU = "mineru"
    MINERU_AGENT = "mineru_agent"
    MINERU_VIA_PDF = "mineru_via_pdf"
    RAGFLOW = "ragflow"


class ReviewPlusTask(BaseModel):
    review_plus_id: str = Field(default_factory=_gen_id)
    name: str = ""
    scenario: str = ""
    scenario_confidence: float = 0.0
    scenario_reason: str = ""
    status: str = "draft"
    materials: list[ReviewPlusMaterialItem] = Field(default_factory=list)
    check_items: list[ReviewPlusCheckItem] = Field(default_factory=list)
    parsed_documents: list[dict[str, Any]] = Field(default_factory=list)
    section_tree: dict[str, Any] = Field(default_factory=dict)
    evidence_pool: dict[str, Any] = Field(default_factory=dict)
    document_ir: dict[str, Any] = Field(default_factory=dict)
    parse_artifact: dict[str, Any] = Field(default_factory=dict)
    object_registry: dict[str, Any] = Field(default_factory=dict)
    document_format_review: dict[str, Any] = Field(default_factory=dict)
    chief_review_plan: dict[str, Any] = Field(default_factory=dict)
    specialist_reviews: list[dict[str, Any]] = Field(default_factory=list)
    traceability_result: dict[str, Any] = Field(default_factory=dict)
    cross_document_review_items: list[dict[str, Any]] = Field(default_factory=list)
    coverage_matrix: dict[str, Any] = Field(default_factory=dict)
    agent_run_traces: list[dict[str, Any]] = Field(default_factory=list)
    gatekeeping_result: dict[str, Any] = Field(default_factory=dict)
    section_mappings: list[ReviewPlusSectionMapping] = Field(default_factory=list)
    findings: list[ReviewPlusFinding] = Field(default_factory=list)
    report: Optional[ReviewPlusReport] = None
    report_markdown: str = ""
    report_file_path: str = ""
    parser_traces: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class CreateReviewPlusRequest(BaseModel):
    name: str = ""
