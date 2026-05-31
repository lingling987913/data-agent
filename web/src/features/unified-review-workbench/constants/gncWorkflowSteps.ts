export const GNC_WORKFLOW_STEP_DEFS = [
  { stepKey: 'review_intake', label: '送审材料接收', badge: '步骤 1', relatedTab: 'overview' },
  { stepKey: 'document_structuring', label: '文档结构化', badge: '步骤 2', relatedTab: 'evidences' },
  { stepKey: 'quality_screening', label: '质量筛查', badge: '步骤 3', relatedTab: 'evidences' },
  { stepKey: 'evidence_pool_building', label: '证据池构建', badge: '步骤 4', relatedTab: 'evidences' },
  { stepKey: 'knowledge_preparation', label: '知识准备', badge: '步骤 5', relatedTab: 'evidences' },
  { stepKey: 'committee_review', label: '委员会审查', badge: '步骤 6', relatedTab: 'committee' },
  { stepKey: 'editorial_synthesis', label: '合稿归并', badge: '步骤 7', relatedTab: 'rid' },
  { stepKey: 'chief_adjudication', label: '总师审定', badge: '步骤 8', relatedTab: 'decision' },
  { stepKey: 'human_arbitration', label: '人工仲裁（按需）', badge: '步骤 9', relatedTab: 'arbitration' },
  { stepKey: 'review_closure', label: '闭环报告', badge: '步骤 10', relatedTab: 'overview' },
] as const

export type GncFlowStepStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface GncFlowStepProjection {
  step_key: string
  label?: string
  status: GncFlowStepStatus | string
  completed?: boolean
  is_current?: boolean
  related_tab?: string
  duration_ms?: number | null
  error?: string
  subtitle?: string
  summary?: string
  metrics?: Record<string, unknown>
}

export interface GncFlowProjection {
  review_id: string
  status: string
  current_step: string
  workbench_phase?: string
  requires_arbitration?: boolean
  failed_step?: string
  error?: string
  steps: GncFlowStepProjection[]
}

export function resolveGncStepLabel(stepKey: string): string {
  return GNC_WORKFLOW_STEP_DEFS.find((step) => step.stepKey === stepKey)?.label || stepKey
}

export function formatDurationMs(durationMs?: number | null): string {
  if (durationMs == null || durationMs < 0) return '—'
  if (durationMs < 1000) return `${durationMs} ms`
  const seconds = durationMs / 1000
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  const remain = Math.round(seconds % 60)
  return remain ? `${minutes} m ${remain} s` : `${minutes} m`
}
