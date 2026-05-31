import type { SuperAgentRun } from '@/features/super-agent/types'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'

/** 运行暂停时的 UI 上下文：决定子步骤展示「已中断 / 等待续跑 / 正在续跑」 */
export type SuperAgentRunPauseContext = 'active' | 'resuming' | 'interrupted' | 'failed' | 'stale'

export function resolveSuperAgentRunPauseContext(
  run: SuperAgentRun,
  options?: { resumeBusy?: boolean; isStaleRunning?: boolean },
): SuperAgentRunPauseContext {
  if (options?.resumeBusy) return 'resuming'
  if (run.status === 'interrupted') return 'interrupted'
  if (run.status === 'failed') return 'failed'
  if (run.status === 'running' && options?.isStaleRunning) return 'stale'
  return 'active'
}

/** running 状态下进度超过此时间未更新，视为 stale（后端 worker 可能已中断） */
export const STALE_RUNNING_MS = 90_000

/** Review-Plus 委托步骤可能 30+ 分钟无 Super Agent checkpoint */
export const LONG_RUNNING_STALE_MS = 45 * 60 * 1000

const EMPTY_STRUCTURED_BUNDLE = {
  materials: [],
  parser_traces: [],
  section_tree: {},
  evidence_pool: {},
  document_ir: {},
  chunks: [],
  check_items: [],
  extracted_parameters: [],
  extracted_objects: [],
  trace_link_candidates: [],
  stats: {},
  warnings: [],
  parser_fallback_logs: [],
  self_healing_records: [],
}

const EMPTY_TRACE_REPORT = {
  parser_traces: [],
  agent_run_traces: [],
  workflow_events: [],
  fallback_events: [],
  failed_steps: [],
  degradation_summary: [],
}

const EMPTY_QUALITY_REPORT = {
  parse_quality_score: 0,
  evidence_quality_score: 0,
  traceability_score: 0,
  consistency_score: 0,
  stability_score: 0,
  overall_score: 0,
  expert_consensus_score: 0,
  evidence_sufficiency_score: 0,
  conflict_detection_score: 0,
  warnings: [],
  human_confirmation_required: false,
}

const EMPTY_EXECUTION_METRICS_SNAPSHOT = {
  execution_pass: false,
  capability_pass: false,
  degradation_rate: 0,
  parse_artifact_summary: {
    file_count: 0,
    parsed_count: 0,
    degraded_count: 0,
    failed_count: 0,
    execution_pass_rate: 0,
    capability_pass_rate: 0,
    degradation_rate: 0,
  },
  quality_scores: {
    parse_quality_score: 0,
    evidence_quality_score: 0,
    traceability_score: 0,
    consistency_score: 0,
    stability_score: 0,
    overall_score: 0,
  },
}

/** API 不可用时保留 runId，便于 ProcessingView 展示续跑入口 */
export function buildFallbackSuperAgentRun(runId: string, error = ''): SuperAgentRun {
  const now = new Date().toISOString()
  return {
    run_id: runId,
    name: '审查任务',
    objective: '',
    processing_mode: 'OPTIMAL',
    input_mode: 'upload',
    source_review_id: '',
    requested_route: 'auto',
    review_mode: 'full',
    materials: [],
    route_decision: null,
    structured_bundle: EMPTY_STRUCTURED_BUNDLE,
    review_plus_result: {},
    gnc_review_result: {},
    trace_report: EMPTY_TRACE_REPORT,
    quality_report: EMPTY_QUALITY_REPORT,
    execution_metrics_snapshot: EMPTY_EXECUTION_METRICS_SNAPSHOT,
    skill_traces: [],
    status: 'interrupted',
    error: error || '无法连接后端，请稍后重试或继续执行',
    created_at: now,
    updated_at: now,
  }
}

export function getSuperAgentRunLastActivityMs(
  run: SuperAgentRun,
  reviewPlusTask?: ReviewPlusTaskDetail | null,
): number {
  let lastMs = Date.now()
  const updatedMs = Date.parse(run.updated_at)
  if (!Number.isNaN(updatedMs)) lastMs = updatedMs
  else {
    const createdMs = Date.parse(run.created_at)
    if (!Number.isNaN(createdMs)) lastMs = createdMs
  }
  if (reviewPlusTask?.updated_at) {
    const rpMs = Date.parse(reviewPlusTask.updated_at)
    if (!Number.isNaN(rpMs)) lastMs = Math.max(lastMs, rpMs)
  }
  return lastMs
}

export function isSuperAgentRunStale(
  run: SuperAgentRun,
  nowMs = Date.now(),
  thresholdMs = STALE_RUNNING_MS,
  reviewPlusTask?: ReviewPlusTaskDetail | null,
): boolean {
  if (run.status !== 'running') return false
  const lastRunningSkill = [...(run.skill_traces || [])].reverse().find((trace) => trace.status === 'running')
  const longRunningSkillIds = new Set(['run_review_plus', 'bootstrap_review_plus_task', 'structure_materials'])
  const effectiveThreshold = lastRunningSkill && longRunningSkillIds.has(lastRunningSkill.skill_id)
    ? LONG_RUNNING_STALE_MS
    : thresholdMs
  const lastActivityMs = getSuperAgentRunLastActivityMs(run, reviewPlusTask)
  if (reviewPlusTask && reviewPlusTask.status === 'running') {
    return nowMs - lastActivityMs >= LONG_RUNNING_STALE_MS
  }
  return nowMs - lastActivityMs >= effectiveThreshold
}
