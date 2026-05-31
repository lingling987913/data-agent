import {
  BUSINESS_BUCKET_LABELS,
  BUSINESS_BUCKET_ORDER,
  type BusinessBucketKey,
} from '@/features/unified-review-workbench/utils/conclusionOverviewModel'
import { normalizeBucketKey, resolveItemBucketKey } from '@/features/unified-review-workbench/utils/bucketTone'

export const BUCKET_MISSING_DETAIL_HINT =
  '该分桶有统计但缺少明细，请查看结论与闭环/运行质量或补充后端明细投影'

function itemDedupeKey(item: Record<string, unknown>): string {
  const id = String(item.finding_id || item.check_item_id || item.evidence_id || item.id || '').trim()
  if (id) return id
  const title = String(item.title || item.description || item.quote || '').trim()
  return title || JSON.stringify(item)
}

/** 合并 findings / check_items / evidences，按 id 去重 */
export function mergeFindingsConclusionItems(
  findings: Array<Record<string, unknown>>,
  checkItems: Array<Record<string, unknown>>,
  evidences: Array<Record<string, unknown>> = [],
): Array<Record<string, unknown>> {
  const seen = new Set<string>()
  const merged: Array<Record<string, unknown>> = []
  for (const item of [...findings, ...checkItems, ...evidences]) {
    const key = itemDedupeKey(item)
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

export function bucketSortIndex(bucketKey: string): number {
  const normalized = normalizeBucketKey(bucketKey)
  const idx = BUSINESS_BUCKET_ORDER.indexOf(normalized as BusinessBucketKey)
  return idx >= 0 ? idx : BUSINESS_BUCKET_ORDER.length
}

/** 按业务分桶风险优先级排序（严重错误 → … → 已通过） */
export function sortConclusionItemsByBucket<T extends Record<string, unknown>>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const bucketDiff = bucketSortIndex(resolveItemBucketKey(a)) - bucketSortIndex(resolveItemBucketKey(b))
    if (bucketDiff !== 0) return bucketDiff
    const titleA = String(a.title || a.description || a.quote || '')
    const titleB = String(b.title || b.description || b.quote || '')
    return titleA.localeCompare(titleB, 'zh-CN')
  })
}

/** 按分桶 key 过滤；bucket 为 null 时返回全部 */
export function filterConclusionItemsByBucket<T extends Record<string, unknown>>(
  items: T[],
  bucket: string | null | undefined,
): T[] {
  if (!bucket) return items
  const target = normalizeBucketKey(bucket)
  return items.filter((item) => normalizeBucketKey(resolveItemBucketKey(item)) === target)
}

export function countConclusionItemsByBucket(
  items: Array<Record<string, unknown>>,
): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const item of items) {
    const key = normalizeBucketKey(resolveItemBucketKey(item))
    if (!key) continue
    counts[key] = (counts[key] || 0) + 1
  }
  return counts
}

export function resolveBucketFilterLabel(bucketKey: string): string {
  const normalized = normalizeBucketKey(bucketKey)
  if (normalized && normalized in BUSINESS_BUCKET_LABELS) {
    return BUSINESS_BUCKET_LABELS[normalized as BusinessBucketKey]
  }
  return bucketKey
}

/** 点击分桶 toggle：再次点击同一 bucket 则清除筛选 */
export function toggleBucketFilter(
  current: string | null,
  clicked: string,
): string | null {
  const normalized = normalizeBucketKey(clicked)
  if (!normalized) return current
  return current === normalized ? null : normalized
}
