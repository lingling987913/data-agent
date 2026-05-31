import {
  GNC_WORKFLOW_STEP_DEFS,
  type GncFlowStepProjection,
} from '@/features/unified-review-workbench/constants/gncWorkflowSteps'
import {
  aggregateGncFlowStages,
  GNC_FLOW_STAGE_DEFS,
  resolveConditionalStepNote,
  resolveGncFlowCurrentStageLabel,
  resolveStageConditionalNote,
} from '@/features/unified-review-workbench/utils/gncFlowStages'
import {
  buildGncCommitteeSubflowLanes,
  subflowStageStatusLabel,
  summarizeSubflowLane,
  type GncCommitteeSubflowInput,
  type GncSubflowLaneProjection,
} from '@/features/unified-review-workbench/utils/gncCommitteeSubFlows'
import {
  aggregateReviewProcessStages,
  mapWorkflowStatusToReviewProcess,
} from '@/features/review-process-model/reviewProcessModel'
import type {
  ReviewProcessModel,
  ReviewProcessStatus,
  ReviewProcessStep,
  ReviewProcessSubflowLane,
} from '@/features/review-process-model/types'

export interface GncReviewProcessInput {
  stepStatuses: string[]
  stepSubtitles?: Record<string, string>
  requiresArbitration?: boolean
  committee?: GncCommitteeSubflowInput | null
  title?: string
  subtitle?: string
}

function mapGncFlowStatus(status: string): ReviewProcessStatus {
  if (status === 'completed') return 'completed'
  if (status === 'running') return 'running'
  if (status === 'failed') return 'failed'
  return 'pending'
}

function mapSubflowLane(lane: GncSubflowLaneProjection): ReviewProcessSubflowLane {
  return {
    laneKey: lane.groupKey,
    label: lane.groupLabel,
    enabled: lane.enabled,
    skipReason: lane.skipReason,
    summary: lane.summary || summarizeSubflowLane(lane),
    verdict: lane.verdict,
    status: lane.enabled ? 'running' : 'skipped',
    stages: lane.stages.map((stage) => ({
      stepKey: stage.stageKey,
      label: stage.stageLabel,
      status: stage.status === 'skipped'
        ? 'skipped'
        : stage.status === 'completed'
          ? 'completed'
          : stage.status === 'running'
            ? 'running'
            : stage.status === 'failed' || stage.status === 'blocked'
              ? 'failed'
              : 'pending',
      subtitle: stage.findingCount ? `${stage.findingCount} 条发现` : undefined,
      summary: stage.summary || subflowStageStatusLabel(stage.status),
    })),
  }
}

export function buildGncReviewProcessModel(input: GncReviewProcessInput): ReviewProcessModel {
  const steps: GncFlowStepProjection[] = GNC_WORKFLOW_STEP_DEFS.map((def, index) => ({
    step_key: def.stepKey,
    label: def.label,
    status: mapWorkflowStatusToReviewProcess(input.stepStatuses[index] || 'pending'),
    completed: ['completed', 'skipped'].includes(input.stepStatuses[index] || ''),
    is_current: input.stepStatuses[index] === 'running',
    subtitle: input.stepSubtitles?.[def.stepKey],
    related_tab: def.relatedTab,
  }))

  const gncStages = aggregateGncFlowStages(steps, { requiresArbitration: input.requiresArbitration })
  const subflowLanes = buildGncCommitteeSubflowLanes(input.committee).map(mapSubflowLane)

  const stageDefs = GNC_FLOW_STAGE_DEFS.map((stage) => ({
    stageKey: stage.stageKey,
    label: stage.label,
    description: stage.description,
    stepKeys: stage.stepKeys,
    conditionalStepKeys: stage.conditionalStepKeys,
  }))

  const atomicSteps: ReviewProcessStep[] = GNC_WORKFLOW_STEP_DEFS.map((def, index) => ({
    stepKey: def.stepKey,
    label: def.label,
    status: mapWorkflowStatusToReviewProcess(input.stepStatuses[index] || 'pending'),
    subtitle: input.stepSubtitles?.[def.stepKey],
    isCurrent: input.stepStatuses[index] === 'running',
  }))

  const stages = aggregateReviewProcessStages(stageDefs, atomicSteps, {
    requiresConditional: input.requiresArbitration,
    resolveConditionalNote: (stepKey, step, requiresArbitration) => resolveConditionalStepNote(
      stepKey,
      {
        step_key: stepKey,
        status: step.status,
        is_current: step.isCurrent,
        completed: step.status === 'completed',
      },
      requiresArbitration,
    ),
    resolveStageConditionalNote: (stageDef, stageSteps, requiresArbitration) => resolveStageConditionalNote(
      {
        stageKey: stageDef.stageKey,
        label: stageDef.label,
        description: stageDef.description,
        stepKeys: stageDef.stepKeys,
        conditionalStepKeys: stageDef.conditionalStepKeys,
      },
      stageSteps.map((view) => ({
        step: {
          step_key: view.step.stepKey,
          status: view.step.status,
          is_current: view.step.isCurrent,
          completed: view.step.status === 'completed',
        },
        stepIndex: view.stepIndex,
        conditionalNote: view.conditionalNote,
      })),
      requiresArbitration,
    ),
  }).map((stage) => {
    const gncStage = gncStages.find((item) => item.stageKey === stage.stageKey)
    return {
      ...stage,
      status: gncStage ? mapGncFlowStatus(gncStage.status) : stage.status,
      isCurrent: gncStage?.isCurrent ?? stage.isCurrent,
      summary: gncStage?.summary || stage.summary,
      error: gncStage?.error || stage.error,
      conditionalNote: gncStage?.conditionalNote || stage.conditionalNote,
      durationMs: gncStage?.durationMs ?? stage.durationMs,
      subflowLanes: stage.stageKey === 'committee_review' && subflowLanes.length
        ? subflowLanes
        : stage.subflowLanes,
    }
  })

  return {
    processKind: 'gnc',
    title: input.title || 'GNC 审查',
    subtitle: input.subtitle,
    currentStageLabel: resolveGncFlowCurrentStageLabel(gncStages),
    stages,
  }
}

export function buildGncStageSubtitleFromModel(
  stageKey: string,
  model: ReviewProcessModel,
): string {
  const stage = model.stages.find((item) => item.stageKey === stageKey)
  if (!stage) return ''
  if (stage.summary) return stage.summary
  if (stage.conditionalNote) return stage.conditionalNote
  if (stage.error) return stage.error
  if (stage.subflowLanes?.length) {
    return stage.subflowLanes.map((lane) => lane.summary || lane.label).join(' · ')
  }
  if (stage.steps.some((step) => step.status === 'running')) {
    const running = stage.steps.find((step) => step.status === 'running')
    return running?.label || stage.description
  }
  const completedCount = stage.steps.filter((step) => step.status === 'completed').length
  if (completedCount > 0 && stage.steps.length > 1) {
    return `${completedCount}/${stage.steps.length} 底层步骤已完成`
  }
  return stage.steps[0]?.subtitle || stage.description
}
