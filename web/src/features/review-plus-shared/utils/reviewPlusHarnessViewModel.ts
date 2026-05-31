import type {
  ReviewPlusAgentRunTrace,
  ReviewPlusCoverageMatrix,
  ReviewPlusHarnessPlan,
  ReviewPlusTaskDetail,
} from '@/features/review-plus-shared/types'
import { HARNESS_AGENT_ID_LABELS, MATERIAL_ROLE_LABELS } from '@/features/review-plus-shared/types'

export function formatAgentIdLabel(agentId: string): string {
  const key = String(agentId || '').trim()
  if (!key) return '—'
  if (HARNESS_AGENT_ID_LABELS[key]) return HARNESS_AGENT_ID_LABELS[key]
  return key.replace(/_agent$/, '').replace(/_/g, ' ')
}

export function formatMaterialRoleLabel(role: string): string {
  return MATERIAL_ROLE_LABELS[role] || role || '—'
}

const SPECIALIST_TO_HARNESS_AGENT: Record<string, string> = {
  "document_format_reviewer": "checklist_agent",
  "product_assurance_reviewer": "product_assurance_agent",
  "reliability_safety_reviewer": "reliability_safety_agent",
  "gnc_design_reviewer": "gnc_design_agent",
  "attitude_control_reviewer": "gnc_design_agent",
  "attitude_determination_reviewer": "gnc_design_agent",
  "interface_reviewer": "interface_agent",
  "verification_reviewer": "verification_agent",
  "requirements_traceability_reviewer": "cross_document_consistency_agent",
}

export interface DelegateSpecialist {
  agent_id: string
  agent_name: string
  role: string
  required: boolean
  reason: string
  matched_signals: string[]
}

export function getDelegatedSpecialists(
  task: Pick<ReviewPlusTaskDetail, 'chief_review_plan'>,
  harnessAgentId: string
): DelegateSpecialist[] {
  const chief = task.chief_review_plan
  if (!chief || !chief.selected_agents) return []

  const specialists = chief.selected_agents as unknown as DelegateSpecialist[]
  
  return specialists.filter((spec) => {
    const specId = spec.agent_id
    const mappedHarnessId = SPECIALIST_TO_HARNESS_AGENT[specId]
    if (mappedHarnessId === harnessAgentId) {
      return true
    }

    // Default core mappings fallback
    if (harnessAgentId === 'checklist_agent' && specId === 'document_format_reviewer') {
      return true
    }
    if (harnessAgentId === 'subject_report_agent' && specId === 'document_format_reviewer') {
      return true
    }
    if (harnessAgentId === 'task_book_agent' && specId === 'requirements_traceability_reviewer') {
      return true
    }

    return false
  })
}

export function getHarnessPlan(task: Pick<ReviewPlusTaskDetail, 'chief_review_plan'>): ReviewPlusHarnessPlan | null {
  const chief = task.chief_review_plan
  if (!chief) return null

  if (chief.harness_plan && typeof chief.harness_plan === 'object' && Object.keys(chief.harness_plan).length > 0) {
    return chief.harness_plan
  }

  // 优雅兼容与预览：若后端真正运行前的中间状态下没有 harness_plan，但有 selected_agents，动态映射出一个
  if (chief.selected_agents && Array.isArray(chief.selected_agents) && chief.selected_agents.length > 0) {
    const selectedAgentIdsSet = new Set<string>()
    // 必备的核心基准专业 Agent
    selectedAgentIdsSet.add("checklist_agent")
    selectedAgentIdsSet.add("task_book_agent")
    selectedAgentIdsSet.add("subject_report_agent")
    selectedAgentIdsSet.add("product_assurance_agent")

    chief.selected_agents.forEach((item) => {
      const specialistId = String(item.agent_id || '')
      const harnessId = SPECIALIST_TO_HARNESS_AGENT[specialistId]
      if (harnessId) {
        selectedAgentIdsSet.add(harnessId)
      }
    })

    const selected_agent_ids = Array.from(selectedAgentIdsSet)
    const selection_reasons: Record<string, string> = {}
    chief.selected_agents.forEach((item) => {
      const specialistId = String(item.agent_id || '')
      const harnessId = SPECIALIST_TO_HARNESS_AGENT[specialistId]
      if (harnessId) {
        selection_reasons[harnessId] = String(item.reason || `总师编排已选择 ${specialistId}。`)
      }
    })

    return {
      team_id: 'review_plus_dynamic_harness_team',
      selected_agent_ids,
      required_agent_ids: ['checklist_agent', 'task_book_agent', 'subject_report_agent', 'product_assurance_agent', ...selected_agent_ids],
      selection_reasons,
    }
  }

  return null
}

export type HarnessArtifactsTask = {
  chief_review_plan?: ReviewPlusTaskDetail['chief_review_plan']
  agent_run_traces?: ReviewPlusTaskDetail['agent_run_traces']
  coverage_matrix?: ReviewPlusTaskDetail['coverage_matrix']
}

export function hasHarnessArtifacts(task: HarnessArtifactsTask | null | undefined): boolean {
  if (!task) return false
  const harnessPlan = getHarnessPlan(task)
  const hasPlan = Boolean(
    harnessPlan?.selected_agent_ids?.length
    || harnessPlan?.required_agent_ids?.length,
  )
  const hasTraces = (task.agent_run_traces?.length || 0) > 0
  const matrix = task.coverage_matrix
  const hasMatrix = Boolean(
    matrix?.summary?.row_count
    || matrix?.rows?.length,
  )
  return hasPlan || hasTraces || hasMatrix
}

export interface HarnessSummaryMetrics {
  teamId: string
  selectedCount: number
  requiredCount: number
  traceCompleted: number
  traceFailed: number
  closedCount: number
  taskOnlyCount: number
  subjectOnlyCount: number
  missingCount: number
  rowCount: number
}

export function buildHarnessSummaryMetrics(
  plan: ReviewPlusHarnessPlan | null,
  traces: ReviewPlusAgentRunTrace[],
  matrix: ReviewPlusCoverageMatrix | undefined,
): HarnessSummaryMetrics {
  const summary = matrix?.summary || {}
  const completed = traces.filter((t) => t.status === 'completed').length
  const failed = traces.filter((t) => t.status === 'failed').length
  return {
    teamId: plan?.team_id || '—',
    selectedCount: plan?.selected_agent_ids?.length || 0,
    requiredCount: plan?.required_agent_ids?.length || 0,
    traceCompleted: completed,
    traceFailed: failed,
    closedCount: summary.closed_count ?? 0,
    taskOnlyCount: summary.task_only_count ?? 0,
    subjectOnlyCount: summary.subject_only_count ?? 0,
    missingCount: summary.missing_count ?? 0,
    rowCount: summary.row_count ?? matrix?.rows?.length ?? 0,
  }
}

export function isCoreAgent(agentId: string, plan: ReviewPlusHarnessPlan | null): boolean {
  return Boolean(plan?.required_agent_ids?.includes(agentId))
}

export function formatTraceOutputSummary(output: Record<string, unknown> | undefined): string[] {
  if (!output || !Object.keys(output).length) return []
  const lines: string[] = []
  const pushCount = (label: string, key: string) => {
    const val = output[key]
    if (Array.isArray(val)) lines.push(`${label} ${val.length}`)
    else if (typeof val === 'number') lines.push(`${label} ${val}`)
  }
  const countSuffix = (label: string, key: string) => {
    const countKey = `${key}_count`
    const countValue = output[countKey]
    if (typeof countValue === 'number' && countValue > 0) {
      lines.push(`${label} ${countValue}`)
    }
  }
  pushCount('检查项', 'check_items')
  pushCount('检查项', 'check_item_count')
  pushCount('映射', 'mapped_count')
  pushCount('审查记录', 'finding_count')
  pushCount('满足', 'satisfied')
  pushCount('不满足', 'not_satisfied')
  countSuffix('覆盖贡献', 'coverage_contributions')
  countSuffix('领域贡献', 'domain_contributions')
  countSuffix('任务书证据', 'task_evidences')
  countSuffix('任务书需求', 'task_book_requirements')
  countSuffix('跨文档问题', 'agent_issues')
  if (output.coverage_rows) pushCount('覆盖行', 'coverage_rows')
  if (output.agent_issues) pushCount('问题', 'agent_issues')
  const direct = String(output.summary || output.message || '').trim()
  if (direct) lines.unshift(direct)
  if (lines.length === 0) {
    return Object.entries(output)
      .slice(0, 4)
      .map(([k, v]) => `${k}: ${String(v).slice(0, 80)}`)
  }
  return lines.slice(0, 5)
}

export function getTraceByAgentId(
  task: Pick<ReviewPlusTaskDetail, 'agent_run_traces'>,
  agentId: string,
): ReviewPlusAgentRunTrace | null {
  const traces = task.agent_run_traces || []
  return traces.find((t) => t.agent_id === agentId) ?? null
}

export function getOrderedHarnessTraceAgentIds(
  task: Pick<ReviewPlusTaskDetail, 'chief_review_plan' | 'agent_run_traces'>,
): string[] {
  const plan = getHarnessPlan(task)
  const selected = plan?.selected_agent_ids || []
  const traceIds = (task.agent_run_traces || []).map((t) => t.agent_id)
  const ordered = [...selected]
  for (const id of traceIds) {
    if (!ordered.includes(id)) ordered.push(id)
  }
  return ordered
}

function formatRecordLines(record: Record<string, unknown> | undefined, maxDepth = 1): string[] {
  if (!record || !Object.keys(record).length) return []
  const lines: string[] = []
  for (const [key, value] of Object.entries(record)) {
    if (value == null || value === '') continue
    if (Array.isArray(value)) {
      lines.push(`${key}：${value.length} 项`)
      if (maxDepth > 0 && value.length > 0 && typeof value[0] === 'object') {
        lines.push(...formatRecordLines(asRecord(value[0]), 0).map((l) => `  ${l}`))
      }
    } else if (typeof value === 'object') {
      const nested = formatRecordLines(value as Record<string, unknown>, 0)
      if (nested.length) lines.push(`${key}：${nested.join('；')}`)
      else lines.push(`${key}：—`)
    } else {
      const text = String(value).trim()
      if (text) lines.push(`${key}：${text.length > 120 ? `${text.slice(0, 120)}…` : text}`)
    }
  }
  return lines.slice(0, 12)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function buildAgentTraceDetailSections(
  task: Pick<ReviewPlusTaskDetail, 'chief_review_plan' | 'agent_run_traces'>,
  agentId: string,
): {
  label: string
  isCore: boolean
  selectionReason: string
  signals: string[]
  trace: ReviewPlusAgentRunTrace | null
  inputLines: string[]
  outputLines: string[]
} {
  const plan = getHarnessPlan(task)
  const trace = getTraceByAgentId(task, agentId)
  return {
    label: formatAgentIdLabel(agentId),
    isCore: isCoreAgent(agentId, plan),
    selectionReason: String(plan?.selection_reasons?.[agentId] || '').trim(),
    signals: plan?.matched_signals?.[agentId] || [],
    trace,
    inputLines: formatRecordLines(trace?.input_summary),
    outputLines: (() => {
      if (!trace?.output_summary) return []
      const summary = formatTraceOutputSummary(trace.output_summary)
      return summary.length ? summary : formatRecordLines(trace.output_summary)
    })(),
  }
}

export function pickTopSelectionReasons(
  plan: ReviewPlusHarnessPlan | null,
  limit = 3,
): Array<{ agentId: string; label: string; reason: string }> {
  if (!plan?.selection_reasons) return []
  return Object.entries(plan.selection_reasons)
    .slice(0, limit)
    .map(([agentId, reason]) => ({
      agentId,
      label: formatAgentIdLabel(agentId),
      reason: String(reason || '').trim(),
    }))
    .filter((item) => item.reason)
}
