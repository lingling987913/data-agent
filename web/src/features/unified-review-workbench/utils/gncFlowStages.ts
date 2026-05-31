import {
  formatDurationMs,
  GNC_WORKFLOW_STEP_DEFS,
  type GncFlowStepProjection,
  type GncFlowStepStatus,
} from '@/features/unified-review-workbench/constants/gncWorkflowSteps'
import type { UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export type GncFlowStageStatus = GncFlowStepStatus

export interface GncFlowStageDef {
  stageKey: string
  label: string
  description: string
  stepKeys: readonly string[]
  /** Steps that may be skipped when not required (e.g. human_arbitration). */
  conditionalStepKeys?: readonly string[]
  primaryRelatedTab?: UnifiedWorkbenchTabKey
}

export const GNC_FLOW_STAGE_DEFS: readonly GncFlowStageDef[] = [
  {
    stageKey: 'material_intake_gate',
    label: '材料接收与任务建立',
    description: '接收送审材料并建立审查任务。',
    stepKeys: ['review_intake'],
    primaryRelatedTab: 'materials',
  },
  {
    stageKey: 'document_evidence_prep',
    label: '文档解析与证据准备',
    description: '文档结构化、质量筛查与门禁、证据池构建及知识准备。',
    stepKeys: [
      'document_structuring',
      'quality_screening',
      'evidence_pool_building',
      'knowledge_preparation',
    ],
    primaryRelatedTab: 'evidences',
  },
  {
    stageKey: 'committee_review',
    label: '专家组审查（AD/AC/规则）',
    description: 'AD/AC 子流程与规则审查，形成专家组意见。',
    stepKeys: ['committee_review'],
    primaryRelatedTab: 'committee',
  },
  {
    stageKey: 'editorial_rid',
    label: '问题合稿与 RID 台账',
    description: '归并审查发现，维护 RID 台账。',
    stepKeys: ['editorial_synthesis'],
    primaryRelatedTab: 'rid',
  },
  {
    stageKey: 'chief_arbitration',
    label: '总师裁定与仲裁',
    description: '总师审定结论；如需人工仲裁则进入仲裁分支。',
    stepKeys: ['chief_adjudication', 'human_arbitration'],
    conditionalStepKeys: ['human_arbitration'],
    primaryRelatedTab: 'decision',
  },
  {
    stageKey: 'closure',
    label: '报告归档 / 闭环',
    description: '生成闭环报告并完成审查归档。',
    stepKeys: ['review_closure'],
    primaryRelatedTab: 'report',
  },
] as const

export interface GncFlowStageStepView {
  step: GncFlowStepProjection
  stepIndex: number
  conditionalNote?: string
}

export interface GncFlowStageProjection {
  stageKey: string
  label: string
  description: string
  status: GncFlowStageStatus
  isCurrent: boolean
  durationMs: number | null
  error?: string
  summary?: string
  conditionalNote?: string
  stepKeys: string[]
  steps: GncFlowStageStepView[]
  primaryRelatedTab?: UnifiedWorkbenchTabKey
  stageIndex: number
}

export interface AggregateGncFlowStagesOptions {
  requiresArbitration?: boolean
}

function stepStatus(step: GncFlowStepProjection): GncFlowStepStatus {
  const status = String(step.status || 'pending')
  if (status === 'completed' || status === 'running' || status === 'failed') return status
  return 'pending'
}

function isConditionalStepNotRequired(
  stepKey: string,
  step: GncFlowStepProjection,
  conditionalStepKeys: readonly string[] | undefined,
  requiresArbitration: boolean | undefined,
): boolean {
  if (!conditionalStepKeys?.includes(stepKey)) return false
  if (requiresArbitration === true) return false
  const status = stepStatus(step)
  return status === 'pending' && !step.is_current && !step.completed
}

export function resolveConditionalStepNote(
  stepKey: string,
  step: GncFlowStepProjection,
  requiresArbitration?: boolean,
): string | undefined {
  if (stepKey !== 'human_arbitration') return undefined
  const status = stepStatus(step)
  if (status === 'completed') return undefined
  if (status === 'running' || step.is_current) return '仲裁进行中'
  if (status === 'failed') return undefined
  if (requiresArbitration === false) return '无需仲裁'
  if (requiresArbitration === true) return '按需触发 · 待仲裁'
  return '按需触发'
}

export function resolveStageConditionalNote(
  stageDef: GncFlowStageDef,
  stageSteps: GncFlowStageStepView[],
  requiresArbitration?: boolean,
): string | undefined {
  if (!stageDef.conditionalStepKeys?.length) return undefined
  const notes = stageSteps
    .filter((view) => stageDef.conditionalStepKeys?.includes(view.step.step_key))
    .map((view) => view.conditionalNote)
    .filter(Boolean) as string[]
  if (!notes.length) return undefined
  if (notes.every((note) => note === '无需仲裁')) return '无需仲裁'
  if (notes.includes('仲裁进行中')) return '仲裁进行中'
  if (notes.includes('按需触发 · 待仲裁')) return '按需触发 · 待仲裁'
  return notes[0]
}

function stepCountsForStageCompletion(
  stepKey: string,
  step: GncFlowStepProjection,
  conditionalStepKeys: readonly string[] | undefined,
  requiresArbitration: boolean | undefined,
): boolean {
  if (isConditionalStepNotRequired(stepKey, step, conditionalStepKeys, requiresArbitration)) {
    return true
  }
  return stepStatus(step) === 'completed' || Boolean(step.completed)
}

export function computeGncFlowStageStatus(
  stageSteps: GncFlowStageStepView[],
  stageDef: GncFlowStageDef,
  requiresArbitration?: boolean,
): GncFlowStageStatus {
  const statuses = stageSteps.map((view) => stepStatus(view.step))
  if (statuses.includes('failed')) return 'failed'
  if (statuses.includes('running') || stageSteps.some((view) => view.step.is_current)) return 'running'
  const allComplete = stageDef.stepKeys.every((stepKey) => {
    const view = stageSteps.find((item) => item.step.step_key === stepKey)
    if (!view) return false
    return stepCountsForStageCompletion(
      stepKey,
      view.step,
      stageDef.conditionalStepKeys,
      requiresArbitration,
    )
  })
  if (allComplete) return 'completed'
  const anyStarted = statuses.some((status) => status !== 'pending')
    || stageSteps.some((view) => Boolean(view.step.completed))
  if (anyStarted) return 'running'
  return 'pending'
}

function sumStageDuration(stageSteps: GncFlowStageStepView[]): number | null {
  let total = 0
  let hasValue = false
  for (const view of stageSteps) {
    const duration = view.step.duration_ms
    if (typeof duration === 'number' && duration >= 0) {
      total += duration
      hasValue = true
    }
  }
  return hasValue ? total : null
}

function pickStageError(stageSteps: GncFlowStageStepView[]): string | undefined {
  for (const view of stageSteps) {
    const error = String(view.step.error || '').trim()
    if (error) return error
  }
  return undefined
}

function isStageCurrent(stageSteps: GncFlowStageStepView[]): boolean {
  return stageSteps.some((view) => Boolean(view.step.is_current))
    || stageSteps.some((view) => stepStatus(view.step) === 'running')
}

function pickStageSummary(stageSteps: GncFlowStageStepView[]): string | undefined {
  const subtitles = stageSteps
    .map((view) => String(view.step.subtitle || view.step.summary || '').trim())
    .filter(Boolean)
  if (!subtitles.length) return undefined
  return subtitles[subtitles.length - 1]
}

export function buildStepIndexMap(steps: GncFlowStepProjection[]): Map<string, number> {
  const map = new Map<string, number>()
  steps.forEach((step, index) => {
    map.set(String(step.step_key || ''), index)
  })
  return map
}

export function aggregateGncFlowStages(
  steps: GncFlowStepProjection[],
  options: AggregateGncFlowStagesOptions = {},
): GncFlowStageProjection[] {
  const { requiresArbitration } = options
  const stepByKey = new Map(steps.map((step) => [String(step.step_key || ''), step]))
  const stepIndexMap = buildStepIndexMap(steps)

  return GNC_FLOW_STAGE_DEFS.map((stageDef, stageIndex) => {
    const stageSteps: GncFlowStageStepView[] = stageDef.stepKeys
      .map((stepKey) => {
        const step = stepByKey.get(stepKey) || { step_key: stepKey, status: 'pending' }
        return {
          step,
          stepIndex: stepIndexMap.get(stepKey) ?? -1,
          conditionalNote: resolveConditionalStepNote(stepKey, step, requiresArbitration),
        }
      })
      .sort((a, b) => a.stepIndex - b.stepIndex)

    const status = computeGncFlowStageStatus(stageSteps, stageDef, requiresArbitration)
    const isCurrent = isStageCurrent(stageSteps)

    return {
      stageKey: stageDef.stageKey,
      label: stageDef.label,
      description: stageDef.description,
      status,
      isCurrent,
      durationMs: sumStageDuration(stageSteps),
      error: pickStageError(stageSteps),
      summary: pickStageSummary(stageSteps),
      conditionalNote: resolveStageConditionalNote(stageDef, stageSteps, requiresArbitration),
      stepKeys: [...stageDef.stepKeys],
      steps: stageSteps,
      primaryRelatedTab: stageDef.primaryRelatedTab,
      stageIndex,
    }
  })
}

export function resolveGncFlowCurrentStageLabel(
  stages: GncFlowStageProjection[],
): string {
  const current = stages.find((stage) => stage.isCurrent)
  if (current) return current.label
  const running = stages.find((stage) => stage.status === 'running')
  if (running) return running.label
  const failed = stages.find((stage) => stage.status === 'failed')
  if (failed) return failed.label
  const lastCompleted = [...stages].reverse().find((stage) => stage.status === 'completed')
  if (lastCompleted) return lastCompleted.label
  return '—'
}

export function formatStageDuration(durationMs: number | null | undefined): string {
  return formatDurationMs(durationMs)
}

export function allGncStageStepKeys(): string[] {
  return GNC_FLOW_STAGE_DEFS.flatMap((stage) => [...stage.stepKeys])
}

export function assertGncStageCoverage(): void {
  const covered = new Set(allGncStageStepKeys())
  for (const def of GNC_WORKFLOW_STEP_DEFS) {
    if (!covered.has(def.stepKey)) {
      throw new Error(`GNC stage mapping missing step: ${def.stepKey}`)
    }
  }
}
