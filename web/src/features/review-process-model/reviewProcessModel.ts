import type {
  ReviewProcessStage,
  ReviewProcessStageDef,
  ReviewProcessStageView,
  ReviewProcessStatus,
  ReviewProcessStep,
  ReviewProcessSubflowLane,
} from '@/features/review-process-model/types'

export function mapWorkflowStatusToReviewProcess(status: string): ReviewProcessStatus {
  if (status === 'completed' || status === 'skipped') return status === 'skipped' ? 'skipped' : 'completed'
  if (status === 'running') return 'running'
  if (status === 'failed') return 'failed'
  if (status === 'blocked') return 'blocked'
  if (status === 'awaiting_confirm') return 'awaiting_confirm'
  return 'pending'
}

export function mapReviewProcessStatusToWorkflow(status: ReviewProcessStatus): string {
  return status
}

export function stepStatus(step: ReviewProcessStep): ReviewProcessStatus {
  const status = String(step.status || 'pending')
  if (
    status === 'completed'
    || status === 'running'
    || status === 'failed'
    || status === 'skipped'
    || status === 'awaiting_confirm'
    || status === 'blocked'
  ) {
    return status
  }
  return 'pending'
}

function isConditionalStepNotRequired(
  stepKey: string,
  step: ReviewProcessStep,
  conditionalStepKeys: readonly string[] | undefined,
  requiresConditional: boolean | undefined,
): boolean {
  if (!conditionalStepKeys?.includes(stepKey)) return false
  if (requiresConditional === true) return false
  const status = stepStatus(step)
  return status === 'pending' && !step.isCurrent
}

function stepCountsForStageCompletion(
  stepKey: string,
  step: ReviewProcessStep,
  conditionalStepKeys: readonly string[] | undefined,
  requiresConditional: boolean | undefined,
): boolean {
  if (isConditionalStepNotRequired(stepKey, step, conditionalStepKeys, requiresConditional)) {
    return true
  }
  return stepStatus(step) === 'completed' || stepStatus(step) === 'skipped'
}

export function computeReviewProcessStageStatus(
  stageSteps: ReviewProcessStageView[],
  stageDef: ReviewProcessStageDef,
  requiresConditional?: boolean,
): ReviewProcessStatus {
  const statuses = stageSteps.map((view) => stepStatus(view.step))
  if (statuses.includes('failed')) return 'failed'
  if (statuses.includes('blocked')) return 'blocked'
  if (statuses.includes('running') || stageSteps.some((view) => view.step.isCurrent)) return 'running'
  if (statuses.includes('awaiting_confirm')) return 'awaiting_confirm'

  const allComplete = stageDef.stepKeys.every((stepKey) => {
    const view = stageSteps.find((item) => item.step.stepKey === stepKey)
    if (!view) return false
    return stepCountsForStageCompletion(
      stepKey,
      view.step,
      stageDef.conditionalStepKeys,
      requiresConditional,
    )
  })
  if (allComplete) return 'completed'

  const anyStarted = statuses.some((status) => status !== 'pending')
    || stageSteps.some((view) => stepStatus(view.step) === 'completed')
  if (anyStarted) return 'running'
  return 'pending'
}

function sumStageDuration(stageSteps: ReviewProcessStageView[]): number | null {
  let total = 0
  let hasValue = false
  for (const view of stageSteps) {
    const duration = view.step.durationMs
    if (typeof duration === 'number' && duration >= 0) {
      total += duration
      hasValue = true
    }
  }
  return hasValue ? total : null
}

function pickStageError(stageSteps: ReviewProcessStageView[]): string | undefined {
  for (const view of stageSteps) {
    const error = String(view.step.error || '').trim()
    if (error) return error
  }
  return undefined
}

function isStageCurrent(stageSteps: ReviewProcessStageView[]): boolean {
  return stageSteps.some((view) => Boolean(view.step.isCurrent))
    || stageSteps.some((view) => stepStatus(view.step) === 'running')
}

function pickStageSummary(stageSteps: ReviewProcessStageView[]): string | undefined {
  const subtitles = stageSteps
    .map((view) => String(view.step.subtitle || view.step.summary || '').trim())
    .filter(Boolean)
  if (!subtitles.length) return undefined
  return subtitles[subtitles.length - 1]
}

export function buildStepIndexMap(steps: ReviewProcessStep[]): Map<string, number> {
  const map = new Map<string, number>()
  steps.forEach((step, index) => {
    map.set(String(step.stepKey || ''), index)
  })
  return map
}

export interface AggregateReviewProcessStagesOptions {
  requiresConditional?: boolean
  resolveConditionalNote?: (
    stepKey: string,
    step: ReviewProcessStep,
    requiresConditional?: boolean,
  ) => string | undefined
  resolveStageConditionalNote?: (
    stageDef: ReviewProcessStageDef,
    stageSteps: ReviewProcessStageView[],
    requiresConditional?: boolean,
  ) => string | undefined
}

export function aggregateReviewProcessStages(
  stageDefs: readonly ReviewProcessStageDef[],
  steps: ReviewProcessStep[],
  options: AggregateReviewProcessStagesOptions = {},
): ReviewProcessStage[] {
  const {
    requiresConditional,
    resolveConditionalNote,
    resolveStageConditionalNote,
  } = options
  const stepByKey = new Map(steps.map((step) => [String(step.stepKey || ''), step]))
  const stepIndexMap = buildStepIndexMap(steps)

  return stageDefs.map((stageDef, stageIndex) => {
    const stageSteps: ReviewProcessStageView[] = stageDef.stepKeys
      .map((stepKey) => {
        const step = stepByKey.get(stepKey) || {
          stepKey,
          label: stepKey,
          status: 'pending' as const,
        }
        return {
          step,
          stepIndex: stepIndexMap.get(stepKey) ?? -1,
          conditionalNote: resolveConditionalNote?.(stepKey, step, requiresConditional),
        }
      })
      .sort((a, b) => a.stepIndex - b.stepIndex)

    const status = computeReviewProcessStageStatus(stageSteps, stageDef, requiresConditional)
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
      conditionalNote: resolveStageConditionalNote?.(stageDef, stageSteps, requiresConditional),
      stepKeys: [...stageDef.stepKeys],
      steps: stageSteps.map((view) => view.step),
      stageIndex,
      badge: `阶段 ${stageIndex + 1}`,
    }
  })
}

export function resolveReviewProcessCurrentStageLabel(stages: ReviewProcessStage[]): string {
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

export function attachSubflowLanesToStage(
  stages: ReviewProcessStage[],
  stageKey: string,
  subflowLanes: ReviewProcessSubflowLane[],
): ReviewProcessStage[] {
  return stages.map((stage) => (
    stage.stageKey === stageKey
      ? { ...stage, subflowLanes }
      : stage
  ))
}

export function flattenSubflowLanesToDeepTasks(
  subflowLanes: ReviewProcessSubflowLane[],
  fallbackStatus: ReviewProcessStatus = 'pending',
): Array<{ id: string; label: string; summary: string; status: ReviewProcessStatus }> {
  const tasks: Array<{ id: string; label: string; summary: string; status: ReviewProcessStatus }> = []
  for (const lane of subflowLanes) {
    if (!lane.enabled) {
      tasks.push({
        id: lane.laneKey,
        label: lane.label,
        summary: lane.skipReason || lane.summary || '本轮未启用',
        status: 'skipped',
      })
      continue
    }
    const activeStages = lane.stages.filter((stage) => stage.status !== 'skipped')
    if (!activeStages.length) {
      tasks.push({
        id: lane.laneKey,
        label: lane.label,
        summary: lane.summary || '待执行',
        status: lane.status || fallbackStatus,
      })
      continue
    }
    for (const stage of activeStages) {
      const findingSuffix = stage.subtitle ? ` · ${stage.subtitle}` : ''
      tasks.push({
        id: `${lane.laneKey}-${stage.stepKey}`,
        label: `${lane.label} · ${stage.label}`,
        summary: stage.summary || `${stage.status}${findingSuffix}`,
        status: stage.status === 'pending' ? fallbackStatus : stage.status,
      })
    }
  }
  return tasks
}
