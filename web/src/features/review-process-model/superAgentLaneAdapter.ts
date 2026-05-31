import type { WorkflowStepStatus } from '@aqua/workflow-core'
import {
  flattenSubflowLanesToDeepTasks,
  mapReviewProcessStatusToWorkflow,
} from '@/features/review-process-model/reviewProcessModel'
import type { ReviewProcessModel, ReviewProcessStage } from '@/features/review-process-model/types'

export interface ProcessLaneNodeSpec {
  id: string
  label: string
  subtitle: string
  status: WorkflowStepStatus
  badge?: string
  processItemId: string
}

export interface ProcessLaneSpec {
  id: string
  title: string
  subtitle: string
  processItemId: string
  nodes: ProcessLaneNodeSpec[]
}

export function reviewProcessStageNodeId(laneId: string, stageKey: string): string {
  return `${laneId}-stage-${stageKey}`
}

export function buildProcessLaneFromModel(
  laneId: string,
  model: ReviewProcessModel,
  options: {
    title: string
    subtitle?: string
    processItemId: string
    resolveStageSubtitle?: (stage: ReviewProcessStage) => string
    extraNodes?: ProcessLaneNodeSpec[]
  },
): ProcessLaneSpec {
  const resolveSubtitle = options.resolveStageSubtitle || ((stage) => (
    stage.subtitle || stage.summary || stage.description
  ))

  const nodes: ProcessLaneNodeSpec[] = model.stages.map((stage) => ({
    id: reviewProcessStageNodeId(laneId, stage.stageKey),
    label: stage.label,
    subtitle: resolveSubtitle(stage),
    status: mapReviewProcessStatusToWorkflow(stage.status) as WorkflowStepStatus,
    badge: stage.badge || `阶段 ${stage.stageIndex + 1}`,
    processItemId: options.processItemId,
  }))

  return {
    id: laneId,
    title: options.title,
    subtitle: options.subtitle || (
      model.currentStageLabel !== '—'
        ? `当前：${model.currentStageLabel}`
        : (model.subtitle || model.title)
    ),
    processItemId: options.processItemId,
    nodes: [...nodes, ...(options.extraNodes || [])],
  }
}

export function resolveProcessStageDeepTasks(
  laneId: string,
  stageIndex: number,
  model: ReviewProcessModel,
): Array<{ id: string; label: string; summary: string; status: WorkflowStepStatus }> {
  const stage = model.stages[stageIndex]
  if (!stage) return []

  if (stage.subflowLanes?.length) {
    return flattenSubflowLanesToDeepTasks(stage.subflowLanes, stage.status).map((task) => ({
      ...task,
      status: mapReviewProcessStatusToWorkflow(task.status) as WorkflowStepStatus,
    }))
  }

  if (stage.steps.length > 1) {
    return stage.steps.map((step) => ({
      id: `${laneId}-${step.stepKey}`,
      label: step.label,
      summary: step.subtitle || step.summary || '',
      status: mapReviewProcessStatusToWorkflow(step.status) as WorkflowStepStatus,
    }))
  }

  return []
}

export function findProcessStageIndexByKey(
  model: ReviewProcessModel,
  stageKey: string,
): number {
  return model.stages.findIndex((stage) => stage.stageKey === stageKey)
}
