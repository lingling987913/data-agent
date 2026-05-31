import { describe, expect, it } from 'vitest'
import { mergePostParseClassification } from '@/features/super-agent/utils/mergePostParseClassification'
import type { MaterialClassification } from '@/features/super-agent/types'

const base: MaterialClassification = {
  doc_type: '设计报告',
  domain: '综合',
  recommended_route: 'smart',
  reason: 'initial',
  initial_recommended_route: 'smart',
}

describe('mergePostParseClassification', () => {
  it('merges post_parse fields from preview classification', () => {
    const merged = mergePostParseClassification(base, {
      ...base,
      recommended_route: 'gnc_review_only',
      final_recommended_route: 'gnc_review_only',
      route_decision_source: 'post_parse',
      post_parse_route: {
        suggested_route: 'gnc_review_only',
        effective_route: 'gnc_review_only',
        changed_from_initial: true,
        initial_route: 'smart',
        reasons: ['GNC 信号'],
      },
    })
    expect(merged?.final_recommended_route).toBe('gnc_review_only')
    expect(merged?.post_parse_route?.changed_from_initial).toBe(true)
    expect(merged?.initial_recommended_route).toBe('smart')
  })

  it('returns preview-only classification when base is null', () => {
    const preview = { ...base, recommended_route: 'review_plus' }
    expect(mergePostParseClassification(null, preview)?.recommended_route).toBe('review_plus')
  })
})
