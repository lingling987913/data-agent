import type { ReviewEvent, ReviewSessionSnapshot, ReviewSessionStatus } from '@/features/review-plus-v2/sessionTypes'
import { REVIEW_PLUS_TERMS } from '@/lib/aeroTerminology'
import type { ReviewPlusEvent, ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { buildReviewPlusWorkflowGraph, resolveActiveWorkflowStepKey } from '@/features/review-plus-v2/utils/reviewPlusWorkflowGraph'
import {
  formatReviewPlusEventLabel,
  inferReviewPlusStepKeyFromEvent,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { formatEventPayloadSummary } from '@/features/review-plus-v2/utils/reviewPlusStepDetail'

const RUNNING_STATUSES = new Set([
  'parsing', 'classifying', 'structuring', 'rule_extracting', 'mapping',
  'reviewing', 'traceability_building', 'reporting', 'gatekeeping',
])

function resolveSessionStatus(status: string): ReviewSessionStatus {
  if (status === 'completed') return 'completed'
  if (status === 'failed') return 'failed'
  if (RUNNING_STATUSES.has(status)) return 'running'
  return 'idle'
}

export function inferReviewPlusEventStepKey(eventType: string): string {
  return inferReviewPlusStepKeyFromEvent(eventType)
}

export function adaptReviewPlusEvents(task: ReviewPlusTaskDetail): ReviewEvent[] {
  const reviewId = task.review_plus_id
  const sessionStatus = resolveSessionStatus(String(task.status))

  return (task.events || []).map((event, index) => adaptSingleEvent(event, reviewId, sessionStatus, index))
}

function adaptSingleEvent(
  event: ReviewPlusEvent,
  reviewId: string,
  sessionStatus: ReviewSessionStatus,
  index: number,
): ReviewEvent {
  const eventType = String(event.type || '')
  const stepKey = inferReviewPlusStepKeyFromEvent(eventType)
  const payload = (event.payload || {}) as Record<string, unknown>
  const summary = formatEventPayloadSummary(eventType, payload)

  return {
    event_id: `rp-${reviewId}-${event.sequence ?? index}`,
    review_id: reviewId,
    sequence: event.sequence ?? index + 1,
    event_type: eventType,
    emitted_at: event.created_at || '',
    session_status: sessionStatus,
    step_key: stepKey,
    node_id: stepKey ? `node_${stepKey}` : '',
    agent_id: '',
    agent_run_id: '',
    correlation_id: '',
    title: formatReviewPlusEventLabel(eventType),
    summary,
    status: String(payload.status || ''),
    severity: eventType.includes('failed') || eventType.includes('blocked') ? 'error' : 'info',
    payload,
    audit: { visibility: 'public', cot_exposed: false },
  }
}

export function buildReviewPlusSessionSnapshot(task: ReviewPlusTaskDetail): ReviewSessionSnapshot {
  const graph = buildReviewPlusWorkflowGraph(task)
  const currentStepKey =
    resolveActiveWorkflowStepKey(task)
    || graph.nodes.find((node) => node.status === 'running')?.step_key
    || graph.nodes.find((node) => node.status === 'failed')?.step_key
    || ''

  const events = adaptReviewPlusEvents(task)

  return {
    review_id: task.review_plus_id,
    session_status: resolveSessionStatus(String(task.status)),
    title: task.name,
    aircraft_model: task.scenario || '—',
    review_stage: REVIEW_PLUS_TERMS.moduleLabel,
    current_step_key: currentStepKey,
    current_node_id: currentStepKey ? `node_${currentStepKey}` : '',
    current_agent_run_id: '',
    metrics: {
      finding_count: task.findings?.length || 0,
      issue_count: task.cross_document_review_items?.length || 0,
      rule_count: task.check_items?.length || 0,
      rid_count: 0,
      pending_hitl_count: 0,
    },
    graph,
    events,
    page_info: {
      last_sequence: events.length > 0 ? events[events.length - 1]!.sequence : 0,
      has_more: false,
      has_more_history: false,
    },
    agent_details: {},
  }
}
