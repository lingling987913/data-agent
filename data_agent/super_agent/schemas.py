"""Schemas for the Review Data Super Agent facade.

Ported from aq-aero review_data_agent_schemas with additive fields reserved
for later phases (execution_plan, self_healing_records, cost_summary).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _gen_id() -> str:
    return f"rda_{uuid.uuid4().hex[:12]}"


class SuperAgentInputMode(str, Enum):
    UPLOAD = "upload"
    EXISTING_REVIEW_PLUS = "existing_review_plus"
    EXISTING_GNC_REVIEW = "existing_gnc_review"


class SuperAgentRoute(str, Enum):
    AUTO = "auto"
    REVIEW_PLUS = "review_plus"
    GNC_REVIEW = "gnc_review"
    GNC_REVIEW_ONLY = "gnc_review_only"
    STRUCTURE_ONLY = "structure_only"
    HYBRID = "hybrid"
    SMART = "smart"  # 智能模式 — 万能路由


class SuperAgentReviewMode(str, Enum):
    SINGLE_DOC = "single_doc"
    MULTI_DOC = "multi_doc"
    FULL = "full"


class SuperAgentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    LIMITED = "limited"


class SuperAgentMaterial(BaseModel):
    name: str = ""
    file_type: str = ""
    content: str = ""
    content_base64: str = ""
    content_preview: str = ""
    file_path: str = ""
    source_display_path: str = ""
    upload_id: str = ""
    file_id: str = ""
    file_size: int = 0
    parser_type: str = "auto"
    role: str = ""
    document_version: str = ""
    baseline_id: str = ""


class ParsePreviewBlock(BaseModel):
    id: str = ""
    block_type: str = "paragraph"
    content: str = ""
    markdown: str = ""
    page_hint: int | None = None
    bbox: list[float] | None = None
    level: int | None = None
    formula_latex: str | None = None


class MaterialParsePreviewItem(BaseModel):
    file_name: str = ""
    role: str = "unknown"
    role_confidence: float = 0.0
    role_reason: str = ""
    parsing_tier: str = "standard"
    parser_type: str = "auto"
    processing_mode: str = "OPTIMAL"
    parse_status: str = ""
    parser_name: str = ""
    content_preview: str = ""
    content_markdown: str = ""
    content_markdown_truncated: bool = False
    content_length: int = 0
    line_count: int = 0
    source_file_type: str = ""
    page_count: int = 0
    blocks: list[ParsePreviewBlock] = Field(default_factory=list)
    parse_artifact_subset: dict[str, Any] = Field(default_factory=dict)
    source_download_url: str = ""
    file_id: str = ""
    upload_id: str = ""
    warnings: list[str] = Field(default_factory=list)
    parser_trace: list[dict[str, Any]] = Field(default_factory=list)
    capability_passed: bool = False
    degraded: bool = False
    document_ir_stats: dict[str, int] = Field(default_factory=dict)


class ParsePreviewResponse(BaseModel):
    classification: dict[str, Any] = Field(default_factory=dict)
    materials: list[MaterialParsePreviewItem] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class CreateSuperAgentRunRequest(BaseModel):
    name: str = ""
    objective: str = ""
    processing_mode: str = "OPTIMAL"
    input_mode: SuperAgentInputMode = SuperAgentInputMode.EXISTING_REVIEW_PLUS
    source_review_id: str = ""
    requested_route: SuperAgentRoute = SuperAgentRoute.AUTO
    review_mode: SuperAgentReviewMode = SuperAgentReviewMode.FULL
    materials: list[SuperAgentMaterial] = Field(default_factory=list)
    classification: Optional[dict[str, Any]] = None
    execute: bool = True


class SaveWizardCheckpointRequest(BaseModel):
    """向导步骤检查点：仅更新 draft run 的前置配置，不重置执行产物。"""

    wizard_step: Optional[int] = Field(default=None, ge=1, le=5)
    materials: Optional[list[SuperAgentMaterial]] = None
    classification: Optional[dict[str, Any]] = None
    parse_preview: Optional[dict[str, Any]] = None
    processing_mode: Optional[str] = None
    requested_route: Optional[SuperAgentRoute] = None
    review_mode_selection: Optional[str] = None
    objective: Optional[str] = None


class SuperAgentParseRunRequest(BaseModel):
    """独立文档解析 API：基于 run 材料产出 parse-only artifact。"""

    include_structure: bool = False
    force_reparse: bool = False


class SuperAgentReviewRunRequest(BaseModel):
    """独立文档审查 API：基于已有 parse artifact 执行 review，默认不重复 parse。"""

    review_mode: Optional[SuperAgentReviewMode] = None
    requested_route: Optional[SuperAgentRoute] = None
    objective: Optional[str] = None
    skip_reparse: bool = True
    force_rerun: bool = False


class SuperAgentRouteDecision(BaseModel):
    route: SuperAgentRoute = SuperAgentRoute.STRUCTURE_ONLY
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    skipped_tools: list[str] = Field(default_factory=list)
    gnc_review_id: str = ""
    classification: dict[str, Any] = Field(default_factory=dict)


class SuperAgentSkillTrace(BaseModel):
    skill_id: str
    agent_id: str = ""
    tool_name: str = ""
    status: str = "pending"
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0


class StructuredReviewBundle(BaseModel):
    materials: list[dict[str, Any]] = Field(default_factory=list)
    parser_traces: list[dict[str, Any]] = Field(default_factory=list)
    section_tree: dict[str, Any] = Field(default_factory=dict)
    evidence_pool: dict[str, Any] = Field(default_factory=dict)
    document_ir: dict[str, Any] = Field(default_factory=dict)
    parse_artifact: dict[str, Any] = Field(default_factory=dict)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    check_items: list[dict[str, Any]] = Field(default_factory=list)
    extracted_parameters: list[dict[str, Any]] = Field(default_factory=list)
    extracted_objects: list[dict[str, Any]] = Field(default_factory=list)
    trace_link_candidates: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    parser_fallback_logs: list[dict[str, Any]] = Field(default_factory=list)
    self_healing_records: list[dict[str, Any]] = Field(default_factory=list)


class SuperAgentTraceReport(BaseModel):
    parser_traces: list[dict[str, Any]] = Field(default_factory=list)
    agent_run_traces: list[dict[str, Any]] = Field(default_factory=list)
    workflow_events: list[dict[str, Any]] = Field(default_factory=list)
    fallback_events: list[dict[str, Any]] = Field(default_factory=list)
    failed_steps: list[dict[str, Any]] = Field(default_factory=list)
    degradation_summary: list[str] = Field(default_factory=list)


class SuperAgentQualityReport(BaseModel):
    parse_quality_score: float = 0.0
    evidence_quality_score: float = 0.0
    traceability_score: float = 0.0
    consistency_score: float = 0.0
    stability_score: float = 0.0
    overall_score: float = 0.0
    expert_consensus_score: float = 0.0
    evidence_sufficiency_score: float = 0.0
    conflict_detection_score: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    human_confirmation_required: bool = False


class SuperAgentRun(BaseModel):
    run_id: str = Field(default_factory=_gen_id)
    name: str = ""
    objective: str = ""
    processing_mode: str = "OPTIMAL"
    input_mode: SuperAgentInputMode = SuperAgentInputMode.EXISTING_REVIEW_PLUS
    source_review_id: str = ""
    requested_route: SuperAgentRoute = SuperAgentRoute.AUTO
    review_mode: SuperAgentReviewMode = SuperAgentReviewMode.FULL
    materials: list[SuperAgentMaterial] = Field(default_factory=list)
    route_decision: Optional[SuperAgentRouteDecision] = None
    classification: dict[str, Any] = Field(default_factory=dict)
    structured_bundle: StructuredReviewBundle = Field(default_factory=StructuredReviewBundle)
    review_plus_result: dict[str, Any] = Field(default_factory=dict)
    gnc_review_result: dict[str, Any] = Field(default_factory=dict)
    report_markdown: str = ""
    report_artifact: dict[str, Any] = Field(default_factory=dict)
    trace_report: SuperAgentTraceReport = Field(default_factory=SuperAgentTraceReport)
    quality_report: SuperAgentQualityReport = Field(default_factory=SuperAgentQualityReport)
    execution_metrics_snapshot: dict[str, Any] = Field(default_factory=dict)
    skill_traces: list[SuperAgentSkillTrace] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    wizard_step: int = 0
    current_phase: str = ""
    phase_status: str = "pending"
    phase_artifacts: dict[str, Any] = Field(default_factory=dict)
    parse_preview: dict[str, Any] = Field(default_factory=dict)
    status: SuperAgentStatus = SuperAgentStatus.DRAFT
    error: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class SuperAgentCapabilities(BaseModel):
    team_id: str = "data-agent:super_agent"
    display_name: str = "Review Data Super Agent"
    routes: list[str] = Field(
        default_factory=lambda: [
            "review_plus",
            "gnc_review",
            "gnc_review_only",
            "structure_only",
            "hybrid",
            "smart",
        ]
    )
    independent_apis: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {
                "id": "document_parse",
                "method": "POST",
                "path": "/api/v1/super-agent/runs/{run_id}/parse",
                "description": "基于已分类材料产出 parse-only artifact",
            },
            {
                "id": "document_review",
                "method": "POST",
                "path": "/api/v1/super-agent/runs/{run_id}/review",
                "description": "基于已有 parse artifact 执行审查技能",
            },
        ]
    )
    skills: list[dict[str, str]] = Field(default_factory=list)
    reused_components: list[str] = Field(default_factory=list)


class SuperAgentParseRunResponse(BaseModel):
    run_id: str = ""
    parse_artifact: dict[str, Any] = Field(default_factory=dict)
    document_ir: dict[str, Any] = Field(default_factory=dict)
    batch_summary: dict[str, Any] = Field(default_factory=dict)
    materials: list[dict[str, Any]] = Field(default_factory=list)
    structured_bundle: Optional[StructuredReviewBundle] = None


class SuperAgentReviewRunResponse(BaseModel):
    run_id: str = ""
    route: str = ""
    review_plus_result: dict[str, Any] = Field(default_factory=dict)
    gnc_review_result: dict[str, Any] = Field(default_factory=dict)
    structured_bundle: StructuredReviewBundle = Field(default_factory=StructuredReviewBundle)
    skill_traces: list[SuperAgentSkillTrace] = Field(default_factory=list)
