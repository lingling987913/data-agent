import { resolveDefaultTab } from '@/features/unified-review-workbench/phaseResolver'
import { normalizeSuperAgentTabKey } from '@/features/unified-review-workbench/utils/superAgentTabAlias'
import type {
  UnifiedReviewWorkbenchDetail,
  UnifiedWorkbenchTabKey,
} from '@/features/unified-review-workbench/types'

export type WorkbenchTabResolveMode = 'initial' | 'reload' | 'url_sync'

export interface ResolveActiveWorkbenchTabInput {
  visibleTabs: readonly string[]
  detail: UnifiedReviewWorkbenchDetail
  urlTab?: string | null
  currentTab?: UnifiedWorkbenchTabKey
  mode: WorkbenchTabResolveMode
}

function isVisibleTab(
  visibleTabs: readonly string[],
  tab: string,
): tab is UnifiedWorkbenchTabKey {
  return visibleTabs.includes(tab)
}

function normalizeUrlTab(
  detail: UnifiedReviewWorkbenchDetail,
  tab: string,
): string {
  if (detail.review_type === 'super_agent') {
    return normalizeSuperAgentTabKey(tab) || tab
  }
  return tab
}

export function resolveActiveWorkbenchTab({
  visibleTabs,
  detail,
  urlTab,
  currentTab,
  mode,
}: ResolveActiveWorkbenchTabInput): UnifiedWorkbenchTabKey {
  const normalizedUrlTab = normalizeUrlTab(detail, (urlTab || '').trim())

  if (
    (mode === 'initial' || mode === 'url_sync')
    && normalizedUrlTab
    && isVisibleTab(visibleTabs, normalizedUrlTab)
  ) {
    return normalizedUrlTab as UnifiedWorkbenchTabKey
  }

  if (mode === 'reload' && currentTab && isVisibleTab(visibleTabs, currentTab)) {
    return currentTab
  }

  const initialTabHint = mode === 'initial' && normalizedUrlTab ? normalizedUrlTab : undefined
  return resolveDefaultTab(detail, initialTabHint ? normalizeUrlTab(detail, initialTabHint) : undefined)
}
