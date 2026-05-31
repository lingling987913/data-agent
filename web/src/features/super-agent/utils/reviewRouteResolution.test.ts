import { describe, expect, it } from 'vitest'
import type { MaterialClassification } from '@/features/super-agent/types'
import {
  mapReviewModeCardToRoute,
  recommendedReviewModeCard,
  resolveCheckpointRoute,
  resolveEffectiveRoute,
  resolveReviewStartRoute,
  routeForReviewModeCardChange,
} from '@/features/super-agent/utils/reviewRouteResolution'

function classification(overrides: Partial<MaterialClassification> = {}): MaterialClassification {
  return {
    doc_type: '设计报告',
    domain: '综合',
    recommended_route: 'smart',
    reason: 'test',
    ...overrides,
  }
}

describe('mapReviewModeCardToRoute', () => {
  it('maps three cards to execution routes', () => {
    expect(mapReviewModeCardToRoute('smart')).toBe('smart')
    expect(mapReviewModeCardToRoute('standard')).toBe('review_plus')
    expect(mapReviewModeCardToRoute('special')).toBe('gnc_review_only')
  })
})

describe('recommendedReviewModeCard', () => {
  it('maps gnc post-parse recommendation to special card', () => {
    expect(
      recommendedReviewModeCard(
        classification({ final_recommended_route: 'gnc_review_only' }),
      ),
    ).toBe('special')
  })

  it('maps review_plus recommendation to standard card', () => {
    expect(
      recommendedReviewModeCard(
        classification({ final_recommended_route: 'review_plus' }),
      ),
    ).toBe('standard')
  })

  it('maps smart / auto recommendation to smart card', () => {
    expect(
      recommendedReviewModeCard(
        classification({ final_recommended_route: 'smart' }),
      ),
    ).toBe('smart')
    expect(
      recommendedReviewModeCard(
        classification({ recommended_route: 'auto' }),
      ),
    ).toBe('smart')
  })
})

describe('resolveReviewStartRoute', () => {
  it('uses card route post-parse even when GNC was recommended', () => {
    const cls = classification({ final_recommended_route: 'gnc_review_only' })
    expect(resolveReviewStartRoute('smart', 'gnc_review_only', cls, true)).toBe('smart')
    expect(resolveReviewStartRoute('special', 'smart', cls, true)).toBe('gnc_review_only')
    expect(resolveReviewStartRoute('standard', 'smart', cls, true)).toBe('review_plus')
  })

  it('respects advanced dropdown pre-parse on smart card', () => {
    expect(resolveReviewStartRoute('smart', 'structure_only', null, false)).toBe('structure_only')
  })
})

describe('resolveEffectiveRoute', () => {
  it('does not passthrough post-parse recommendation for smart card', () => {
    const cls = classification({ final_recommended_route: 'gnc_review_only' })
    expect(resolveEffectiveRoute('smart', 'smart', cls, true)).toBe('smart')
  })

  it('uses classification hint pre-parse when dropdown is auto', () => {
    const cls = classification({ recommended_route: 'gnc_review_only' })
    expect(resolveEffectiveRoute('smart', 'auto', cls, false)).toBe('gnc_review_only')
  })
})

describe('resolveCheckpointRoute', () => {
  it('keeps dropdown for smart card', () => {
    expect(resolveCheckpointRoute('smart', 'structure_only')).toBe('structure_only')
  })

  it('forces card route for non-smart cards', () => {
    expect(resolveCheckpointRoute('special', 'auto')).toBe('gnc_review_only')
  })
})

describe('routeForReviewModeCardChange', () => {
  it('always sets explicit execution route from card', () => {
    expect(routeForReviewModeCardChange('smart')).toBe('smart')
    expect(routeForReviewModeCardChange('standard')).toBe('review_plus')
    expect(routeForReviewModeCardChange('special')).toBe('gnc_review_only')
  })
})
