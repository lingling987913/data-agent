import {
  aggregateReviewProcessStages,
  mapWorkflowStatusToReviewProcess,
  resolveReviewProcessCurrentStageLabel,
} from '@/features/review-process-model/reviewProcessModel'
import type {
  ReviewProcessModel,
  ReviewProcessStatus,
  ReviewProcessStep,
  ReviewProcessSubflowLane,
} from '@/features/review-process-model/types'

export const SMART_REVIEW_PROCESS_STAGE_DEFS = [
  {
    stageKey: 'material_prep',
    label: '材料接收与准备',
    description: '材料上传、结构化与审查任务组织',
    stepKeys: ['structure_materials', 'bootstrap_review_plus_task'],
  },
  {
    stageKey: 'format_gate',
    label: '格式预审与门禁',
    description: '送审材料可审查性检查',
    stepKeys: ['format_gate'],
  },
  {
    stageKey: 'expert_review',
    label: '专家并行审查',
    description: '多专家/多文档专项审查',
    stepKeys: ['smart_specialist_review'],
  },
  {
    stageKey: 'chief_merge',
    label: '总师综合评判',
    description: '汇总专家意见、处理冲突与加权裁决',
    stepKeys: ['arbiter_summary'],
  },
  {
    stageKey: 'quality_report',
    label: '质量复核与报告',
    description: '质量复核、证据覆盖诊断与报告导出',
    stepKeys: ['synthesize'],
  },
] as const

export interface SmartExpertTaskInput {
  taskId: string
  title: string
  subtitle?: string
  status: string
  findingCount?: number
}

export interface SmartReviewProcessInput {
  prepareStatus: string
  formatGateStatus?: string
  formatGateSubtitle?: string
  committeeStatus: string
  mergeStatus: string
  synthesizeStatus: string
  expertTasks?: SmartExpertTaskInput[]
  expertCount?: number
  title?: string
  subtitle?: string
}

function expertTasksToSubflowLanes(expertTasks: SmartExpertTaskInput[]): ReviewProcessSubflowLane[] {
  return expertTasks.map((task) => ({
    laneKey: task.taskId,
    label: task.title,
    enabled: true,
    status: mapWorkflowStatusToReviewProcess(task.status) as ReviewProcessStatus,
    summary: task.subtitle || (task.findingCount ? `${task.findingCount} 条发现` : '专项审查'),
    stages: [{
      stepKey: `${task.taskId}-review`,
      label: task.title,
      status: mapWorkflowStatusToReviewProcess(task.status) as ReviewProcessStatus,
      summary: task.subtitle,
    }],
  }))
}

export function buildSmartReviewProcessModel(input: SmartReviewProcessInput): ReviewProcessModel {
  const stepStatuses: Record<string, string> = {
    structure_materials: input.prepareStatus,
    bootstrap_review_plus_task: input.prepareStatus,
    format_gate: input.formatGateStatus || 'pending',
    smart_specialist_review: input.committeeStatus,
    arbiter_summary: input.mergeStatus,
    synthesize: input.synthesizeStatus,
  }

  const stepSubtitles: Record<string, string> = {
    structure_materials: input.expertCount
      ? `已规划 ${input.expertCount} 个审查组`
      : '材料结构化与任务组织',
    format_gate: input.formatGateSubtitle || '送审材料可审查性检查',
    smart_specialist_review: '多专家并行审查与一致性核验',
    arbiter_summary: '按证据覆盖、发现严重度、专家置信度加权汇总',
    synthesize: '质量复核与报告导出',
  }

  const atomicSteps: ReviewProcessStep[] = SMART_REVIEW_PROCESS_STAGE_DEFS.flatMap((stage) =>
    stage.stepKeys.map((stepKey) => ({
      stepKey,
      label: stepKey,
      status: mapWorkflowStatusToReviewProcess(stepStatuses[stepKey] || 'pending'),
      subtitle: stepSubtitles[stepKey],
      isCurrent: stepStatuses[stepKey] === 'running',
    })),
  )

  const expertSubflowLanes = input.expertTasks?.length
    ? expertTasksToSubflowLanes(input.expertTasks)
    : undefined

  const stages = aggregateReviewProcessStages(SMART_REVIEW_PROCESS_STAGE_DEFS, atomicSteps).map((stage) => {
    if (stage.stageKey === 'expert_review' && expertSubflowLanes?.length) {
      return {
        ...stage,
        subflowLanes: expertSubflowLanes,
        subtitle: `${expertSubflowLanes.length} 位专家并行审查`,
      }
    }
    if (stage.stageKey === 'format_gate' && !input.formatGateStatus) {
      return {
        ...stage,
        status: 'pending' as const,
        subtitle: input.formatGateSubtitle || stage.description,
      }
    }
    return stage
  })

  return {
    processKind: 'smart_committee',
    title: input.title || '智能审查',
    subtitle: input.subtitle,
    currentStageLabel: resolveReviewProcessCurrentStageLabel(stages),
    stages,
  }
}

export function buildSmartStageSubtitleFromModel(
  stageKey: string,
  model: ReviewProcessModel,
): string {
  const stage = model.stages.find((item) => item.stageKey === stageKey)
  if (!stage) return ''
  if (stage.subtitle) return stage.subtitle
  if (stage.subflowLanes?.length) {
    return stage.subflowLanes.map((lane) => lane.summary || lane.label).join(' · ')
  }
  return stage.description
}
