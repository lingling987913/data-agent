export type UnifiedReviewType = 'gnc' | 'review_plus' | 'super_agent'

export type UnifiedWorkbenchPhase =
  | 'pre_review'
  | 'startup'
  | 'executing'
  | 'arbitration'
  | 'completed'
  | 'failed'

export type UnifiedWorkbenchTabKey =
  | 'overview'
  | 'materials'
  | 'routes'
  | 'findings'
  | 'closure'
  | 'quality'
  | 'flow'
  | 'check_items'
  | 'coverage'
  | 'traceability'
  | 'cross_doc'
  | 'report'
  | 'events'
  | 'rid'
  | 'minutes'
  | 'decision'
  | 'committee'
  | 'evidences'
  | 'arbitration'

export interface UnifiedWorkbenchMetrics {
  finding_count: number
  problem_count?: number
  check_item_count?: number
  pending_confirm?: number
  rid_count: number
  open_rid_count: number
  evidence_count: number
  conflict_count: number
  requires_arbitration: boolean
  material_count?: number
}

export interface UnifiedWorkbenchSummary {
  verdict: string
  verdict_label_zh?: string
  rationale: string
  rationale_zh?: string
  requires_arbitration: boolean
  arbitration_status: string
  report_available: boolean
  headline_verdict?: string
  one_line_conclusion?: string
  review_mode_label?: string
}

export interface WorkbenchConclusionOverview {
  headline_verdict: string
  headline_zh?: string
  one_line_conclusion: string
  verdict_label_zh?: string
  rationale_zh?: string
  material_insufficiency?: boolean
  issue_buckets: Record<string, number>
  bucket_labels: Record<string, string>
  review_scope: Record<string, unknown>
  priority_items: Array<Record<string, unknown>>
  coverage_summary: Record<string, unknown>
}

export interface UnifiedReviewWorkbenchDetail {
  review_id: string
  name: string
  review_type: UnifiedReviewType
  status: string
  workbench_phase: UnifiedWorkbenchPhase
  visible_tabs: string[]
  current_step: string
  metrics: UnifiedWorkbenchMetrics
  summary: UnifiedWorkbenchSummary
  conclusion_overview?: WorkbenchConclusionOverview | null
  error: string
  created_at: string
  updated_at: string
}
