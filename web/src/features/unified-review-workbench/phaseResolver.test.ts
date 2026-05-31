import { describe, expect, it } from 'vitest'
import {
  parseReviewTypeParam,
  requiresArbitrationLanding,
  resolveDefaultTab,
  resolvePhaseLabel,
} from '@/features/unified-review-workbench/phaseResolver'
import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'

function mockDetail(
  overrides: Partial<UnifiedReviewWorkbenchDetail> = {},
): UnifiedReviewWorkbenchDetail {
  return {
    review_id: 'review-1',
    name: 'Review 1',
    review_type: 'gnc',
    status: 'running',
    workbench_phase: 'executing',
    visible_tabs: ['overview', 'flow', 'rid', 'decision'],
    current_step: '',
    metrics: {
      finding_count: 0,
      rid_count: 0,
      open_rid_count: 0,
      evidence_count: 0,
      conflict_count: 0,
      requires_arbitration: false,
    },
    summary: {
      verdict: '',
      rationale: '',
      requires_arbitration: false,
      arbitration_status: '',
      report_available: false,
    },
    error: '',
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

describe('resolvePhaseLabel', () => {
  it('maps known phases and falls back to raw value', () => {
    expect(resolvePhaseLabel('executing')).toBe('执行中')
    expect(resolvePhaseLabel('unknown_phase')).toBe('unknown_phase')
  })
})

describe('parseReviewTypeParam', () => {
  it('normalizes review type aliases', () => {
    expect(parseReviewTypeParam('gnc-review')).toBe('gnc')
    expect(parseReviewTypeParam('review-plus')).toBe('review_plus')
    expect(parseReviewTypeParam('')).toBeNull()
  })
})

describe('resolveDefaultTab', () => {
  it('prioritizes a valid initialTab hint over phase defaults', () => {
    expect(resolveDefaultTab(
      mockDetail({ workbench_phase: 'completed', metrics: { ...mockDetail().metrics, open_rid_count: 3 } }),
      'overview',
    )).toBe('overview')
  })

  it('ignores an invalid initialTab hint', () => {
    expect(resolveDefaultTab(
      mockDetail({ workbench_phase: 'completed' }),
      'not-a-tab',
    )).toBe('decision')
  })

  it('opens materials during pre_review', () => {
    expect(resolveDefaultTab(mockDetail({
      workbench_phase: 'pre_review',
      visible_tabs: ['overview', 'materials', 'flow'],
    }))).toBe('materials')
  })

  it('opens arbitration during arbitration phase', () => {
    expect(resolveDefaultTab(mockDetail({
      workbench_phase: 'arbitration',
      visible_tabs: ['overview', 'arbitration'],
    }))).toBe('arbitration')
  })

  it('requiresArbitrationLanding aligns with super agent pending arbitration', () => {
    expect(requiresArbitrationLanding(mockDetail({
      workbench_phase: 'executing',
      status: 'running',
      summary: { ...mockDetail().summary, requires_arbitration: true, arbitration_status: 'pending' },
      metrics: { ...mockDetail().metrics, requires_arbitration: true },
    }))).toBe(true)
    expect(requiresArbitrationLanding(mockDetail({
      summary: { ...mockDetail().summary, requires_arbitration: true, arbitration_status: 'resolved' },
      metrics: { ...mockDetail().metrics, requires_arbitration: true },
    }))).toBe(false)
  })

  it('opens arbitration when requires_arbitration is pending outside arbitration phase', () => {
    expect(resolveDefaultTab(mockDetail({
      workbench_phase: 'executing',
      visible_tabs: ['overview', 'flow', 'arbitration', 'decision'],
      summary: { ...mockDetail().summary, requires_arbitration: true, arbitration_status: 'pending' },
      metrics: { ...mockDetail().metrics, requires_arbitration: true },
    }))).toBe('arbitration')
  })

  it('opens overview/decision when arbitration is resolved', () => {
    expect(resolveDefaultTab(mockDetail({
      workbench_phase: 'executing',
      visible_tabs: ['overview', 'flow', 'arbitration', 'decision'],
      summary: { ...mockDetail().summary, requires_arbitration: true, arbitration_status: 'resolved' },
      metrics: { ...mockDetail().metrics, requires_arbitration: true },
    }))).toBe('overview')
  })

  it('opens rid for completed gnc when open RID exists', () => {
    expect(resolveDefaultTab(mockDetail({
      workbench_phase: 'completed',
      review_type: 'gnc',
      metrics: { ...mockDetail().metrics, open_rid_count: 2 },
      visible_tabs: ['overview', 'rid', 'decision'],
    }))).toBe('rid')
  })

  it('opens decision for completed gnc without open RID', () => {
    expect(resolveDefaultTab(mockDetail({
      workbench_phase: 'completed',
      review_type: 'gnc',
      visible_tabs: ['overview', 'rid', 'decision'],
    }))).toBe('decision')
  })

  it('falls back when completed gnc targets are not visible', () => {
    expect(resolveDefaultTab(mockDetail({
      workbench_phase: 'completed',
      review_type: 'gnc',
      visible_tabs: ['overview', 'flow'],
    }))).toBe('overview')
  })

  it('opens report for completed review_plus with report_available', () => {
    expect(resolveDefaultTab(mockDetail({
      workbench_phase: 'completed',
      review_type: 'review_plus',
      summary: { ...mockDetail().summary, report_available: true },
      visible_tabs: ['overview', 'report', 'findings'],
    }))).toBe('report')
  })

  it('defaults to overview during executing phase', () => {
    expect(resolveDefaultTab(mockDetail({
      workbench_phase: 'executing',
      visible_tabs: ['overview', 'flow'],
    }))).toBe('overview')
  })
})
