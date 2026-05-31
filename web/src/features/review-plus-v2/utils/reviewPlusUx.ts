/**
 * 文件组审查 — 业务用户向体验辅助（默认 Tab、场景文案、备料步骤）
 * 阶段契约见 docs/plans/aero/review-plus-v2-phase-ux.md
 */

import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import {
  REVIEW_PLUS_PIPELINE_STEPS,
  type ReviewPlusWorkbenchTabKey,
  shouldShowReviewPlusContinueAction,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'

const PRE_REVIEW_STATUSES = new Set([
  'draft', 'materials_uploaded', 'parsed', 'classified', 'scenario_detected', 'ready', 'limited_pass',
])

const RUNNING_STATUSES = new Set([
  'parsing', 'classifying', 'structuring', 'rule_extracting', 'mapping',
  'reviewing', 'traceability_building', 'reporting', 'gatekeeping',
])

export const REVIEW_PLUS_SCENARIO_LABELS: Record<string, string> = {
  product_assurance_reliability_safety: '产品保证与可靠性安全性',
  gnc_design_review: 'GNC 设计评审',
  generic_multi_document: '多文档符合性审查',
}

export function formatReviewPlusScenarioLabel(scenario?: string | null): string {
  const key = String(scenario || '').trim()
  if (!key) return ''
  return REVIEW_PLUS_SCENARIO_LABELS[key] || key.replace(/_/g, ' ')
}

export function hasReviewPlusReviewStarted(task: {
  status?: string
  events?: Array<{ type?: string }>
}): boolean {
  const eventTypes = new Set((task.events || []).map((e) => String(e.type || '')))
  if (eventTypes.has('review_start_requested') || eventTypes.has('review_continue_requested')) {
    return true
  }
  return REVIEW_PLUS_PIPELINE_STEPS.some((step) => eventTypes.has(step.completeEvent))
}

export function isReviewPlusPreReview(task: { status?: string; events?: Array<{ type?: string }> }): boolean {
  const status = String(task.status || '')
  return PRE_REVIEW_STATUSES.has(status) && !hasReviewPlusReviewStarted(task)
}

export function isReviewPlusParseComplete(task: {
  status?: string
  parse_artifact?: Record<string, unknown>
  materials?: Array<{ parse_status?: string; content?: string }>
}): boolean {
  const status = String(task.status || '')
  if (status === 'parsed' || status === 'classified' || status === 'ready' || status === 'limited_pass') {
    return true
  }
  const artifact = task.parse_artifact
  if (artifact && typeof artifact === 'object') {
    const parsedDocuments = Array.isArray(artifact.parsed_documents) ? artifact.parsed_documents : []
    const fileResults = Array.isArray(artifact.file_results) ? artifact.file_results : []
    if (parsedDocuments.length > 0 || fileResults.length > 0) {
      return true
    }
  }
  const materials = task.materials || []
  if (!materials.length) return false
  return materials.every((item) => {
    const parseStatus = String(item.parse_status || '')
    if (parseStatus === 'failed') return false
    return Boolean((item.content || '').trim()) || parseStatus === 'ok' || parseStatus === 'degraded' || parseStatus === 'partial'
  })
}

export function isReviewPlusExecuting(task: {
  status?: string
  events?: Array<{ type?: string }>
}): boolean {
  const status = String(task.status || '')
  if (status === 'completed') return false
  if (isReviewPlusPreReview(task)) return false
  return RUNNING_STATUSES.has(status) || shouldShowReviewPlusContinueAction(task)
}

/** 审查已提交启动，但流程尚未真正跑起来（无运行态、无步骤产出） */
export function isReviewPlusStartupStage(
  task: { status?: string; events?: Array<{ type?: string }> },
  completedSteps: Set<string>,
): boolean {
  const status = String(task.status || '')
  if (status === 'completed' || status === 'failed') return false
  if (!hasReviewPlusReviewStarted(task)) return false
  if (RUNNING_STATUSES.has(status)) return false
  return completedSteps.size === 0
}

/** 是否展示 overview Tab（未完成时承载流程进度，完成后承载审查结论） */
export function shouldShowReviewPlusOverviewTab(
  task: { status?: string; events?: Array<{ type?: string }> },
  completedSteps: Set<string>,
): boolean {
  const status = String(task.status || '')
  if (status === 'completed') return true
  if (!hasReviewPlusReviewStarted(task)) return false
  if (status === 'failed') return true
  if (RUNNING_STATUSES.has(status)) return true
  return true
}

/** overview Tab 文案：执行中显示进度，完成后显示结论 */
export function resolveReviewPlusOverviewTabLabel(task: { status?: string }): string {
  return String(task.status || '') === 'completed' ? '审查结论' : '审查进度'
}

export type ReviewPlusPrimaryProcessAction = {
  kind: 'start' | 'continue' | 'retry'
  label: string
  loadingLabel: string
  testId: string
}

/** Header 主处理按钮：启动前开始处理，等待续跑时继续处理，失败时重新处理；运行中不展示 */
export function resolveReviewPlusPrimaryProcessAction(input: {
  status?: string
  canStart: boolean
  canContinue: boolean
}): ReviewPlusPrimaryProcessAction | null {
  const status = String(input.status || '')
  if (status === 'completed') return null
  if (input.canStart) {
    return {
      kind: 'start',
      label: '开始处理',
      loadingLabel: '开始中...',
      testId: 'review-plus-v2-start-review',
    }
  }
  if (!input.canContinue || RUNNING_STATUSES.has(status)) return null
  if (status === 'failed') {
    return {
      kind: 'retry',
      label: '重新处理',
      loadingLabel: '处理中...',
      testId: 'review-plus-v2-retry-review',
    }
  }
  return {
    kind: 'continue',
    label: '继续处理',
    loadingLabel: '处理中...',
    testId: 'review-plus-v2-continue-review',
  }
}

type DefaultTabInput = {
  status?: string
  events?: Array<{ type?: string }>
}

/** 首页 / 打开任务时的默认工作台 Tab */
export function resolveReviewPlusDefaultWorkbenchTab(
  task: DefaultTabInput,
  initialTab?: string,
): ReviewPlusWorkbenchTabKey {
  const allowed = new Set<ReviewPlusWorkbenchTabKey>([
    'overview', 'flow', 'materials', 'check_items', 'findings', 'coverage', 'traceability', 'cross_doc', 'report', 'events',
  ])
  if (initialTab === 'flow' || initialTab === 'report') return 'overview'
  if (initialTab && allowed.has(initialTab as ReviewPlusWorkbenchTabKey)) {
    return initialTab as ReviewPlusWorkbenchTabKey
  }

  const status = String(task.status || '')
  if (status === 'completed') return 'overview'
  if (status === 'failed') return 'overview'
  if (RUNNING_STATUSES.has(status)) return 'overview'
  if (resolveReviewPlusWorkspaceMode(task) === 'progress') return 'overview'
  if (PRE_REVIEW_STATUSES.has(status)) return 'materials'
  return 'materials'
}

export type ReviewPlusWorkbenchPhase = 'pre_review' | 'startup' | 'executing' | 'completed' | 'failed'

/** 工作台主视图：送审包 / 审查进度 / 审查结论 三态分离 */
export type ReviewPlusWorkspaceMode = 'package' | 'progress' | 'conclusion'

export function resolveReviewPlusWorkspaceMode(task: {
  status?: string
  events?: Array<{ type?: string }>
}): ReviewPlusWorkspaceMode {
  const status = String(task.status || '')
  if (status === 'completed') return 'conclusion'
  if (hasReviewPlusReviewStarted(task)) return 'progress'
  return 'package'
}

export const REVIEW_PLUS_PHASE_LABELS: Record<ReviewPlusWorkbenchPhase, string> = {
  pre_review: '送审准备',
  startup: '启动等待',
  executing: '审查执行中',
  completed: '审查完成',
  failed: '审查失败',
}

/** 工作台业务阶段（用户向，不暴露后端 status 枚举） */
export function resolveReviewPlusWorkbenchPhase(
  task: { status?: string; events?: Array<{ type?: string }> },
  completedSteps: Set<string>,
): ReviewPlusWorkbenchPhase {
  const status = String(task.status || '')
  if (status === 'completed') return 'completed'
  if (status === 'failed') return 'failed'
  if (isReviewPlusPreReview(task)) return 'pre_review'
  if (isReviewPlusStartupStage(task, completedSteps)) return 'startup'
  return 'executing'
}

export function resolveReviewPlusPhaseChipClass(phase: ReviewPlusWorkbenchPhase): string {
  switch (phase) {
    case 'completed':
      return 'border-positive/25 bg-positive/8 text-positive'
    case 'failed':
      return 'border-destructive/25 bg-destructive/8 text-destructive'
    case 'executing':
      return 'border-primaryAccent/25 bg-primaryAccent/8 text-primaryAccent'
    case 'startup':
      return 'border-warning/25 bg-warning/8 text-warning'
    default:
      return 'border-brand/25 bg-brand/8 text-brand'
  }
}

/** 任务列表行 hint（与 Header 主按钮语义一致） */
export function resolveReviewPlusTaskActionHint(task: {
  status?: string
  events?: Array<{ type?: string }>
}): string {
  const status = String(task.status || '')
  if (status === 'completed') return '查看审查结论'
  if (status === 'failed' || status === 'blocked') return '重新处理或补充送审包'
  if (RUNNING_STATUSES.has(status)) return '查看审查进度'
  if (hasReviewPlusReviewStarted(task) && PRE_REVIEW_STATUSES.has(status)) return '继续处理或检查送审包'
  if (PRE_REVIEW_STATUSES.has(status)) return '补充送审材料并开始处理'
  return '进入工作台继续处理'
}

/** 从列表/Session 打开工作台时的默认 Tab */
export function resolveReviewPlusWorkbenchOpenTab(
  task: DefaultTabInput,
): ReviewPlusWorkbenchTabKey {
  return resolveReviewPlusDefaultWorkbenchTab(task)
}
