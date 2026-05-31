import { filterTabsForReviewType } from '@/features/unified-review-workbench/tabRegistry'
import type { UnifiedReviewType, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export interface OpenTabGuardResult {
  allowed: boolean
  reason?: 'not_visible' | 'no_detail'
}

export function isOpenableWorkbenchTab(
  visibleTabs: readonly string[],
  reviewType: UnifiedReviewType,
  tab: string,
): tab is UnifiedWorkbenchTabKey {
  return filterTabsForReviewType([...visibleTabs], reviewType).includes(tab as UnifiedWorkbenchTabKey)
}

export function guardWorkbenchOpenTab(
  visibleTabs: readonly string[] | undefined,
  reviewType: UnifiedReviewType,
  tab: UnifiedWorkbenchTabKey,
): OpenTabGuardResult {
  if (!visibleTabs?.length) {
    return { allowed: false, reason: 'no_detail' }
  }
  if (!isOpenableWorkbenchTab(visibleTabs, reviewType, tab)) {
    return { allowed: false, reason: 'not_visible' }
  }
  return { allowed: true }
}

export function shouldSanitizeWorkbenchUrlTab(
  urlTab: string | null | undefined,
  activeTab: UnifiedWorkbenchTabKey,
  visibleTabs: readonly string[],
  reviewType: UnifiedReviewType,
): boolean {
  const normalized = (urlTab || '').trim()
  if (!normalized) return false
  if (normalized === activeTab) return false
  return !isOpenableWorkbenchTab(visibleTabs, reviewType, normalized)
}

export function buildWorkbenchTabHref(
  pathname: string,
  searchParams: URLSearchParams | string,
  tab: UnifiedWorkbenchTabKey,
): string {
  const params = new URLSearchParams(typeof searchParams === 'string' ? searchParams : searchParams.toString())
  params.set('tab', tab)
  const query = params.toString()
  return query ? `${pathname}?${query}` : pathname
}

export const INVALID_URL_TAB_SANITIZE_HINT = '链接 Tab 不可用，已打开默认页'

export function resolveInvalidUrlTabSanitizeHint(
  urlTab: string | null | undefined,
  activeTab: UnifiedWorkbenchTabKey,
  visibleTabs: readonly string[],
  reviewType: UnifiedReviewType,
): string | null {
  return shouldSanitizeWorkbenchUrlTab(urlTab, activeTab, visibleTabs, reviewType)
    ? INVALID_URL_TAB_SANITIZE_HINT
    : null
}

/** Tracks which invalid ?tab= values already triggered a user hint (avoids reload/back spam). */
export class InvalidUrlTabHintTracker {
  private shown = new Set<string>()

  reset(): void {
    this.shown.clear()
  }

  shouldNotify(invalidTab: string | null | undefined): boolean {
    const key = (invalidTab || '').trim()
    if (!key || this.shown.has(key)) return false
    this.shown.add(key)
    return true
  }
}
