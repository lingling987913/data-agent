import type { UnifiedReviewType, UnifiedReviewWorkbenchDetail, UnifiedWorkbenchPhase, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export const PHASE_LABELS: Record<UnifiedWorkbenchPhase, string> = {
  pre_review: '送审准备',
  startup: '启动中',
  executing: '执行中',
  arbitration: '待仲裁',
  completed: '已完成',
  failed: '失败',
}

export function resolvePhaseLabel(phase: UnifiedWorkbenchPhase | string): string {
  return PHASE_LABELS[phase as UnifiedWorkbenchPhase] || phase
}

const RESOLVED_ARBITRATION_STATUSES = new Set(['resolved', 'completed'])

export function requiresArbitrationLanding(detail: UnifiedReviewWorkbenchDetail): boolean {
  const status = String(detail.status || '').toLowerCase()
  const phase = detail.workbench_phase
  const arbitrationStatus = String(detail.summary.arbitration_status || '').toLowerCase()
  const requiresArbitration = Boolean(
    detail.metrics.requires_arbitration || detail.summary.requires_arbitration,
  )

  if (phase === 'arbitration') return true
  if (status.includes('arbitration')) return true
  if (arbitrationStatus === 'pending') return true
  if (
    requiresArbitration
    && !RESOLVED_ARBITRATION_STATUSES.has(arbitrationStatus)
  ) {
    return true
  }
  return false
}

export function resolveDefaultTab(
  detail: UnifiedReviewWorkbenchDetail,
  initialTab?: string,
): UnifiedWorkbenchTabKey {
  const visible = detail.visible_tabs as UnifiedWorkbenchTabKey[]
  if (initialTab && visible.includes(initialTab as UnifiedWorkbenchTabKey)) {
    return initialTab as UnifiedWorkbenchTabKey
  }
  if (detail.workbench_phase === 'pre_review') {
    return visible.includes('materials') ? 'materials' : (visible[0] || 'overview')
  }
  if (
    detail.review_type === 'gnc'
    && requiresArbitrationLanding(detail)
    && visible.includes('arbitration')
  ) {
    return 'arbitration'
  }
  if (detail.review_type === 'super_agent') {
    return visible.includes('overview') ? 'overview' : (visible[0] || 'overview')
  }
  if (detail.workbench_phase === 'completed') {
    if (detail.review_type === 'gnc') {
      if (detail.metrics.open_rid_count > 0 && visible.includes('rid')) {
        return 'rid'
      }
      if (visible.includes('decision')) {
        return 'decision'
      }
    }
    if (
      detail.review_type === 'review_plus'
      && (detail.summary.report_available || detail.status === 'completed')
      && visible.includes('report')
    ) {
      return 'report'
    }
  }
  return visible.includes('overview') ? 'overview' : (visible[0] || 'overview')
}

export function parseReviewTypeParam(value: string | null): UnifiedReviewType | null {
  const normalized = (value || '').trim().toLowerCase()
  if (normalized === 'gnc' || normalized === 'gnc-review') return 'gnc'
  if (normalized === 'review_plus' || normalized === 'review-plus' || normalized === 'reviewplus') {
    return 'review_plus'
  }
  if (normalized === 'super_agent' || normalized === 'super-agent' || normalized === 'superagent') {
    return 'super_agent'
  }
  return null
}
