"""Unified review workbench contracts shared by GNC and Review-Plus."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReviewType(str, Enum):
    GNC = "gnc"
    REVIEW_PLUS = "review_plus"
    SUPER_AGENT = "super_agent"


class WorkbenchPhase(str, Enum):
    PRE_REVIEW = "pre_review"
    STARTUP = "startup"
    EXECUTING = "executing"
    ARBITRATION = "arbitration"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkbenchTab(str, Enum):
    OVERVIEW = "overview"
    ROUTES = "routes"
    CLOSURE = "closure"
    QUALITY = "quality"
    FLOW = "flow"
    MATERIALS = "materials"
    CHECK_ITEMS = "check_items"
    FINDINGS = "findings"
    COVERAGE = "coverage"
    TRACEABILITY = "traceability"
    CROSS_DOC = "cross_doc"
    REPORT = "report"
    EVENTS = "events"
    RID = "rid"
    MINUTES = "minutes"
    DECISION = "decision"
    COMMITTEE = "committee"
    EVIDENCES = "evidences"
    ARBITRATION = "arbitration"


class WorkbenchMetrics(BaseModel):
    finding_count: int = 0
    problem_count: int = 0
    check_item_count: int = 0
    pending_confirm: int = 0
    rid_count: int = 0
    open_rid_count: int = 0
    evidence_count: int = 0
    conflict_count: int = 0
    requires_arbitration: bool = False
    material_count: int = 0


class WorkbenchSummary(BaseModel):
    verdict: str = ""
    verdict_label_zh: str = ""
    rationale: str = ""
    rationale_zh: str = ""
    requires_arbitration: bool = False
    arbitration_status: str = ""
    report_available: bool = False
    headline_verdict: str = ""
    one_line_conclusion: str = ""
    review_mode_label: str = ""


class WorkbenchConclusionOverview(BaseModel):
    """Business-readable conclusion snapshot for overview panels."""

    headline_verdict: str = ""
    headline_zh: str = ""
    one_line_conclusion: str = ""
    verdict_label_zh: str = ""
    rationale_zh: str = ""
    issue_buckets: dict[str, int] = Field(default_factory=dict)
    bucket_labels: dict[str, str] = Field(default_factory=dict)
    review_scope: dict[str, Any] = Field(default_factory=dict)
    priority_items: list[dict[str, Any]] = Field(default_factory=list)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)


class UnifiedReviewWorkbenchDetail(BaseModel):
    review_id: str
    name: str = ""
    review_type: ReviewType
    status: str = ""
    workbench_phase: WorkbenchPhase
    visible_tabs: list[str] = Field(default_factory=list)
    current_step: str = ""
    metrics: WorkbenchMetrics = Field(default_factory=WorkbenchMetrics)
    summary: WorkbenchSummary = Field(default_factory=WorkbenchSummary)
    conclusion_overview: WorkbenchConclusionOverview | None = None
    error: str = ""
    created_at: str = ""
    updated_at: str = ""


GNCArbitrationStatus = Literal["resolved", "completed", "pending"]
GNCRidStatus = Literal["open", "closed", "pending", "reopened"]


class GNCArbitrationRequest(BaseModel):
    """Human arbitration resolution payload."""

    status: GNCArbitrationStatus = "resolved"
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


class GNCRidPatchRequest(BaseModel):
    """Partial update for a single RID item."""

    status: GNCRidStatus | None = None
    notes: str | None = None
    comment: str | None = None
