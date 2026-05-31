/**
 * 文件组审查 — 前端类型（对齐 review_plus_schemas.py）
 */

import { GATEKEEPING_TERMS } from '@/lib/aeroTerminology'

export type ReviewPlusStatus =
  | 'draft'
  | 'materials_uploaded'
  | 'parsing'
  | 'parsed'
  | 'classifying'
  | 'classified'
  | 'scenario_detected'
  | 'gatekeeping'
  | 'traceability_building'
  | 'structuring'
  | 'rule_extracting'
  | 'ready'
  | 'blocked'
  | 'limited_pass'
  | 'mapping'
  | 'reviewing'
  | 'reporting'
  | 'completed'
  | 'failed'

export type ReviewPlusMaterialRole =
  | 'review_rule'
  | 'checklist'
  | 'task_book'
  | 'subject_report'
  | 'subject_document'
  | 'supporting_attachment'
  | 'unknown'

export type ReviewPlusParserType =
  | 'auto'
  | 'local'
  | 'mineru'
  | 'mineru_agent'
  | 'mineru_via_pdf'
  | 'ragflow'

export type ReviewPlusJudgment =
  | 'satisfied'
  | 'not_satisfied'
  | 'insufficient_evidence'
  | 'not_applicable'
  | 'not_checked'

export type ReviewPlusFindingSeverity = 'critical' | 'major' | 'minor' | 'info'

export interface ReviewPlusMaterialItem {
  name: string
  file_type: string
  content?: string
  file_path?: string
  parser_type?: string
  parser_name?: string
  warnings?: string[]
  parse_status?: string
  role: ReviewPlusMaterialRole | string
  role_confidence?: number
  role_reason?: string
  document_version?: string
  baseline_id?: string
  included_in_formal_review?: boolean
  role_confirmed?: boolean
  parser_trace?: Array<Record<string, unknown>>
}

export interface ReviewPlusCheckItem {
  check_item_id: string
  item_no?: string
  title?: string
  requirement_text?: string
  acceptance_criteria?: string
  applicable_scope?: string
  severity?: string
  source_material_name?: string
  source_sheet?: string
  source_row?: number | null
  source_quote?: string
  confidence?: number
}

export interface ReviewPlusFinding {
  finding_id: string
  check_item_id: string
  judgment: ReviewPlusJudgment | string
  severity: ReviewPlusFindingSeverity | string
  title?: string
  reasoning?: string
  evidence_refs?: string[]
  source_quotes?: string[]
  recommendation?: string
  confidence?: number
  section_ids?: string[]
  source_quote?: string
  checklist_source_role?: string
  checklist_source_material_name?: string
  task_book_evidence_refs?: string[]
  subject_evidence_refs?: string[]
  coverage_status?: string
  requires_human_confirmation?: boolean
}

export interface ReviewPlusReport {
  report_id: string
  total_check_items: number
  satisfied_count: number
  not_satisfied_count: number
  insufficient_evidence_count: number
  not_checked_count: number
  critical_count: number
  conclusion?: string
  summary?: string
  residual_risks?: string[]
  markdown?: string
  cross_document_items?: Array<Record<string, unknown>>
  chief_comprehensive_review?: ReviewPlusChiefComprehensiveReview | null
}

export interface ReviewPlusChiefEngineeringConclusion {
  conclusion_id?: string
  title?: string
  description?: string
  evidence_sources?: string[]
  involved_documents?: string[]
  risk_impact?: string
  recommendation?: string
  severity?: ReviewPlusFindingSeverity | string
  confidence?: number
}

export interface ReviewPlusChiefComprehensiveReview {
  status?: 'ok' | 'degraded' | 'unavailable' | string
  method?: string
  overall_assessment?: string
  release_recommendation?: string
  engineering_conclusions?: ReviewPlusChiefEngineeringConclusion[]
  key_risks?: string[]
  rationale?: string
  degraded?: boolean
  degrade_reason?: string
}

export interface ReviewPlusGatekeepingResult {
  review_id?: string
  gate_status: 'blocked' | 'limited' | 'passed' | string
  gate_summary?: string
  can_start_review?: boolean
  blocking_reasons?: string[]
  limited_scope?: string[]
  missing_materials?: string[]
  warnings?: string[]
}

export interface ReviewPlusEvent {
  sequence?: number
  type: string
  payload?: Record<string, unknown>
  created_at?: string
}

export interface ReviewPlusDocumentFormatReview {
  agent_id?: string
  agent_name?: string
  gate_status?: string
  material_results?: Array<Record<string, unknown>>
  findings?: Array<Record<string, unknown>>
  summary?: Record<string, unknown>
}

export interface ReviewPlusHarnessPlan {
  team_id?: string
  selected_agent_ids?: string[]
  required_agent_ids?: string[]
  selection_reasons?: Record<string, string>
  material_roles?: string[]
  matched_signals?: Record<string, string[]>
}

export interface ReviewPlusAgentRunTrace {
  agent_id: string
  status?: 'completed' | 'failed' | string
  elapsed_ms?: number
  error_code?: string
  error_message?: string
  input_summary?: Record<string, unknown>
  output_summary?: Record<string, unknown>
}

export type ReviewPlusCoverageStatus = 'closed' | 'task_only' | 'subject_only' | 'missing'

export interface ReviewPlusCoverageMatrixRow {
  check_item_id?: string
  check_item_title?: string
  checklist_source_role?: string
  checklist_source_material_name?: string
  task_book_evidence_refs?: string[]
  subject_evidence_refs?: string[]
  judgment?: ReviewPlusJudgment | string
  coverage_status?: ReviewPlusCoverageStatus | string
  confidence?: number
  risks?: string[]
  source_quote?: string
  requires_human_confirmation?: boolean
}

export interface ReviewPlusCoverageMatrixSummary {
  row_count?: number
  closed_count?: number
  task_only_count?: number
  subject_only_count?: number
  missing_count?: number
  ruleset_version?: string
}

export interface ReviewPlusCoverageMatrix {
  rows?: ReviewPlusCoverageMatrixRow[]
  summary?: ReviewPlusCoverageMatrixSummary
}

export interface ReviewPlusChiefReviewPlan {
  chief_agent_id?: string
  chief_agent_name?: string
  scenario?: string
  selected_agents?: Array<Record<string, unknown>>
  focus_questions?: string[]
  coordination_policy?: Record<string, unknown>
  summary?: Record<string, unknown>
  harness_plan?: ReviewPlusHarnessPlan
}

export interface ReviewPlusSpecialistReview {
  agent_id?: string
  agent_name?: string
  role?: string
  status?: string
  assignment_reason?: string
  finding_count?: number
  findings?: Array<Record<string, unknown>>
}

export interface ReviewPlusTaskSummary {
  review_plus_id: string
  name: string
  status: ReviewPlusStatus | string
  scenario?: string
  material_count?: number
  check_item_count?: number
  created_at: string
  updated_at: string
}

export interface ReviewPlusTaskDetail {
  review_plus_id: string
  name: string
  status: ReviewPlusStatus | string
  scenario?: string
  scenario_confidence?: number
  scenario_reason?: string
  materials: ReviewPlusMaterialItem[]
  check_items: ReviewPlusCheckItem[]
  section_mappings?: Array<Record<string, unknown>>
  findings: ReviewPlusFinding[]
  report?: ReviewPlusReport | null
  report_markdown?: string
  report_file_path?: string
  gatekeeping_result?: ReviewPlusGatekeepingResult
  parse_artifact?: Record<string, unknown>
  document_ir?: Record<string, unknown>
  document_format_review?: ReviewPlusDocumentFormatReview
  chief_review_plan?: ReviewPlusChiefReviewPlan
  specialist_reviews?: ReviewPlusSpecialistReview[]
  traceability_result?: Record<string, unknown>
  cross_document_review_items?: Array<Record<string, unknown>>
  coverage_matrix?: ReviewPlusCoverageMatrix
  agent_run_traces?: ReviewPlusAgentRunTrace[]
  events?: ReviewPlusEvent[]
  created_at: string
  updated_at: string
}

export const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  materials_uploaded: '材料已上传',
  parsing: '解析中',
  parsed: '已解析',
  classifying: '分类中',
  classified: '已分类',
  scenario_detected: '场景已识别',
  gatekeeping: GATEKEEPING_TERMS.check,
  traceability_building: '追溯构建中',
  structuring: '结构化中',
  rule_extracting: '规则抽取中',
  ready: '可审查',
  blocked: '已阻断',
  limited_pass: GATEKEEPING_TERMS.limitedPass,
  mapping: '证据映射中',
  reviewing: '符合性审查中',
  reporting: '报告生成中',
  completed: '已完成',
  failed: '失败',
}

export const MATERIAL_ROLE_LABELS: Record<string, string> = {
  review_rule: '审查规则',
  checklist: '检查单',
  task_book: '任务书',
  subject_report: '被审报告',
  subject_document: '待审文档',
  supporting_attachment: '支撑附件',
  unknown: '未识别',
}

export const JUDGMENT_LABELS: Record<string, string> = {
  satisfied: '满足',
  not_satisfied: '不满足',
  insufficient_evidence: '证据不足',
  not_applicable: '不适用',
  not_checked: '未检查',
  compliant: '符合',
  non_compliant: '不符合',
}

export const SEVERITY_LABELS: Record<string, string> = {
  critical: '重大问题',
  major: '主要问题',
  minor: '一般问题',
  suggestion: '建议项',
  info: '建议项',
  pending_expert: '待专家确认',
}

export const COVERAGE_STATUS_LABELS: Record<string, string> = {
  closed: '已闭合',
  task_only: '仅任务书',
  subject_only: '仅被审材料',
  missing: '缺失',
}

export const HARNESS_AGENT_ID_LABELS: Record<string, string> = {
  material_package_agent: '送审包校验',
  chief_orchestrator_agent: '组队编排',
  coverage_matrix_builder_agent: '覆盖矩阵构建',
  review_plus_arbiter_agent: '审查裁决',
  checklist_agent: '检查单审查',
  task_book_agent: '任务书审查',
  subject_report_agent: '被审报告审查',
  product_assurance_agent: '产品保证审查',
  reliability_safety_agent: '可靠性安全性审查',
  gnc_design_agent: 'GNC 设计审查',
  interface_agent: '接口审查',
  verification_agent: '验证审查',
  cross_document_consistency_agent: '跨文档一致性审查',
}
