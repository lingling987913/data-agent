import { describe, expect, it } from 'vitest'
import {
  BUCKET_MISSING_DETAIL_HINT,
  filterConclusionItemsByBucket,
  mergeFindingsConclusionItems,
  sortConclusionItemsByBucket,
  toggleBucketFilter,
} from '@/features/unified-review-workbench/utils/findingsBucketFilter'

describe('findingsBucketFilter', () => {
  const findings = [
    { finding_id: 'f-1', business_bucket: 'severe_error', title: '严重项' },
    { finding_id: 'f-2', business_bucket: 'verified', title: '已通过项' },
  ]
  const checkItems = [
    { check_item_id: 'c-1', business_bucket: 'content_nonconforming', title: '内容问题' },
    { check_item_id: 'c-2', business_bucket: 'verified', title: '已通过检查项' },
  ]
  const evidences = [
    { evidence_id: 'e-1', business_bucket: 'insufficient_evidence', quote: '缺证据摘录' },
  ]

  it('merges findings, check items and evidences without duplicate ids', () => {
    const merged = mergeFindingsConclusionItems(findings, checkItems, evidences)
    expect(merged).toHaveLength(5)
    expect(mergeFindingsConclusionItems(findings, checkItems, findings)).toHaveLength(4)
  })

  it('sorts items by business bucket risk priority', () => {
    const merged = mergeFindingsConclusionItems(findings, checkItems, evidences)
    const sorted = sortConclusionItemsByBucket(merged)
    expect(sorted.map((item) => item.business_bucket)).toEqual([
      'severe_error',
      'content_nonconforming',
      'insufficient_evidence',
      'verified',
      'verified',
    ])
  })

  it('filters items by selected bucket', () => {
    const merged = mergeFindingsConclusionItems(findings, checkItems, evidences)
    const sorted = sortConclusionItemsByBucket(merged)
    const verified = filterConclusionItemsByBucket(sorted, 'verified')
    expect(verified).toHaveLength(2)
    expect(filterConclusionItemsByBucket(sorted, null)).toHaveLength(5)
    expect(filterConclusionItemsByBucket(sorted, 'severe_error')[0].finding_id).toBe('f-1')
  })

  it('toggles bucket filter on repeated click', () => {
    expect(toggleBucketFilter(null, 'verified')).toBe('verified')
    expect(toggleBucketFilter('verified', 'verified')).toBeNull()
    expect(toggleBucketFilter('severe_error', 'verified')).toBe('verified')
  })

  it('exposes Chinese hint for stat-only buckets', () => {
    expect(BUCKET_MISSING_DETAIL_HINT).toContain('缺少明细')
    expect(BUCKET_MISSING_DETAIL_HINT).not.toMatch(/bucket|verified|severe/i)
  })
})
