from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from data_agent.review_plus.schemas import (
    ReviewPlusCheckItem,
    ReviewPlusFinding,
    ReviewPlusFindingSeverity,
    ReviewPlusJudgment,
    ReviewPlusMaterialRole,
    ReviewPlusSectionMapping,
)

__all__ = [
    "CrossDocFinding",
    "PackageReviewReport",
    "ParsedMaterial",
    "ReviewPlusCheckItem",
    "ReviewPlusFinding",
    "ReviewPlusFindingSeverity",
    "ReviewPlusJudgment",
    "ReviewPlusMaterialRole",
    "ReviewPlusSectionMapping",
]


def _gen_id() -> str:
    return str(uuid.uuid4())[:12]


class ParsedMaterial(BaseModel):
    name: str
    file_path: str = ""
    file_type: str = ""
    content: str = ""
    parser_name: str = ""
    parse_status: str = ""
    warnings: list[str] = Field(default_factory=list)
    role: ReviewPlusMaterialRole = ReviewPlusMaterialRole.UNKNOWN
    role_confidence: float = 0.0
    role_reason: str = ""


class CrossDocFinding(BaseModel):
    finding_id: str = Field(default_factory=_gen_id)
    finding_type: str = "cross_document_issue"
    severity: str = "major"
    title: str = ""
    description: str = ""
    doc_a: str = ""
    doc_b: str = ""
    source_quotes: list[str] = Field(default_factory=list)
    recommendation: str = ""


class PackageReviewReport(BaseModel):
    report_id: str = Field(default_factory=_gen_id)
    scenario: str = ""
    package_id: str | None = None
    check_items: list[ReviewPlusCheckItem] = Field(default_factory=list)
    total_check_items: int = 0
    satisfied_count: int = 0
    not_satisfied_count: int = 0
    insufficient_evidence_count: int = 0
    critical_count: int = 0
    findings: list[ReviewPlusFinding] = Field(default_factory=list)
    cross_doc_findings: list[CrossDocFinding] = Field(default_factory=list)
    conclusion: str = ""
    summary: str = ""
    markdown: str = ""
