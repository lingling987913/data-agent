/**
 * Review-Plus 九步执行链路 — 与 review_plus_workflow.py 对齐的单一事实来源
 */

import {
  hasHarnessArtifacts,
  type HarnessArtifactsTask,
} from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'

export type ReviewPlusPipelineStepKey =
  | 'material_classification'
  | 'scenario_detection'
  | 'document_structuring'
  | 'chief_orchestration'
  | 'rule_extraction'
  | 'rule_section_mapping'
  | 'item_review'
  | 'traceability'
  | 'cross_document_review'
  | 'report_composition'

export interface ReviewPlusPipelineStep {
  step_key: ReviewPlusPipelineStepKey
  label: string
  description: string
  completeEvent: string
  startEvent?: string
}

/** 与 get_review_plus_workflow steps / description 一致 */
export const REVIEW_PLUS_PIPELINE_STEPS: ReviewPlusPipelineStep[] = [
  {
    step_key: 'material_classification',
    label: '材料分类',
    description: '材料角色分类',
    completeEvent: 'material_classification_completed',
    startEvent: 'material_classification_started',
  },
  {
    step_key: 'scenario_detection',
    label: '场景识别',
    description: '审查场景识别',
    completeEvent: 'scenario_detection_completed',
  },
  {
    step_key: 'document_structuring',
    label: '文档结构化',
    description: '结构化待审文档并生成章节树/证据池',
    completeEvent: 'document_structuring_completed',
  },
  {
    step_key: 'chief_orchestration',
    label: '送审预审',
    description: '送审包格式审查与预审分工建议',
    completeEvent: 'chief_orchestration_completed',
  },
  {
    step_key: 'rule_extraction',
    label: '规则抽取',
    description: '从审查规则材料抽取检查项',
    completeEvent: 'rule_extraction_completed',
    startEvent: 'rule_extraction_started',
  },
  {
    step_key: 'rule_section_mapping',
    label: '证据映射',
    description: '检查项到文档章节映射',
    completeEvent: 'rule_section_mapping_completed',
    startEvent: 'rule_section_mapping_started',
  },
  {
    step_key: 'item_review',
    label: '动态组队符合性审查',
    description: '按材料信号动态组队，逐环节执行并生成覆盖矩阵',
    completeEvent: 'item_review_completed',
    startEvent: 'item_review_started',
  },
  {
    step_key: 'traceability',
    label: '追溯构建',
    description: '需求闭环追溯矩阵构建',
    completeEvent: 'traceability_completed',
    startEvent: 'traceability_started',
  },
  {
    step_key: 'cross_document_review',
    label: '跨文档审查',
    description: '跨文档一致性审查',
    completeEvent: 'cross_document_review_completed',
  },
  {
    step_key: 'report_composition',
    label: '报告生成',
    description: '审查报告生成',
    completeEvent: 'report_composition_completed',
    startEvent: 'report_composition_started',
  },
]

export const REVIEW_PLUS_STEP_KEYS = REVIEW_PLUS_PIPELINE_STEPS.map((s) => s.step_key)

export type ReviewPlusWorkbenchTabKey =
  | 'overview'
  | 'flow'
  | 'materials'
  | 'check_items'
  | 'findings'
  | 'coverage'
  | 'traceability'
  | 'cross_doc'
  | 'report'
  | 'events'

/** 流程节点点击 → 工作台 Tab */
export function workflowStepToWorkbenchTab(stepKey: string): ReviewPlusWorkbenchTabKey {
  switch (stepKey) {
    case 'material_classification':
    case 'scenario_detection':
      return 'materials'
    case 'document_structuring':
    case 'chief_orchestration':
    case 'rule_extraction':
    case 'rule_section_mapping':
      return 'check_items'
    case 'item_review':
      return 'findings'
    case 'traceability':
      return 'traceability'
    case 'cross_document_review':
      return 'cross_doc'
    case 'report_composition':
      return 'overview'
    default:
      return 'flow'
  }
}

export const REVIEW_PLUS_EVENT_TYPE_LABELS: Record<string, string> = {
  task_created: '任务创建',
  materials_uploaded: '材料上传',
  material_classification_started: '开始材料分类',
  material_classification_completed: '材料分类完成',
  scenario_detection_completed: '场景识别完成',
  document_structuring_completed: '文档结构化完成',
  chief_orchestration_completed: '送审预审完成',
  rule_extraction_started: '开始规则抽取',
  rule_extraction_completed: '规则抽取完成',
  rule_section_mapping_started: '开始证据映射',
  rule_section_mapping_completed: '证据映射完成',
  item_review_started: '开始动态组队符合性审查',
  item_review_completed: '动态组队符合性审查完成',
  traceability_started: '开始追溯构建',
  traceability_completed: '追溯构建完成',
  cross_document_review_completed: '跨文档审查完成',
  report_composition_started: '开始报告生成',
  report_composition_completed: '报告生成完成',
  review_start_requested: '启动审查',
  review_continue_requested: '继续处理审查',
  review_restart_requested: '重新开始审查',
  workflow_failed: '流程失败',
  gatekeeping_rechecked: '门禁复检',
  material_role_confirmed: '角色确认',
  status_changed: '状态变更',
}

/** 审查已启动但九步链路尚未全部完成（含失败、卡住、后台任务中断） */
export function shouldShowReviewPlusContinueAction(task: {
  status?: string
  events?: Array<{ type?: string }>
}): boolean {
  const status = String(task.status || '')
  if (['completed', 'draft', 'materials_uploaded', 'blocked', 'limited_pass'].includes(status)) {
    return false
  }

  const eventTypes = new Set((task.events || []).map((e) => String(e.type || '')))
  const reviewStarted =
    eventTypes.has('review_start_requested')
    || eventTypes.has('review_continue_requested')
    || REVIEW_PLUS_PIPELINE_STEPS.some((step) => eventTypes.has(step.completeEvent))

  if (!reviewStarted) return false
  if (status === 'failed') return true
  return !eventTypes.has('report_composition_completed')
}

const PRE_REVIEW_STATUSES = new Set([
  'draft', 'materials_uploaded', 'classified', 'ready', 'limited_pass',
])

const RUNNING_STATUSES = new Set([
  'parsing', 'classifying', 'structuring', 'rule_extracting', 'mapping',
  'reviewing', 'traceability_building', 'reporting', 'gatekeeping',
])

export const REVIEW_PLUS_TAB_LABELS: Record<ReviewPlusWorkbenchTabKey, string> = {
  overview: '审查结论',
  flow: '审查进度',
  materials: '送审包',
  check_items: '检查项',
  findings: '审查记录',
  coverage: '覆盖矩阵',
  traceability: '需求闭环',
  cross_doc: '跨文档',
  report: '审查报告',
  events: '执行日志',
}

/** 主 Tab：审查进度/结论 + 核心结果消费 */
export const REVIEW_PLUS_PRIMARY_TAB_KEYS = new Set<ReviewPlusWorkbenchTabKey>([
  'overview',
  'findings',
  'cross_doc',
])

/** 二级 Tab：收进「更多」菜单（排查/专家向） */
export const REVIEW_PLUS_SECONDARY_TAB_KEYS = new Set<ReviewPlusWorkbenchTabKey>([
  'coverage',
  'check_items',
  'traceability',
  'events',
])

function hasReviewStarted(task: { events?: Array<{ type?: string }> }): boolean {
  const eventTypes = new Set((task.events || []).map((e) => String(e.type || '')))
  if (eventTypes.has('review_start_requested') || eventTypes.has('review_continue_requested')) {
    return true
  }
  return REVIEW_PLUS_PIPELINE_STEPS.some((step) => eventTypes.has(step.completeEvent))
}

/** 工作台 Tab 可见性：备料独立页 / 进度+结果 Tab / 结论 Tab */
export function resolveReviewPlusVisibleTabs(
  task: HarnessArtifactsTask & {
    status?: string
    events?: Array<{ type?: string }>
  },
  completedSteps: Set<string>,
): Set<ReviewPlusWorkbenchTabKey> {
  const status = String(task.status || '')
  const started = hasReviewStarted(task)

  if (PRE_REVIEW_STATUSES.has(status) && !started) {
    return new Set<ReviewPlusWorkbenchTabKey>(['materials'])
  }

  const visible = new Set<ReviewPlusWorkbenchTabKey>()

  const showOverview = status === 'completed' || started
  if (showOverview) {
    visible.add('overview')
  }

  if (status === 'completed') {
    visible.add('findings')
  }

  for (const stepKey of completedSteps) {
    const tab = workflowStepToWorkbenchTab(stepKey)
    if (tab !== 'flow' && tab !== 'materials') visible.add(tab)
  }

  if (completedSteps.has('item_review') && hasHarnessArtifacts({
    chief_review_plan: task.chief_review_plan,
    agent_run_traces: task.agent_run_traces,
    coverage_matrix: task.coverage_matrix,
  })) {
    visible.add('coverage')
  }

  if (status === 'failed' && started) {
    visible.add('overview')
    visible.add('events')
  }

  return visible
}

export function formatReviewPlusEventLabel(eventType: string): string {
  const key = String(eventType || '').trim()
  if (!key) return '—'
  return REVIEW_PLUS_EVENT_TYPE_LABELS[key] || key
}

export function inferReviewPlusStepKeyFromEvent(eventType: string): ReviewPlusPipelineStepKey | '' {
  const normalized = String(eventType || '').trim()
  if (!normalized) return ''

  const direct = REVIEW_PLUS_STEP_KEYS.find(
    (key) => normalized === key || normalized.startsWith(`${key}_`),
  )
  if (direct) return direct

  if (normalized.includes('material_classification') || normalized === 'materials_uploaded') {
    return 'material_classification'
  }
  if (normalized.includes('scenario_detection')) return 'scenario_detection'
  if (normalized.includes('document_structuring')) return 'document_structuring'
  if (normalized.includes('chief_orchestration')) return 'chief_orchestration'
  if (normalized.includes('rule_extraction')) return 'rule_extraction'
  if (normalized.includes('rule_section_mapping')) return 'rule_section_mapping'
  if (normalized.includes('item_review')) return 'item_review'
  if (normalized.includes('traceability')) return 'traceability'
  if (normalized.includes('cross_document')) return 'cross_document_review'
  if (normalized.includes('report_composition')) return 'report_composition'

  return ''
}

export const CROSS_DOC_ITEM_TYPE_LABELS: Record<string, string> = {
  missing_cross_document_reference: '跨文档引用缺失',
  metric_unit_mismatch: '指标单位不一致',
  metric_value_mismatch: '指标数值不一致',
  metric_statistic_mismatch: '指标统计口径不一致',
  baseline_version_mismatch: '版本/基线不一致',
  missing_decomposition: '需求分解不完整',
  missing_design_closure: '设计闭合不足',
  design_item_without_requirement_basis: '设计项缺上游依据',
  missing_verification: '验证覆盖不足',
  verification_condition_gap: '验证工况覆盖不足',
}
