import type { MaterialClassification, SuperAgentRun } from '@/features/super-agent/types'
import { filterBusinessLines } from '@/features/super-agent/utils/diagnosticsSanitizer'

export {
  filterBusinessFindings,
  filterBusinessLines,
  isInternalDiagnosticText,
  isSmartInternalDiagnostic,
  sanitizeBusinessMarkdown,
  sanitizeBusinessReportText,
  sanitizeSmartDiagnosticText,
} from '@/features/super-agent/utils/diagnosticsSanitizer'

export interface SmartCommitteeExecutionModeSummary {
  harness_count?: number
  generic_llm_harness_count?: number
  deterministic_count?: number
  failed_count?: number
  blocked_count?: number
}

export interface SmartCommitteeTaskBoardSummary {
  task_count?: number
  completed?: number
  failed?: number
  blocked?: number
  skipped?: number
  limited?: number
  execution_mode_counts?: Record<string, number>
  status_counts?: Record<string, number>
}

export interface SmartCommitteeBootstrapSummary {
  bootstrap_mode?: string
  synthetic_check_item_count?: number
  source_evidence_ref_count?: number
  synthetic_context_label?: string
}

export interface SmartCommitteeDiagnostics {
  visible: boolean
  limited: boolean
  executionModeLabel: string
  executionModeSummary?: SmartCommitteeExecutionModeSummary
  executionModeSummaryLines: string[]
  taskBoardSummary?: SmartCommitteeTaskBoardSummary
  bootstrapSummary?: SmartCommitteeBootstrapSummary
  taskSpecCount?: number
  domainId?: string
  routeSignalHits?: string[]
  specialistModes: Array<{
    agentId: string
    title: string
    executionMode: string
    fallbackReason?: string
  }>
  citationCoverage?: number
  citationCoverageSource?: string
  degradationNotes: string[]
  fallbackReasons: string[]
  skippedCount?: number
  hasArbiterSummary?: boolean
  arbiterConsensusSummary?: string
  replanSuggestions: string[]
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

function readExecutionModeSummary(run: SuperAgentRun): SmartCommitteeExecutionModeSummary | undefined {
  const review = asRecord(run.review_plus_result)
  const fromReview = asRecord(review.execution_mode_summary)
  if (Object.keys(fromReview).length) {
    return {
      harness_count: Number(fromReview.harness_count || 0),
      generic_llm_harness_count: Number(fromReview.generic_llm_harness_count || 0),
      deterministic_count: Number(fromReview.deterministic_count || 0),
      failed_count: Number(fromReview.failed_count || 0),
      blocked_count: Number(fromReview.blocked_count || 0),
    }
  }
  return undefined
}

function readTaskBoardSummary(
  run: SuperAgentRun,
  classification?: MaterialClassification,
): SmartCommitteeTaskBoardSummary | undefined {
  const review = asRecord(run.review_plus_result)
  const fromReview = asRecord(review.task_board_summary)
  if (Object.keys(fromReview).length) {
    return {
      task_count: Number(fromReview.task_count || 0),
      completed: Number(fromReview.completed || 0),
      failed: Number(fromReview.failed || 0),
      blocked: Number(fromReview.blocked || 0),
      skipped: Number(fromReview.skipped || (asRecord(fromReview.status_counts).skipped as number) || 0),
      limited: Number(fromReview.limited || 0),
      execution_mode_counts: asRecord(fromReview.execution_mode_counts) as Record<string, number>,
      status_counts: asRecord(fromReview.status_counts) as Record<string, number>,
    }
  }

  const fromClassification = asRecord(classification?.smart_task_board_summary)
  if (Object.keys(fromClassification).length) {
    return {
      task_count: Number(fromClassification.task_count || 0),
      completed: Number(fromClassification.completed || 0),
      failed: Number(fromClassification.failed || 0),
      blocked: Number(fromClassification.blocked || 0),
      limited: Number(fromClassification.limited || 0),
      execution_mode_counts: asRecord(fromClassification.execution_mode_counts) as Record<string, number>,
    }
  }

  const boardFromClassification = asRecord(classification?.smart_task_board)
  const tasks = asArray<Record<string, unknown>>(boardFromClassification.tasks)
  if (tasks.length) {
    const statusCounts: Record<string, number> = {}
    let limited = 0
    const executionModeCounts: Record<string, number> = {}
    for (const task of tasks) {
      const status = String(task.status || 'unknown')
      statusCounts[status] = (statusCounts[status] || 0) + 1
      const output = asRecord(task.output_summary)
      const nested = asRecord(output.review)
      const mode = String(
        output.execution_mode
        || nested.execution_mode
        || asRecord(nested.summary).execution_mode
        || '',
      )
      if (mode) {
        executionModeCounts[mode] = (executionModeCounts[mode] || 0) + 1
      }
      if (
        output.limited === true
        || nested.limited === true
        || mode === 'deterministic_pre_review'
      ) {
        limited += 1
      }
    }
    return {
      task_count: tasks.length,
      completed: statusCounts.completed || 0,
      failed: statusCounts.failed || 0,
      blocked: statusCounts.blocked || 0,
      skipped: statusCounts.skipped || 0,
      limited,
      execution_mode_counts: executionModeCounts,
      status_counts: statusCounts,
    }
  }

  const reviewCounts = {
    task_count: Number(review.total_tasks || 0),
    completed: Number(review.completed_tasks || 0),
    failed: Number(review.failed_tasks || 0),
    blocked: Number(review.blocked_tasks || 0),
    skipped: Number(review.skipped_tasks || 0),
    limited: Number(review.limited_tasks || 0),
  }
  if (reviewCounts.task_count > 0) {
    return reviewCounts
  }
  return undefined
}

function readSpecialistModes(
  run: SuperAgentRun,
  classification?: MaterialClassification,
): SmartCommitteeDiagnostics['specialistModes'] {
  const review = asRecord(run.review_plus_result)
  const specialistReviews = asArray<Record<string, unknown>>(review.specialist_reviews)
  if (specialistReviews.length) {
    return specialistReviews.map((item) => ({
      agentId: String(item.agent_id || item.agent_name || 'specialist'),
      title: String(item.agent_name || item.agent_id || '专家'),
      executionMode: String(
        item.execution_mode
        || asRecord(item.summary).execution_mode
        || 'unknown',
      ),
      fallbackReason: String(item.fallback_reason || item.harness_unavailable_reason || ''),
    }))
  }

  const board = asRecord(review.smart_task_board)
  let tasks = asArray<Record<string, unknown>>(board.tasks)
  if (!tasks.length) {
    const classificationBoard = asRecord(classification?.smart_task_board)
    tasks = asArray<Record<string, unknown>>(classificationBoard.tasks)
  }
  return tasks.map((task) => {
    const output = asRecord(task.output_summary)
    const nested = asRecord(output.review)
    return {
      agentId: String(task.specialist_id || task.agent_id || 'specialist'),
      title: String(task.title || task.specialist_id || '专家'),
      executionMode: String(
        output.execution_mode
        || nested.execution_mode
        || asRecord(nested.summary).execution_mode
        || 'unknown',
      ),
      fallbackReason: String(
        output.fallback_reason
        || nested.fallback_reason
        || output.harness_unavailable_reason
        || nested.harness_unavailable_reason
        || '',
      ),
    }
  })
}

export function resolveExecutionModeLabel(summary?: SmartCommitteeExecutionModeSummary): string {
  if (!summary) return '未知'
  const harness = Number(summary.harness_count || 0)
  const genericLlm = Number(summary.generic_llm_harness_count || 0)
  const deterministic = Number(summary.deterministic_count || 0)
  if ((harness > 0 || genericLlm > 0) && deterministic > 0) return '混合'
  if (genericLlm > 0 && harness === 0) return 'LLM Harness 专家审查'
  if (harness > 0 && genericLlm === 0) return 'Harness 专家审查'
  if (harness > 0 && genericLlm > 0) return 'Harness + LLM Harness'
  if (deterministic > 0) return '确定性预审'
  if (Number(summary.failed_count || 0) > 0) return '部分失败'
  if (Number(summary.blocked_count || 0) > 0) return '部分阻塞'
  return '未知'
}

export function formatExecutionModeSummaryLines(
  summary?: SmartCommitteeExecutionModeSummary,
  options?: { limited?: boolean },
): string[] {
  if (!summary) return []
  const harness = Number(summary.harness_count || 0)
  const genericLlm = Number(summary.generic_llm_harness_count || 0)
  const deterministic = Number(summary.deterministic_count || 0)
  const failed = Number(summary.failed_count || 0)
  const blocked = Number(summary.blocked_count || 0)
  const lines: string[] = []
  const expertTotal = harness + genericLlm + deterministic

  if (expertTotal > 0) {
    if (genericLlm > 0 && harness === 0) {
      lines.push(`本次智能审查由 ${genericLlm} 个通用 LLM 专家完成。`)
    } else if (harness > 0 && genericLlm === 0) {
      lines.push(`本次智能审查由 ${harness} 个 Harness 专家完成。`)
    } else if (harness > 0 && genericLlm > 0) {
      lines.push(`本次智能审查由 ${harness} 个 Harness 专家与 ${genericLlm} 个通用 LLM 专家完成。`)
    }
    if (deterministic > 0) {
      lines.push(`另有 ${deterministic} 项采用确定性预审。`)
    }
  }

  if (harness === 0 && genericLlm > 0) {
    lines.push('未启用 Review-Plus Harness，已使用 Generic LLM Harness。')
  } else if (harness > 0 && genericLlm === 0) {
    lines.push('已启用 Review-Plus Harness 专家审查。')
  }

  if (failed > 0) {
    lines.push(`有 ${failed} 个专家任务执行失败。`)
  }
  if (blocked > 0) {
    lines.push(`有 ${blocked} 个专家任务被阻塞。`)
  }

  if (options?.limited) {
    lines.push('当前结果为受限审查：包含确定性预审、降级执行或引用/证据覆盖不足。')
  } else if (expertTotal > 0 && deterministic === 0 && failed === 0 && blocked === 0) {
    lines.push('当前结果为完整智能审查。')
  }

  return lines
}

function readBootstrapSummary(
  run: SuperAgentRun,
  classification?: MaterialClassification,
): SmartCommitteeBootstrapSummary | undefined {
  const review = asRecord(run.review_plus_result)
  const fromReview = asRecord(review.bootstrap_summary)
  if (Object.keys(fromReview).length) {
    return {
      bootstrap_mode: String(fromReview.bootstrap_mode || ''),
      synthetic_check_item_count: Number(fromReview.synthetic_check_item_count || 0),
      source_evidence_ref_count: Number(fromReview.source_evidence_ref_count || 0),
      synthetic_context_label: String(fromReview.synthetic_context_label || ''),
    }
  }

  const fromClassification = asRecord(classification?.bootstrap_summary)
  if (Object.keys(fromClassification).length) {
    return {
      bootstrap_mode: String(fromClassification.bootstrap_mode || ''),
      synthetic_check_item_count: Number(fromClassification.synthetic_check_item_count || 0),
      source_evidence_ref_count: Number(fromClassification.source_evidence_ref_count || 0),
      synthetic_context_label: String(fromClassification.synthetic_context_label || ''),
    }
  }

  const docReview = asRecord(run.phase_artifacts?.document_review)
  const fromArtifact = asRecord(docReview.bootstrap_summary)
  if (Object.keys(fromArtifact).length) {
    return {
      bootstrap_mode: String(fromArtifact.bootstrap_mode || ''),
      synthetic_check_item_count: Number(fromArtifact.synthetic_check_item_count || 0),
      source_evidence_ref_count: Number(fromArtifact.source_evidence_ref_count || 0),
      synthetic_context_label: String(fromArtifact.synthetic_context_label || ''),
    }
  }

  return undefined
}

function readTaskSpecPreview(
  run: SuperAgentRun,
  classification?: MaterialClassification,
): { taskSpecCount?: number; domainId?: string; routeSignalHits?: string[] } {
  const classificationRecord = asRecord(classification)
  const reviewPlan = asRecord(classificationRecord.review_plan)
  const smartPlan = asRecord(reviewPlan.smart_review_plan)
    || asRecord(classificationRecord.smart_review_plan)
  const preview = asRecord(reviewPlan.task_board_preview)
    || asRecord(reviewPlan.smart_task_board_summary)

  const taskSpecs = asArray<Record<string, unknown>>(smartPlan.task_specs)
  const rawSpecCount = preview.task_spec_count ?? (taskSpecs.length || undefined)
  const taskSpecCount = rawSpecCount != null ? Number(rawSpecCount) || undefined : undefined

  let domainId = String(preview.domain_id || smartPlan.domain_id || '')
  let routeSignalHits = asArray<string>(preview.route_signal_hits)

  if (taskSpecs.length) {
    const firstInput = asRecord(taskSpecs[0]?.input_summary)
    if (!domainId) domainId = String(firstInput.domain_id || '')
    if (!routeSignalHits.length) {
      routeSignalHits = asArray<string>(firstInput.route_signal_hits)
    }
  }

  const review = asRecord(run.review_plus_result)
  if (!domainId) domainId = String(review.domain_id || '')

  return {
    taskSpecCount,
    domainId: domainId || undefined,
    routeSignalHits: routeSignalHits.length ? routeSignalHits : undefined,
  }
}

export function resolveSmartCommitteeDiagnostics(
  run: SuperAgentRun,
  classification?: MaterialClassification,
): SmartCommitteeDiagnostics {
  const review = asRecord(run.review_plus_result)
  const executionModeSummary = readExecutionModeSummary(run)
  const taskBoardSummary = readTaskBoardSummary(run, classification)
  const bootstrapSummary = readBootstrapSummary(run, classification)
  const taskSpecPreview = readTaskSpecPreview(run, classification)
  const degradationNotes = filterBusinessLines([
    ...asArray<string>(run.trace_report?.degradation_summary),
  ])
  const hasClassificationBoard = Boolean(classification?.smart_task_board || classification?.smart_task_board_summary)
  const derivedExecutionSummary = executionModeSummary || (() => {
    const counts = taskBoardSummary?.execution_mode_counts || {}
    const harness = Number(counts.harness || 0)
    const genericLlm = Number(counts.generic_llm_harness || 0)
    const deterministic = Number(counts.deterministic_pre_review || 0)
    if (!harness && !genericLlm && !deterministic && !taskBoardSummary) return undefined
    return {
      harness_count: harness,
      generic_llm_harness_count: genericLlm,
      deterministic_count: deterministic,
      failed_count: Number(taskBoardSummary?.failed || 0),
      blocked_count: Number(taskBoardSummary?.blocked || 0),
    }
  })()
  const visible = Boolean(
    derivedExecutionSummary
    || taskBoardSummary
    || hasClassificationBoard
    || taskSpecPreview.taskSpecCount
    || degradationNotes.some((note) => /SMART|committee|deterministic|TaskBoard|execution_mode/i.test(note)),
  )

  const limited = Boolean(
    review.limited
    || Number(taskBoardSummary?.limited || 0) > 0
    || Number(derivedExecutionSummary?.deterministic_count || 0) > 0
    || Number(derivedExecutionSummary?.failed_count || 0) > 0
    || Number(derivedExecutionSummary?.blocked_count || 0) > 0,
  )

  const specialistModes = readSpecialistModes(run, classification)
  const fallbackReasons = [
    ...new Set(
      specialistModes
        .map((item) => item.fallbackReason?.trim())
        .filter((reason): reason is string => Boolean(reason)),
    ),
  ]

  const arbiterSummary = asRecord(review.arbiter_summary)
  const replanSuggestions = asArray<string>(review.replan_suggestions)
  const executionModeSummaryLines = formatExecutionModeSummaryLines(derivedExecutionSummary, {
    limited,
  })

  return {
    visible,
    limited,
    executionModeLabel: resolveExecutionModeLabel(derivedExecutionSummary),
    executionModeSummary: derivedExecutionSummary,
    executionModeSummaryLines,
    taskBoardSummary,
    bootstrapSummary,
    taskSpecCount: taskSpecPreview.taskSpecCount,
    domainId: taskSpecPreview.domainId,
    routeSignalHits: taskSpecPreview.routeSignalHits,
    specialistModes,
    citationCoverage: review.citation_coverage != null ? Number(review.citation_coverage) : undefined,
    citationCoverageSource: review.citation_coverage_source ? String(review.citation_coverage_source) : undefined,
    degradationNotes: filterBusinessLines(
      degradationNotes.filter((note) =>
        /SMART|committee|deterministic|TaskBoard|execution_mode|limited|Harness|引用|证据|降级/i.test(note),
      ),
    ),
    fallbackReasons,
    skippedCount: Number(
      taskBoardSummary?.skipped
      ?? taskBoardSummary?.status_counts?.skipped
      ?? review.skipped_tasks
      ?? 0,
    ) || undefined,
    hasArbiterSummary: Boolean(Object.keys(arbiterSummary).length),
    arbiterConsensusSummary: arbiterSummary.consensus_summary
      ? String(arbiterSummary.consensus_summary)
      : undefined,
    replanSuggestions: replanSuggestions.filter(Boolean),
  }
}
