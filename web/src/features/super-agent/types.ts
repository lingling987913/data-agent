export type SuperAgentStatus = 'draft' | 'running' | 'interrupted' | 'completed' | 'failed' | 'limited'

export type SuperAgentWizardStep = 1 | 2 | 3 | 4 | 5

export type SuperAgentRoute = 'auto' | 'review_plus' | 'gnc_review' | 'gnc_review_only' | 'structure_only' | 'hybrid' | 'smart'

export type SuperAgentReviewMode = 'single_doc' | 'multi_doc' | 'full'

export interface SuperAgentCapabilities {
  team_id: string
  display_name: string
  routes: string[]
  skills: Array<{
    id: string
    name: string
    description: string
  }>
  reused_components: string[]
}

export interface ParsePlanFile {
  file_name: string
  role: string
  parsing_tier: string
  parser_type: string
  processing_mode: string
}

export interface ParsePlan {
  default_processing_mode: string
  default_parser_type: string
  files: ParsePlanFile[]
  source?: string
}

export interface ReviewPlan {
  route: string
  recommended_route: string
  review_mode_selection: 'smart' | 'standard' | 'specialized' | string
  required_tools: string[]
  skipped_tools: string[]
  bootstrap_review_plus: boolean
  run_structure_parse: boolean
  reuse_review_plus_parse: boolean
  confidence: number
  reasons: string[]
  downgrade_reasons: string[]
  slot_status?: {
    slot_completeness?: Record<string, boolean>
    missing_slots?: string[]
    review_plus_ready?: boolean
  }
  review_plus_ready: boolean
  gnc_review_id?: string
}

export type ReviewModeSelection = 'smart' | 'standard' | 'specialized'

export type AdaptiveRouterSource = 'baseline' | 'llm' | 'error'

export interface AdaptiveRouterPayload {
  source: AdaptiveRouterSource
  domain_id: string
  route: string
  primary_path?: string
  confidence?: number
  reasoning_summary?: string
  selected_capabilities?: {
    primary_path?: string
    specialist_ids?: string[]
  }
  task_specs?: Array<Record<string, unknown>>
  guardrail_corrections?: string[]
  risk_flags?: string[]
  missing_info?: string[]
}

export interface MaterialClassification {
  doc_type: string
  domain: string
  recommended_route: string
  reason: string
  confidence?: number
  initial_recommended_route?: string
  final_recommended_route?: string
  route_decision_source?: string
  post_parse_route?: {
    source?: string
    suggested_route?: string
    effective_route?: string
    confidence?: number
    reasons?: string[]
    changed_from_initial?: boolean
    initial_route?: string
    user_override_active?: boolean
    parse_incomplete?: boolean
  }
  post_parse_reason?: string
  material_roles?: Array<{
    file_name: string
    role: string
    confidence?: number
    reason?: string
    recommended_parsing_tier?: string
    recommended_parser_type?: string
    recommended_processing_mode?: string
  }>
  slot_completeness?: Record<string, boolean>
  missing_slots?: string[]
  review_plus_ready?: boolean
  parse_plan?: ParsePlan
  review_plan?: ReviewPlan
  review_mode_selection?: ReviewModeSelection
  smart_task_board?: Record<string, unknown>
  smart_task_board_summary?: {
    task_count?: number
    completed?: number
    failed?: number
    blocked?: number
    limited?: number
    execution_mode_counts?: Record<string, number>
  }
  bootstrap_summary?: {
    bootstrap_mode?: string
    synthetic_check_item_count?: number
    source_evidence_ref_count?: number
    synthetic_context_label?: string
  }
  domain_id?: string
  adaptive_router?: AdaptiveRouterPayload
  user_overrides?: {
    domain_id?: string
    route?: string
    recommended_route?: string
    review_mode_selection?: ReviewModeSelection
  }
}

export interface StructurePreviewSummary {
  section_count: number
  evidence_count: number
  top_sections?: Array<{ section_id?: string; title: string; level: number }>
  structure_ready?: boolean
}

export interface ParsePreviewBlock {
  id: string
  block_type: string
  content: string
  markdown?: string
  original_content?: string
  original_markdown?: string
  page_hint?: number | null
  bbox?: number[] | null
  level?: number | null
  angle?: number | null
  formula_latex?: string | null
  caption?: string | null
  image_description?: string | null
  image_url?: string | null
  calibrated?: boolean
  needs_calibration_review?: boolean
  calibration_records?: ParseCalibrationRecord[]
}

export interface ParseCalibrationRecord {
  block_id: string
  page_hint?: number | null
  issue_type?: string
  severity?: 'info' | 'warning' | 'critical' | string
  original_text?: string
  suggested_text?: string
  reason?: string
  evidence?: string[]
  confidence?: number
  status?: 'needs_review' | 'suggested' | 'dismissed' | string
}

export interface MaterialParsePreviewItem {
  file_name: string
  role: string
  role_confidence: number
  role_reason: string
  parsing_tier: string
  parser_type: string
  processing_mode: string
  parse_status: string
  parser_name: string
  content_preview: string
  content_markdown?: string
  content_markdown_truncated?: boolean
  content_length: number
  line_count: number
  source_file_type?: string
  page_count?: number
  blocks?: ParsePreviewBlock[]
  parse_artifact_subset?: Record<string, unknown>
  source_download_url?: string
  file_id?: string
  upload_id?: string
  warnings: string[]
  parser_trace: Array<Record<string, unknown>>
  capability_passed?: boolean
  degraded?: boolean
  document_ir_stats?: Record<string, number>
}

export interface ParsePreviewResponse {
  parse_artifact?: Record<string, unknown>
  document_ir?: Record<string, unknown>
  batch_summary?: Record<string, unknown>
  classification: MaterialClassification
  materials: MaterialParsePreviewItem[]
  summary: {
    material_count: number
    parsed_ok: number
    degraded_count: number
  }
  structure_summary?: StructurePreviewSummary
  section_tree?: Record<string, unknown>
  evidence_pool?: Record<string, unknown>
}

export interface SuperAgentRouteDecision {
  route: SuperAgentRoute
  confidence: number
  reasons: string[]
  required_tools: string[]
  skipped_tools: string[]
  gnc_review_id: string
  classification?: MaterialClassification
}

export interface SuperAgentSkillTrace {
  skill_id: string
  agent_id: string
  tool_name: string
  status: string
  input_summary: Record<string, unknown>
  output_summary: Record<string, unknown>
  warnings: string[]
  elapsed_ms: number
}

export interface SuperAgentTraceReport {
  parser_traces: Array<Record<string, unknown>>
  agent_run_traces: Array<Record<string, unknown>>
  workflow_events: Array<Record<string, unknown>>
  fallback_events: Array<Record<string, unknown>>
  failed_steps: Array<Record<string, unknown>>
  degradation_summary: string[]
}

export interface SuperAgentQualityReport {
  parse_quality_score: number
  evidence_quality_score: number
  traceability_score: number
  consistency_score: number
  stability_score: number
  overall_score: number
  expert_consensus_score: number
  evidence_sufficiency_score: number
  conflict_detection_score: number
  warnings: string[]
  human_confirmation_required: boolean
}

export interface ExecutionMetricsSnapshot {
  execution_pass: boolean
  capability_pass: boolean
  degradation_rate: number
  parse_artifact_summary: {
    file_count: number
    parsed_count: number
    degraded_count: number
    failed_count: number
    execution_pass_rate: number
    capability_pass_rate: number
    degradation_rate: number
  }
  quality_scores: {
    parse_quality_score: number
    evidence_quality_score: number
    traceability_score: number
    consistency_score: number
    stability_score: number
    overall_score: number
  }
}

export interface SuperAgentStructuredBundle {
  materials: Array<Record<string, unknown>>
  parser_traces: Array<Record<string, unknown>>
  section_tree: Record<string, unknown>
  evidence_pool: Record<string, unknown>
  document_ir?: Record<string, unknown>
  parse_artifact?: Record<string, unknown>
  chunks: Array<Record<string, unknown>>
  check_items: Array<Record<string, unknown>>
  extracted_parameters?: Array<Record<string, unknown>>
  extracted_objects?: Array<Record<string, unknown>>
  trace_link_candidates?: Array<Record<string, unknown>>
  stats: Record<string, unknown>
  warnings: string[]
  parser_fallback_logs?: Array<Record<string, unknown>>
  self_healing_records?: Array<Record<string, unknown>>
}

export interface SuperAgentRun {
  run_id: string
  name: string
  objective: string
  processing_mode: string
  input_mode: 'upload' | 'existing_review_plus' | 'existing_gnc_review'
  source_review_id: string
  requested_route: SuperAgentRoute
  review_mode: SuperAgentReviewMode
  materials: SuperAgentMaterialInput[]
  route_decision: SuperAgentRouteDecision | null
  classification?: MaterialClassification
  structured_bundle: SuperAgentStructuredBundle
  review_plus_result: Record<string, unknown>
  gnc_review_result: Record<string, unknown>
  report_markdown?: string
  report_artifact?: Record<string, unknown>
  trace_report: SuperAgentTraceReport
  quality_report: SuperAgentQualityReport
  execution_metrics_snapshot?: ExecutionMetricsSnapshot
  skill_traces: SuperAgentSkillTrace[]
  completed_steps?: string[]
  current_phase?: string
  phase_status?: string
  phase_artifacts?: Record<string, Record<string, unknown>>
  wizard_step?: number
  parse_preview?: ParsePreviewResponse | Record<string, unknown>
  status: SuperAgentStatus
  error: string
  created_at: string
  updated_at: string
}

export interface SuperAgentMaterialInput {
  name: string
  file_type?: string
  content?: string
  /** Legacy small-payload path only. Browser uploads should use file_path. */
  content_base64?: string
  content_preview?: string
  file_path?: string
  upload_id?: string
  file_id?: string
  file_size?: number
  parser_type?: string
  role?: string
}

export interface SuperAgentUploadResponse {
  upload_id: string
  materials: SuperAgentMaterialInput[]
  skipped: Array<{ file_name: string; reason: string }>
}

export interface SuperAgentReviewRunInput {
  review_mode?: SuperAgentReviewMode
  requested_route?: SuperAgentRoute
  objective?: string
  skip_reparse?: boolean
  force_rerun?: boolean
}

export interface CreateSuperAgentRunInput {
  name: string
  objective: string
  processing_mode: string
  input_mode: 'upload' | 'existing_review_plus' | 'existing_gnc_review'
  source_review_id: string
  requested_route: SuperAgentRoute
  review_mode: SuperAgentReviewMode
  execute: boolean
  materials?: SuperAgentMaterialInput[]
  classification?: MaterialClassification | Record<string, unknown>
}

export interface SaveWizardCheckpointInput {
  wizard_step?: SuperAgentWizardStep
  materials?: SuperAgentMaterialInput[]
  classification?: MaterialClassification | Record<string, unknown>
  parse_preview?: ParsePreviewResponse | Record<string, unknown>
  processing_mode?: string
  requested_route?: SuperAgentRoute
  review_mode_selection?: ReviewModeSelection
  objective?: string
}

export interface SuperAgentBenchmarkReport {
  case_count: number
  passed_count: number
  failed_count: number
  pass_rate: number
  results: Array<Record<string, unknown>>
}

export interface SuperAgentGncStatus {
  run_id: string
  review_mode: SuperAgentReviewMode
  gnc_review_id: string
  status: string
  reason: string
}
