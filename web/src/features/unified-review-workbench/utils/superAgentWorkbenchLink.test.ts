import { describe, expect, it } from 'vitest'
import {
  buildSuperAgentRunWorkbenchHref,
  buildSuperAgentWorkbenchHref,
  defaultWorkbenchTabForRun,
  resolveSuperAgentWorkbenchReviewId,
  resolveSuperAgentWorkbenchReviewType,
} from '@/features/unified-review-workbench/utils/superAgentWorkbenchLink'
import type { SuperAgentRun } from '@/features/super-agent/types'

function minimalRun(overrides: Partial<SuperAgentRun>): SuperAgentRun {
  return {
    run_id: 'run-1',
    source_review_id: 'rev-1',
    status: 'completed',
    route_decision: { route: 'gnc_review_only' },
    gnc_review_result: {},
    review_plus_result: {},
    ...overrides,
  } as SuperAgentRun
}

describe('superAgentWorkbenchLink', () => {
  it('resolveSuperAgentWorkbenchReviewType prefers explicit route', () => {
    expect(resolveSuperAgentWorkbenchReviewType(minimalRun({
      route_decision: { route: 'review_plus' } as SuperAgentRun['route_decision'],
      gnc_review_result: { status: 'completed' },
    }))).toBe('review_plus')
  })

  it('uses generated GNC review id for Super Agent GNC runs', () => {
    const run = minimalRun({
      source_review_id: '',
      route_decision: {
        route: 'gnc_review_only',
        gnc_review_id: 'gnc-42',
      } as SuperAgentRun['route_decision'],
      gnc_review_result: { status: 'completed', review_id: 'gnc-result-fallback' },
    })

    expect(resolveSuperAgentWorkbenchReviewType(run)).toBe('gnc')
    expect(resolveSuperAgentWorkbenchReviewId(run)).toBe('gnc-42')
    expect(buildSuperAgentWorkbenchHref(run)).toContain('reviewType=gnc')
    expect(buildSuperAgentWorkbenchHref(run)).toContain('reviewId=gnc-42')
    expect(buildSuperAgentRunWorkbenchHref(run)).toContain('reviewType=super_agent')
    expect(buildSuperAgentRunWorkbenchHref(run)).toContain('reviewId=run-1')
  })

  it('falls back to GNC result id when route decision does not carry one', () => {
    const run = minimalRun({
      source_review_id: '',
      route_decision: { route: 'smart' } as SuperAgentRun['route_decision'],
      gnc_review_result: { status: 'completed', gnc_review_id: 'gnc-from-result' },
      review_plus_result: {},
    })

    expect(resolveSuperAgentWorkbenchReviewType(run)).toBe('gnc')
    expect(resolveSuperAgentWorkbenchReviewId(run)).toBe('gnc-from-result')
  })

  it('uses Review-Plus result id for Review-Plus and smart Review-Plus runs', () => {
    const run = minimalRun({
      source_review_id: 'source-rp',
      route_decision: { route: 'smart' } as SuperAgentRun['route_decision'],
      review_plus_result: { review_plus_id: 'rp-result', status: 'completed' },
      gnc_review_result: {},
    })

    expect(resolveSuperAgentWorkbenchReviewType(run)).toBe('review_plus')
    expect(resolveSuperAgentWorkbenchReviewId(run)).toBe('rp-result')
    expect(buildSuperAgentWorkbenchHref(run)).toContain('reviewType=review_plus')
    expect(buildSuperAgentWorkbenchHref(run)).toContain('reviewId=rp-result')
    expect(buildSuperAgentRunWorkbenchHref(run)).toContain('reviewType=super_agent')
    expect(buildSuperAgentRunWorkbenchHref(run)).toContain('reviewId=run-1')
  })

  it('uses native Super Agent workbench for smart committee results without delegated review id', () => {
    const run = minimalRun({
      source_review_id: '',
      route_decision: { route: 'smart' } as SuperAgentRun['route_decision'],
      review_plus_result: {
        status: 'completed',
        review_mode: 'smart_committee',
        specialist_reviews: [],
      },
      gnc_review_result: {},
      report_markdown: '# Report',
    })

    expect(resolveSuperAgentWorkbenchReviewType(run)).toBe('super_agent')
    expect(resolveSuperAgentWorkbenchReviewId(run)).toBe('run-1')
    expect(buildSuperAgentWorkbenchHref(run)).toContain('reviewType=super_agent')
    expect(buildSuperAgentWorkbenchHref(run)).toContain('reviewId=run-1')
    expect(buildSuperAgentRunWorkbenchHref(run)).toContain('reviewType=super_agent')
    expect(buildSuperAgentRunWorkbenchHref(run)).toContain('reviewId=run-1')
  })

  it('defaultWorkbenchTabForRun opens arbitration when pending', () => {
    expect(defaultWorkbenchTabForRun(minimalRun({
      gnc_review_result: { status: 'running', workbench_phase: 'arbitration', requires_arbitration: true },
    }))).toBe('arbitration')
  })

  it('defaultWorkbenchTabForRun opens decision or rid when completed', () => {
    expect(defaultWorkbenchTabForRun(minimalRun({
      gnc_review_result: { status: 'completed', workbench_phase: 'completed' },
    }))).toBe('decision')
    expect(defaultWorkbenchTabForRun(minimalRun({
      gnc_review_result: { status: 'completed', open_rid_count: 2 },
    }))).toBe('rid')
  })

  it('defaultWorkbenchTabForRun opens report for completed review plus', () => {
    expect(defaultWorkbenchTabForRun(minimalRun({
      route_decision: { route: 'review_plus' } as SuperAgentRun['route_decision'],
      gnc_review_result: {},
      review_plus_result: { status: 'completed', report: { markdown: '# R' } },
    }))).toBe('report')
  })
})
