"""Pydantic models for the satellite GNC design review integration."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _gen_id() -> str:
    return str(uuid.uuid4())[:12]


def _now() -> str:
    return datetime.now().isoformat()


class GNCReviewMode(str, Enum):
    SINGLE_DOC = "single_doc"
    MULTI_DOC = "multi_doc"


class GNCReviewStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ARBITRATION_PENDING = "arbitration_pending"


class GNCReviewDocument(BaseModel):
    name: str = ""
    content: str = ""
    file_path: str = ""
    document_type: str = "design_document"
    version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class GNCReviewRule(BaseModel):
    rule_id: str = Field(default_factory=_gen_id)
    title: str = ""
    requirement_text: str = ""
    severity: str = "major"
    category: str = ""
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class GNCExpertFinding(BaseModel):
    finding_id: str = Field(default_factory=_gen_id)
    agent_id: str = ""
    expert_role: str = ""
    discipline: str = ""
    title: str = ""
    description: str = ""
    severity: str = "minor"
    judgment: str = "insufficient_evidence"
    evidence_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    source_quotes: list[str] = Field(default_factory=list)
    recommendation: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class GNCConflictReport(BaseModel):
    conflict_id: str = Field(default_factory=_gen_id)
    conflict_key: str = ""
    conflict_type: str = ""
    summary: str = ""
    observations: list[dict[str, Any]] = Field(default_factory=list)
    recommended_resolution: dict[str, Any] = Field(default_factory=dict)
    requires_arbitration: bool = False


class GNCReviewResult(BaseModel):
    review_id: str = ""
    mode: GNCReviewMode = GNCReviewMode.SINGLE_DOC
    status: GNCReviewStatus = GNCReviewStatus.COMPLETED
    findings: list[GNCExpertFinding] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[GNCConflictReport] = Field(default_factory=list)
    quality_scores: dict[str, float] = Field(default_factory=dict)
    discipline_reviews: dict[str, Any] = Field(default_factory=dict)
    editorial_synthesis: dict[str, Any] = Field(default_factory=dict)
    chief_decision: dict[str, Any] = Field(default_factory=dict)
    arbitration: dict[str, Any] = Field(default_factory=dict)
    report_markdown: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class GNCReviewRequest(BaseModel):
    name: str = ""
    documents: list[GNCReviewDocument] = Field(default_factory=list)
    review_rules: list[GNCReviewRule] = Field(default_factory=list)
    mode: GNCReviewMode = GNCReviewMode.SINGLE_DOC
    product_model: str = ""
    review_phase: str = "CDR"
    review_scope: str = "ad_ac"
    review_focus: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("documents")
    @classmethod
    def _require_documents(cls, value: list[GNCReviewDocument]) -> list[GNCReviewDocument]:
        if not value:
            raise ValueError("documents cannot be empty")
        return value


class GNCReviewRun(BaseModel):
    review_id: str = Field(default_factory=_gen_id)
    name: str = ""
    request: GNCReviewRequest
    status: GNCReviewStatus = GNCReviewStatus.DRAFT
    current_step: str = ""
    step_outputs: dict[str, Any] = Field(default_factory=dict)
    result: GNCReviewResult | None = None
    error: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class GNCCommitteeOutput(BaseModel):
    reviewer: str = ""
    discipline: str = ""
    score: float = 0.0
    summary: str = ""
    completed: bool = True
    knowledge_gap: bool = False
    findings: list[GNCExpertFinding] = Field(default_factory=list)


class GNCEditorialOutput(BaseModel):
    rid_items: list[dict[str, Any]] = Field(default_factory=list)
    minutes: str = ""
    conclusion_draft: str = ""
    residual_risks: list[str] = Field(default_factory=list)
    cross_discipline_issues: list[str] = Field(default_factory=list)
    degraded: bool = False
    degrade_reason: str = ""


class GNCChiefDecisionOutput(BaseModel):
    verdict: str = "conditionally_approved"
    rationale: str = ""
    key_risks: list[str] = Field(default_factory=list)
    conflict_resolutions: list[str] = Field(default_factory=list)
    requires_arbitration: bool = False
    arbitration_items: list[str] = Field(default_factory=list)
    degraded: bool = False
    degrade_reason: str = ""
