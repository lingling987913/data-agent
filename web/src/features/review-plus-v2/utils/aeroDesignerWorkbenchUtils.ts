import type { ReviewPlusMaterialItem, ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { getHarnessPlan } from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'
import { HARNESS_AGENT_ID_LABELS } from '@/features/review-plus-shared/types'
import {
  getReviewPlusCompletedStepKeys,
  resolveActiveWorkflowStepKey,
} from '@/features/review-plus-v2/utils/reviewPlusWorkflowGraph'
import { REVIEW_PLUS_PIPELINE_STEPS } from '@/features/review-plus-v2/utils/reviewPlusPipeline'

export interface ParsedEvidenceRef {
  raw: string
  materialName: string
  lineNo: number
}

export interface EvidenceHighlight {
  materialName: string
  lineNo: number
  viewport: 'left' | 'right'
}

export interface WorkbenchSelection {
  source: 'coverage' | 'finding' | 'traceability' | 'cross_doc'
  checkItemId?: string
  findingId?: string
  traceRowId?: string
  crossDocItemId?: string
  quote?: string
  requiresHumanConfirmation?: boolean
  pendingTraceLinkId?: string
  highlights: EvidenceHighlight[]
}

export function parseEvidenceRef(ref: string): ParsedEvidenceRef | null {
  const parts = ref.split(':')
  if (parts.length < 3 || parts[0] !== 'ev') return null
  const materialName = parts[1]
  const lineNo = parseInt(String(parts[2]).replace('line-', ''), 10)
  if (!materialName || Number.isNaN(lineNo)) return null
  return { raw: ref, materialName, lineNo }
}

export function matchMaterialByEvidenceName(
  materials: ReviewPlusMaterialItem[],
  rawFilename: string,
): ReviewPlusMaterialItem | undefined {
  const needle = rawFilename.toLowerCase()
  return materials.find((m) => {
    const name = m.name.toLowerCase()
    return name === needle || name.includes(needle) || needle.includes(name)
  })
}

export function resolveEvidenceViewport(role: string): 'left' | 'right' {
  if (role === 'task_book' || role === 'checklist' || role === 'review_rule') return 'left'
  return 'right'
}

export function buildHighlightsFromRefs(
  refs: string[],
  materials: ReviewPlusMaterialItem[],
): EvidenceHighlight[] {
  const highlights: EvidenceHighlight[] = []
  for (const ref of refs) {
    const parsed = parseEvidenceRef(ref)
    if (!parsed) continue
    const material = matchMaterialByEvidenceName(materials, parsed.materialName)
    if (!material) continue
    highlights.push({
      materialName: material.name,
      lineNo: parsed.lineNo,
      viewport: resolveEvidenceViewport(String(material.role)),
    })
  }
  return highlights
}

export function resolveTraceMatrixRowId(rowData: Record<string, unknown>): string {
  const requirement = rowData.requirement as Record<string, unknown> | undefined
  const topId = String(rowData.top_requirement_id || requirement?.requirement_id || '')
  const decomposedId = String(rowData.decomposed_requirement_id || '')
  const designId = String(rowData.design_item_id || '')
  return topId || decomposedId || designId || String(rowData.row_id || '')
}

export function countPendingTraceLinks(task: ReviewPlusTaskDetail): number {
  const data = task.traceability_result as { trace_links?: Array<{ status?: string }> } | undefined
  return (data?.trace_links || []).filter((link) => link.status === 'candidate').length
}

export function countPendingCoverageHitl(task: ReviewPlusTaskDetail): number {
  return (task.coverage_matrix?.rows || []).filter((row) => row.requires_human_confirmation).length
}

export function countPendingHitl(task: ReviewPlusTaskDetail): number {
  return countPendingTraceLinks(task) + countPendingCoverageHitl(task)
}

export function findMatchingTraceLink(
  task: Pick<ReviewPlusTaskDetail, 'traceability_result'> & Partial<ReviewPlusTaskDetail>,
  selection: WorkbenchSelection,
) {
  const data = task.traceability_result as {
    trace_links?: Array<{
      link_id: string
      status?: string
      source_id?: string
      target_id?: string
      evidence_ids?: string[]
    }>
  } | undefined
  const links = data?.trace_links || []
  const evidenceKeys = selection.highlights.map(
    (h) => `ev:${h.materialName}:line-${h.lineNo}`,
  )
  return links.find((link) => (
    link.status === 'candidate'
    && (
      (selection.quote && (link.source_id === selection.quote || link.target_id === selection.quote))
      || evidenceKeys.some((key) => link.evidence_ids?.includes(key))
    )
  ))
}

export function buildExecutionStatus(task: ReviewPlusTaskDetail) {
  const completedSteps = getReviewPlusCompletedStepKeys(task)
  const activeStepKey = resolveActiveWorkflowStepKey(task)
  const activeStep = REVIEW_PLUS_PIPELINE_STEPS.find((step) => step.step_key === activeStepKey)
  const totalSteps = REVIEW_PLUS_PIPELINE_STEPS.length
  const completedCount = completedSteps.size
  const plan = getHarnessPlan(task)
  const selectedAgents = plan?.selected_agent_ids?.length || 0
  const traceFailed = (task.agent_run_traces || []).filter((t) => t.status === 'failed').length

  return {
    activeStepKey,
    activeStepLabel: activeStep?.label || activeStepKey || '—',
    completedCount,
    totalSteps,
    pendingHitl: countPendingHitl(task),
    pendingTraceLinks: countPendingTraceLinks(task),
    pendingCoverageHitl: countPendingCoverageHitl(task),
    selectedAgents,
    traceFailed,
    taskStatus: String(task.status),
  }
}

export function formatAgentLabel(agentId: string): string {
  return HARNESS_AGENT_ID_LABELS[agentId] || agentId.replace(/_agent$/, '').replace(/_/g, ' ')
}
