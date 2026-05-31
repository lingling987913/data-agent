import { normalizeBucketKey } from '@/features/unified-review-workbench/utils/bucketTone'
import type { UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export const WORKBENCH_BUCKET_QUERY = 'bucket'
export const WORKBENCH_HINT_QUERY = 'hint'

export function readWorkbenchBucketParam(
  searchParams: URLSearchParams | string | null | undefined,
): string | null {
  if (!searchParams) return null
  const params = typeof searchParams === 'string'
    ? new URLSearchParams(searchParams)
    : searchParams
  const raw = (params.get(WORKBENCH_BUCKET_QUERY) || '').trim()
  if (!raw) return null
  return normalizeBucketKey(raw) || null
}

export function readWorkbenchHintParam(
  searchParams: URLSearchParams | string | null | undefined,
): string {
  if (!searchParams) return ''
  const params = typeof searchParams === 'string'
    ? new URLSearchParams(searchParams)
    : searchParams
  return (params.get(WORKBENCH_HINT_QUERY) || '').trim()
}

export interface BuildWorkbenchNavigateHrefInput {
  pathname: string
  searchParams: URLSearchParams | string
  tab: UnifiedWorkbenchTabKey
  bucket?: string | null
  hint?: string | null
  preserveOtherParams?: boolean
}

/** 构建带 tab / bucket / hint 的工作台深链 */
export function buildWorkbenchNavigateHref({
  pathname,
  searchParams,
  tab,
  bucket,
  hint,
  preserveOtherParams = true,
}: BuildWorkbenchNavigateHrefInput): string {
  const base = preserveOtherParams
    ? new URLSearchParams(typeof searchParams === 'string' ? searchParams : searchParams.toString())
    : new URLSearchParams()
  base.set('tab', tab)
  const normalizedBucket = bucket ? normalizeBucketKey(bucket) || bucket : null
  if (normalizedBucket) {
    base.set(WORKBENCH_BUCKET_QUERY, normalizedBucket)
  } else {
    base.delete(WORKBENCH_BUCKET_QUERY)
  }
  if (hint?.trim()) {
    base.set(WORKBENCH_HINT_QUERY, hint.trim())
  } else {
    base.delete(WORKBENCH_HINT_QUERY)
  }
  const query = base.toString()
  return query ? `${pathname}?${query}` : pathname
}

/** findings 以外 Tab 时是否应清除 bucket 查询参数 */
export function shouldClearBucketOnTab(tab: UnifiedWorkbenchTabKey): boolean {
  return tab !== 'findings'
}
