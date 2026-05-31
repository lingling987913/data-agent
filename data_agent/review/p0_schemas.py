"""P0 traceability / gatekeeping schemas (source-equivalent subset)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


def _gen_id() -> str:
    return str(uuid.uuid4())[:12]


class MaterialItem(BaseModel):
    name: str = ""
    file_type: str = ""
    description: str = ""
    content: str = ""
    file_path: str = ""
    parser_type: str = "local"
    parse_status: str = ""
    parser_name: str = ""
    warnings: list[str] = Field(default_factory=list)
    document_role: str = ""
    document_version: str = ""
    baseline_id: str = ""
    source_system: str = ""
    external_document_id: str = ""
    included_in_formal_review: bool = True
    role_confirmed: bool = False
    role_confidence: float = 0.0
    role_reason: str = ""


class MaterialPackage(BaseModel):
    materials: list[MaterialItem] = Field(default_factory=list)
    uploaded_at: str | None = None


class ReviewBaseline(BaseModel):
    design_version: str = ""
    icd_version: str = ""
    requirements_version: str = ""
    simulation_version: str = ""
    verification_version: str = ""


class RequirementNode(BaseModel):
    requirement_id: str = ""
    external_req_id: str = ""
    title: str = ""
    text: str = ""
    requirement_level: str = ""
    parent_requirement_ids: list[str] = Field(default_factory=list)
    metric_id: str = ""
    metric_name: str = ""
    comparator: str = ""
    target_value: float | None = None
    unit: str = ""
    condition_tags: list[str] = Field(default_factory=list)
    source_file_name: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    source_quote: str = ""
    confidence: float = 0.0


class DesignImplementationItem(BaseModel):
    design_item_id: str = ""
    title: str = ""
    text: str = ""
    item_type: str = ""
    satisfies_requirement_ids: list[str] = Field(default_factory=list)
    metric_id: str = ""
    observed_value: float | None = None
    unit: str = ""
    source_file_name: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    source_quote: str = ""
    confidence: float = 0.0


class VerificationClaim(BaseModel):
    verification_id: str = ""
    title: str = ""
    method: str = ""
    verifies_requirement_ids: list[str] = Field(default_factory=list)
    verifies_design_item_ids: list[str] = Field(default_factory=list)
    status: str = ""
    pass_fail: str = ""
    metric_id: str = ""
    observed_value: float | None = None
    unit: str = ""
    source_file_name: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    source_quote: str = ""
    confidence: float = 0.0


class RequirementTraceLink(BaseModel):
    link_id: str = ""
    source_id: str = ""
    target_id: str = ""
    link_type: str = ""
    status: str = "candidate"
    confidence: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    source_quote: str = ""
    rationale: str = ""
    confirmed_by: str = ""
    confirmed_at: str = ""
    rejected_by: str = ""
    rejected_at: str = ""
    rejection_reason: str = ""


class CrossDocumentReviewItem(BaseModel):
    review_item_id: str = ""
    item_type: str = ""
    severity: str = "minor"
    title: str = ""
    description: str = ""
    impact: str = ""
    recommendation: str = ""
    source_artifact_ids: list[str] = Field(default_factory=list)
    target_artifact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_chain: list[dict[str, Any]] = Field(default_factory=list)
    evidence_chain_summary: str = ""
    source_quote: str = ""
    detection_method: str = "deterministic"
    status: str = "open"


class GatekeepingResult(BaseModel):
    review_id: str = ""
    gate_status: str = "blocked"
    gate_summary: str = ""
    can_start_review: bool = False
    blocking_reasons: list[str] = Field(default_factory=list)
    limited_scope: list[str] = Field(default_factory=list)
    missing_materials: list[str] = Field(default_factory=list)
    parsing_failed_materials: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    materials: list[dict[str, Any]] = Field(default_factory=list)
    checked_at: str = ""


class TraceabilityResult(BaseModel):
    review_id: str = ""
    gate_status: str = "blocked"
    gate_summary: str = ""
    blocking_reasons: list[str] = Field(default_factory=list)
    limited_scope: list[str] = Field(default_factory=list)
    missing_materials: list[str] = Field(default_factory=list)
    parsing_failed_materials: list[str] = Field(default_factory=list)
    formal_materials_cache: list[dict[str, Any]] = Field(default_factory=list)
    materials: list[dict[str, Any]] = Field(default_factory=list)
    requirements: list[RequirementNode] = Field(default_factory=list)
    design_items: list[DesignImplementationItem] = Field(default_factory=list)
    verification_claims: list[VerificationClaim] = Field(default_factory=list)
    trace_links: list[RequirementTraceLink] = Field(default_factory=list)
    object_registry: dict[str, Any] = Field(default_factory=dict)
    evidence_chains: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = Field(default_factory=list)
    review_items: list[CrossDocumentReviewItem] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ReviewTask(BaseModel):
    review_id: str = Field(default_factory=_gen_id)
    name: str = ""
    template_id: str = ""
    baseline: ReviewBaseline = Field(default_factory=ReviewBaseline)
    materials: MaterialPackage = Field(default_factory=MaterialPackage)


class ToolCallEvidence(BaseModel):
    tool_call_id: str = Field(default_factory=lambda: f"tool-{_gen_id()}")
    tool_name: str = ""
    tool_type: Literal[
        "calculation",
        "simulation",
        "retrieval",
        "standard_match",
        "database_query",
        "parameter_binding",
        "unknown",
    ] = "unknown"
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    status: str = ""
    error_message: str = ""
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class RuleExecutionResult(BaseModel):
    rule_id: str
    rule_desc: str = ""
    passed: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    reasoning: str = ""
    issues: list[str] = Field(default_factory=list)
    calculation: dict[str, Any] = Field(default_factory=dict)
    parameter_refs: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[ToolCallEvidence] = Field(default_factory=list)
    verification_method: str = ""
    rule_source_refs: list[dict[str, Any]] = Field(default_factory=list)
    execution_status: str = ""


class UnitEvidenceBundle(BaseModel):
    unit_key: str = ""
    primary_evidences: list[dict[str, Any]] = Field(default_factory=list)
    supporting_evidences: list[dict[str, Any]] = Field(default_factory=list)
    cross_section_evidences: list[dict[str, Any]] = Field(default_factory=list)
    extracted_parameters: list[dict[str, Any]] = Field(default_factory=list)
    extracted_objects: list[dict[str, Any]] = Field(default_factory=list)
    trace_link_candidates: list[dict[str, Any]] = Field(default_factory=list)
    trace_links: list[dict[str, Any]] = Field(default_factory=list)
    gatekeeping_status: str = "pass"
    warnings: list[str] = Field(default_factory=list)


class UnitFinding(BaseModel):
    finding_id: str = Field(default_factory=_gen_id)
    unit_key: str = ""
    rule_id: str = ""
    severity: str = "minor"
    description: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    recommendation: str = ""


class UnitReviewResult(BaseModel):
    unit_key: str = ""
    unit_name: str = ""
    agent_id: str = ""
    status: str = "completed"
    matched_section_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    rule_results: list[RuleExecutionResult] = Field(default_factory=list)
    findings: list[UnitFinding] = Field(default_factory=list)
    summary: str = ""
    is_blocked: bool = False
    knowledge_gap: bool = False
    confidence: float = 0.0
    rerun_downstream_units: list[str] = Field(default_factory=list)
    reviewed_at: str = ""
