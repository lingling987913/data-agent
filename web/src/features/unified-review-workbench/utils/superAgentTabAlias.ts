import type { UnifiedReviewType, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

/** Legacy Super Agent deep-link keys mapped to the six business tabs. */
const SUPER_AGENT_LEGACY_TAB_ALIASES: Record<string, UnifiedWorkbenchTabKey> = {
  flow: 'routes',
  committee: 'routes',
  events: 'routes',
  decision: 'closure',
  report: 'closure',
  evidences: 'findings',
  check_items: 'findings',
}

const SUPER_AGENT_TAB_LABELS: Record<UnifiedWorkbenchTabKey, string> = {
  overview: '总览',
  materials: '材料与底稿',
  routes: '审查路线',
  findings: '发现与证据',
  closure: '结论与闭环',
  quality: '运行质量',
  flow: '审查路线',
  committee: '审查路线',
  events: '审查路线',
  check_items: '发现与证据',
  evidences: '发现与证据',
  decision: '结论与闭环',
  report: '结论与闭环',
  coverage: '覆盖矩阵',
  traceability: '需求追溯',
  cross_doc: '跨文档',
  rid: 'RID 台账',
  minutes: '审查纪要',
  arbitration: '人工仲裁',
}

export function normalizeSuperAgentTabKey(
  tab: string | null | undefined,
): UnifiedWorkbenchTabKey | null {
  const normalized = (tab || '').trim()
  if (!normalized) return null
  return SUPER_AGENT_LEGACY_TAB_ALIASES[normalized] || (normalized as UnifiedWorkbenchTabKey)
}

export function resolveSuperAgentTabLabel(key: string): string {
  const canonical = normalizeSuperAgentTabKey(key) || key
  return SUPER_AGENT_TAB_LABELS[canonical as UnifiedWorkbenchTabKey] || key
}

export function normalizeSuperAgentVisibleTabs(visibleTabs: readonly string[]): UnifiedWorkbenchTabKey[] {
  const seen = new Set<UnifiedWorkbenchTabKey>()
  const ordered: UnifiedWorkbenchTabKey[] = []
  for (const raw of visibleTabs) {
    const mapped = normalizeSuperAgentTabKey(raw)
    if (!mapped || seen.has(mapped)) continue
    seen.add(mapped)
    ordered.push(mapped)
  }
  const preferred: UnifiedWorkbenchTabKey[] = [
    'overview',
    'materials',
    'routes',
    'findings',
    'closure',
    'quality',
  ]
  return preferred.filter((tab) => seen.has(tab)).concat(
    ordered.filter((tab) => !preferred.includes(tab)),
  )
}

export function isSuperAgentReviewType(reviewType: UnifiedReviewType): boolean {
  return reviewType === 'super_agent'
}
