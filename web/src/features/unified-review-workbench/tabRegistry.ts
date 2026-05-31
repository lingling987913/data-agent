import { normalizeSuperAgentVisibleTabs } from '@/features/unified-review-workbench/utils/superAgentTabAlias'
import type { UnifiedReviewType, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export interface UnifiedTabDefinition {
  key: UnifiedWorkbenchTabKey
  label: string
  reviewTypes: UnifiedReviewType[] | 'all'
}

export const UNIFIED_TAB_REGISTRY: UnifiedTabDefinition[] = [
  { key: 'overview', label: '总览', reviewTypes: 'all' },
  { key: 'flow', label: '流程', reviewTypes: ['gnc', 'review_plus'] },
  { key: 'materials', label: '送审材料', reviewTypes: ['gnc', 'review_plus'] },
  { key: 'materials', label: '材料与底稿', reviewTypes: ['super_agent'] },
  { key: 'routes', label: '审查路线', reviewTypes: ['super_agent'] },
  { key: 'check_items', label: '检查项', reviewTypes: ['review_plus'] },
  { key: 'findings', label: '审查发现', reviewTypes: ['gnc', 'review_plus'] },
  { key: 'findings', label: '发现与证据', reviewTypes: ['super_agent'] },
  { key: 'closure', label: '结论与闭环', reviewTypes: ['super_agent'] },
  { key: 'quality', label: '运行质量', reviewTypes: ['super_agent'] },
  { key: 'coverage', label: '覆盖矩阵', reviewTypes: ['review_plus'] },
  { key: 'traceability', label: '需求追溯', reviewTypes: ['review_plus'] },
  { key: 'cross_doc', label: '跨文档', reviewTypes: ['review_plus'] },
  { key: 'rid', label: 'RID 台账', reviewTypes: ['gnc'] },
  { key: 'evidences', label: '证据链', reviewTypes: ['gnc'] },
  { key: 'committee', label: '专家意见', reviewTypes: ['gnc'] },
  { key: 'minutes', label: '审查纪要', reviewTypes: ['gnc'] },
  { key: 'decision', label: '总师裁定', reviewTypes: ['gnc'] },
  { key: 'arbitration', label: '人工仲裁', reviewTypes: ['gnc'] },
  { key: 'report', label: '报告', reviewTypes: ['gnc', 'review_plus'] },
  { key: 'events', label: '事件', reviewTypes: ['gnc', 'review_plus'] },
]

export function resolveTabLabel(key: string, reviewType?: UnifiedReviewType): string {
  const matches = UNIFIED_TAB_REGISTRY.filter((tab) => tab.key === key)
  if (reviewType) {
    const scoped = matches.find(
      (tab) => tab.reviewTypes === 'all' || tab.reviewTypes.includes(reviewType),
    )
    if (scoped) return scoped.label
  }
  return matches[0]?.label || key
}

export function filterTabsForReviewType(
  visibleTabs: string[],
  reviewType: UnifiedReviewType,
): UnifiedWorkbenchTabKey[] {
  const allowed = new Set<string>(
    UNIFIED_TAB_REGISTRY.filter(
      (tab) =>
        tab.reviewTypes === 'all'
        || tab.reviewTypes.includes(reviewType),
    ).map((tab) => tab.key),
  )
  if (reviewType === 'super_agent') {
    return normalizeSuperAgentVisibleTabs(visibleTabs).filter((key) => allowed.has(key))
  }
  const seen = new Set<string>()
  return visibleTabs.filter((key): key is UnifiedWorkbenchTabKey => {
    if (!allowed.has(key) || seen.has(key)) return false
    seen.add(key)
    return true
  })
}
