import type { WorkflowGraph } from '@aqua/workflow-core'

export type ReviewSessionStatus = 'idle' | 'running' | 'blocked' | 'awaiting_confirm' | 'completed' | 'failed'
export type ReviewEventSeverity = 'info' | 'warning' | 'error'

export interface ReviewEventAudit {
  visibility: string
  cot_exposed: boolean
}

export interface ReviewEvent {
  event_id: string
  review_id: string
  sequence: number
  event_type: string
  emitted_at: string
  session_status: ReviewSessionStatus
  step_key: string
  node_id: string
  agent_id: string
  agent_run_id: string
  correlation_id: string
  title: string
  summary: string
  status: string
  severity: ReviewEventSeverity
  payload: Record<string, unknown>
  audit: ReviewEventAudit
}

export interface ReviewEventPageInfo {
  last_sequence: number
  has_more: boolean
  has_more_history: boolean
}

export interface ReviewSessionMetrics {
  finding_count: number
  issue_count: number
  rule_count: number
  rid_count: number
  pending_hitl_count: number
}

export interface ReviewSessionSnapshot {
  review_id: string
  session_status: ReviewSessionStatus
  title: string
  aircraft_model: string
  review_stage: string
  current_step_key: string
  current_node_id: string
  current_agent_run_id: string
  metrics: ReviewSessionMetrics
  graph: WorkflowGraph
  events: ReviewEvent[]
  page_info: ReviewEventPageInfo
  agent_details?: Record<string, unknown>
}
