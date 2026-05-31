import type { UnifiedReviewType, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export function buildUnifiedReviewWorkbenchHref(
  reviewType: UnifiedReviewType,
  reviewId: string,
  options?: { tab?: UnifiedWorkbenchTabKey | string },
): string {
  const params = new URLSearchParams({
    reviewType,
    reviewId,
  })
  if (options?.tab) params.set('tab', options.tab)
  return `/review/workbench?${params.toString()}`
}

/** Review-Plus 兼容：仍可直接打开 V2 工作台 */
export function buildReviewPlusLegacyWorkbenchHref(
  reviewId: string,
  options?: { tab?: string },
): string {
  const params = new URLSearchParams({ reviewId })
  if (options?.tab) params.set('tab', options.tab)
  return `/review-plus-v2?${params.toString()}`
}
