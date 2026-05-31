import { describe, expect, it } from 'vitest'
import {
  BUCKET_TONE_MAP,
  bucketBadgeClass,
  bucketListItemClass,
  bucketToneClass,
  normalizeBucketKey,
  resolveConclusionBadge,
  resolveItemBucketKey,
} from '@/features/unified-review-workbench/utils/bucketTone'

describe('bucketTone', () => {
  it('maps each business bucket to distinct card/badge/listItem classes', () => {
    const keys = Object.keys(BUCKET_TONE_MAP)
    const cardClasses = keys.map((key) => bucketToneClass(key))
    const badgeClasses = keys.map((key) => bucketBadgeClass(key))
    expect(new Set(cardClasses).size).toBe(keys.length)
    expect(new Set(badgeClasses).size).toBe(keys.length)
  })

  it('uses semantic colors per bucket', () => {
    expect(bucketToneClass('severe_error')).toContain('red')
    expect(bucketToneClass('content_nonconforming')).toContain('orange')
    expect(bucketToneClass('template_structure_nonconforming')).toContain('amber')
    expect(bucketToneClass('cross_document_inconsistency')).toContain('purple')
    expect(bucketToneClass('insufficient_evidence')).toContain('blue')
    expect(bucketToneClass('manual_review')).toContain('slate')
    expect(bucketToneClass('verified')).toContain('emerald')
  })

  it('normalizes legacy status aliases to bucket keys', () => {
    expect(normalizeBucketKey('critical')).toBe('severe_error')
    expect(normalizeBucketKey('evidence_supported')).toBe('verified')
    expect(normalizeBucketKey('blocked')).toBe('insufficient_evidence')
  })

  it('resolves bucket key from check item fields', () => {
    expect(resolveItemBucketKey({ business_bucket: 'cross_document_inconsistency' }))
      .toBe('cross_document_inconsistency')
    expect(resolveItemBucketKey({ conclusion_bucket: 'verified', status: 'open' }))
      .toBe('verified')
  })

  it('prefers Chinese bucket label for conclusion badges', () => {
    const { bucketKey, label } = resolveConclusionBadge({
      business_bucket: 'cross_document_inconsistency',
      business_bucket_label: '文文不一致',
    })
    expect(bucketKey).toBe('cross_document_inconsistency')
    expect(label).toBe('文文不一致')
    expect(bucketBadgeClass(bucketKey)).toContain('purple')
  })

  it('falls back to Chinese bucket label when only English bucket key is present', () => {
    const { bucketKey, label } = resolveConclusionBadge({
      business_bucket: 'insufficient_evidence',
      status: 'blocked',
    })
    expect(bucketKey).toBe('insufficient_evidence')
    expect(label).toBe('证据不足/无法印证')
    expect(label).not.toContain('insufficient_evidence')
  })

  it('maps legacy severity aliases to Chinese labels', () => {
    const { label } = resolveConclusionBadge({ severity: 'critical', title: '示例' })
    expect(label).toBe('严重错误')
  })

  it('applies list item accent classes for priority rendering', () => {
    expect(bucketListItemClass('severe_error')).toContain('border-l-red-600')
    expect(bucketListItemClass('verified')).toContain('border-l-emerald-600')
  })
})
