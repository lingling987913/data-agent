import { REVIEW_PLUS_PIPELINE_STEPS } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import {
  aggregateReviewProcessStages,
  mapWorkflowStatusToReviewProcess,
  resolveReviewProcessCurrentStageLabel,
} from '@/features/review-process-model/reviewProcessModel'
import type { ReviewProcessModel, ReviewProcessStep } from '@/features/review-process-model/types'

export const REVIEW_PLUS_PROCESS_STAGE_DEFS = [
  {
    stageKey: 'material_intake',
    label: '材料接收与分类',
    description: '材料角色分类与审查场景识别',
    stepKeys: ['material_classification', 'scenario_detection'],
  },
  {
    stageKey: 'document_structure',
    label: '文档结构化与预审',
    description: '结构化待审文档、章节树/证据池与送审预审',
    stepKeys: ['document_structuring', 'chief_orchestration'],
  },
  {
    stageKey: 'rule_mapping',
    label: '规则抽取与证据映射',
    description: '从审查规则材料抽取检查项并完成章节映射',
    stepKeys: ['rule_extraction', 'rule_section_mapping'],
  },
  {
    stageKey: 'item_review',
    label: '逐项符合性审查',
    description: '动态组队执行符合性判读与证据对齐',
    stepKeys: ['item_review'],
  },
  {
    stageKey: 'traceability_cross',
    label: '追溯与跨文档核验',
    description: '需求闭环追溯与跨文档一致性审查',
    stepKeys: ['traceability', 'cross_document_review'],
  },
  {
    stageKey: 'report_output',
    label: '报告输出',
    description: '审查报告生成与归档',
    stepKeys: ['report_composition'],
  },
] as const

export interface ReviewPlusProcessInput {
  stepStatuses: Record<string, string>
  stepSubtitles?: Record<string, string>
  sourceReviewId?: string
  findingCount?: number
  title?: string
  subtitle?: string
}

const ITEM_REVIEW_DEEP_TASKS = [
  { id: 'clause-check', label: '条款核验', summary: '对照标准条款核验符合性' },
  { id: 'evidence-check', label: '证据核验', summary: '核验证据引用与覆盖完整性' },
  { id: 'cross-check', label: '交叉核验', summary: '交叉比对多源材料一致性' },
] as const

export function buildReviewPlusReviewProcessModel(input: ReviewPlusProcessInput): ReviewProcessModel {
  const atomicSteps: ReviewProcessStep[] = REVIEW_PLUS_PIPELINE_STEPS.map((def) => ({
    stepKey: def.step_key,
    label: def.label,
    status: mapWorkflowStatusToReviewProcess(input.stepStatuses[def.step_key] || 'pending'),
    subtitle: input.stepSubtitles?.[def.step_key] || def.description,
    isCurrent: input.stepStatuses[def.step_key] === 'running',
  }))

  const stages = aggregateReviewProcessStages(REVIEW_PLUS_PROCESS_STAGE_DEFS, atomicSteps).map((stage) => {
    if (stage.stageKey === 'item_review') {
      const findingSuffix = (input.findingCount || 0) > 0 ? `${input.findingCount} 条审查意见` : '符合性判读与证据对齐'
      return {
        ...stage,
        subtitle: (input.findingCount || 0) > 0 ? `已形成 ${input.findingCount} 条审查意见` : stage.subtitle,
        subflowLanes: [{
          laneKey: 'item_review_parallel',
          label: '符合性判读子任务',
          enabled: true,
          status: stage.status,
          summary: findingSuffix,
          stages: ITEM_REVIEW_DEEP_TASKS.map((task, index) => ({
            stepKey: task.id,
            label: task.label,
            status: index <= 1 ? stage.status : stage.status === 'completed' ? 'completed' : 'pending',
            summary: task.summary,
          })),
        }],
      }
    }
    if (stage.stageKey === 'material_intake' && input.sourceReviewId) {
      return {
        ...stage,
        subtitle: `载体 ${input.sourceReviewId}`,
      }
    }
    return stage
  })

  return {
    processKind: 'review_plus',
    title: input.title || '文件组审查',
    subtitle: input.subtitle,
    currentStageLabel: resolveReviewProcessCurrentStageLabel(stages),
    stages,
  }
}

export function buildReviewPlusStageSubtitleFromModel(
  stageKey: string,
  model: ReviewProcessModel,
): string {
  const stage = model.stages.find((item) => item.stageKey === stageKey)
  if (!stage) return ''
  if (stage.subtitle) return stage.subtitle
  if (stage.summary) return stage.summary
  if (stage.steps.some((step) => step.status === 'running')) {
    return stage.steps.find((step) => step.status === 'running')?.label || stage.description
  }
  const completedCount = stage.steps.filter((step) => step.status === 'completed').length
  if (completedCount > 0 && stage.steps.length > 1) {
    return `${completedCount}/${stage.steps.length} 底层步骤已完成`
  }
  return stage.steps[0]?.subtitle || stage.description
}
