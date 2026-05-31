import { REVIEW_PLUS_TERMS } from '@/lib/aeroTerminology'

/** 任务工作台 Tab：文件组审查-{任务名} */
export function formatReviewPlusTaskTabLabel(taskName?: string | null): string {
  const trimmed = (taskName || '').trim()
  if (!trimmed) return REVIEW_PLUS_TERMS.workbench
  return `${REVIEW_PLUS_TERMS.moduleLabel}-${trimmed}`
}

export function buildReviewPlusV2WorkbenchHref(
  reviewId: string,
  options?: {
    tab?: string
    action?: string
  },
): string {
  const params = new URLSearchParams({ reviewId })
  if (options?.tab) params.set('tab', options.tab)
  if (options?.action) params.set('action', options.action)
  return `/review-plus-v2?${params.toString()}`
}

/** 深度监控页 deep-link（含完整 Trace） */
export function buildReviewPlusV2SessionDeepLink(reviewId: string): string {
  return `/review-plus-v2/session/${reviewId}`
}

export function openReviewPlusV2WorkbenchTab(
  reviewId: string,
  options?: {
    tab?: string
    action?: string
    label?: string
    taskName?: string | null
  },
): string {
  return buildReviewPlusV2WorkbenchHref(reviewId, {
    tab: options?.tab,
    action: options?.action,
  })
}
