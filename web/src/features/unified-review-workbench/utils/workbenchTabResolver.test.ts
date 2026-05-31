import { describe, expect, it } from 'vitest'
import { resolveActiveWorkbenchTab } from '@/features/unified-review-workbench/utils/workbenchTabResolver'
import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'

function mockDetail(
  visibleTabs: string[],
  workbenchPhase: UnifiedReviewWorkbenchDetail['workbench_phase'] = 'executing',
  overrides: Partial<UnifiedReviewWorkbenchDetail> = {},
): UnifiedReviewWorkbenchDetail {
  return {
    review_id: 'review-1',
    name: 'Review 1',
    review_type: 'gnc',
    status: 'running',
    workbench_phase: workbenchPhase,
    visible_tabs: visibleTabs,
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

describe('resolveActiveWorkbenchTab', () => {
  const visibleTabs = ['overview', 'flow', 'materials', 'findings', 'rid', 'events']

  it('prioritizes a valid deep-link tab on first load', () => {
    expect(resolveActiveWorkbenchTab({
      visibleTabs,
      detail: mockDetail(visibleTabs),
      urlTab: 'rid',
      currentTab: 'overview',
      mode: 'initial',
    })).toBe('rid')
  })

  it('falls back to the phase default when the deep-link tab is invalid', () => {
    expect(resolveActiveWorkbenchTab({
      visibleTabs,
      detail: mockDetail(visibleTabs),
      urlTab: 'not-a-tab',
      currentTab: 'overview',
      mode: 'initial',
    })).toBe('overview')
  })

  it('keeps the current tab on reload after the user switched tabs', () => {
    expect(resolveActiveWorkbenchTab({
      visibleTabs,
      detail: mockDetail(visibleTabs),
      urlTab: 'rid',
      currentTab: 'findings',
      mode: 'reload',
    })).toBe('findings')
  })

  it('syncs activeTab when the URL tab changes via browser navigation', () => {
    expect(resolveActiveWorkbenchTab({
      visibleTabs,
      detail: mockDetail(visibleTabs),
      urlTab: 'rid',
      currentTab: 'findings',
      mode: 'url_sync',
    })).toBe('rid')
  })

  it('uses phase default when URL sync receives an invalid tab', () => {
    expect(resolveActiveWorkbenchTab({
      visibleTabs,
      detail: mockDetail(visibleTabs),
      urlTab: 'not-a-tab',
      currentTab: 'findings',
      mode: 'url_sync',
    })).toBe('overview')
  })

  it('defaults to arbitration when pending arbitration and tab is visible', () => {
    const arbitrationTabs = ['overview', 'flow', 'arbitration', 'decision']
    expect(resolveActiveWorkbenchTab({
      visibleTabs: arbitrationTabs,
      detail: mockDetail(arbitrationTabs, 'executing', {
        summary: {
          verdict: '',
          rationale: '',
          requires_arbitration: true,
          arbitration_status: 'pending',
          report_available: false,
        },
        metrics: {
          finding_count: 0,
          rid_count: 0,
          open_rid_count: 0,
          evidence_count: 0,
          conflict_count: 0,
          requires_arbitration: true,
        },
      }),
      urlTab: null,
      currentTab: 'overview',
      mode: 'initial',
    })).toBe('arbitration')
  })

  it('defaults to rid for completed gnc with open RID when no valid deep link', () => {
    const completedTabs = ['overview', 'flow', 'rid', 'decision']
    expect(resolveActiveWorkbenchTab({
      visibleTabs: completedTabs,
      detail: mockDetail(completedTabs, 'completed', {
        metrics: {
          finding_count: 0,
          rid_count: 2,
          open_rid_count: 2,
          evidence_count: 0,
          conflict_count: 0,
          requires_arbitration: false,
        },
      }),
      urlTab: null,
      currentTab: 'overview',
      mode: 'initial',
    })).toBe('rid')
  })

  it('maps legacy super_agent check_items deep link to findings tab', () => {
    const superTabs = ['overview', 'materials', 'routes', 'findings', 'closure', 'quality']
    expect(resolveActiveWorkbenchTab({
      visibleTabs: superTabs,
      detail: mockDetail(superTabs, 'completed', { review_type: 'super_agent' }),
      urlTab: 'check_items',
      currentTab: 'overview',
      mode: 'initial',
    })).toBe('findings')
  })

  it('keeps findings tab for check_items alias regardless of bucket query handling at shell', () => {
    const superTabs = ['overview', 'findings', 'quality']
    expect(resolveActiveWorkbenchTab({
      visibleTabs: superTabs,
      detail: mockDetail(superTabs, 'completed', { review_type: 'super_agent' }),
      urlTab: 'check_items',
      currentTab: 'overview',
      mode: 'url_sync',
    })).toBe('findings')
  })

  it('defaults super_agent completed runs to overview', () => {
    const superTabs = ['overview', 'materials', 'routes', 'findings', 'closure', 'quality']
    expect(resolveActiveWorkbenchTab({
      visibleTabs: superTabs,
      detail: mockDetail(superTabs, 'completed', { review_type: 'super_agent' }),
      urlTab: null,
      currentTab: 'overview',
      mode: 'initial',
    })).toBe('overview')
  })

  it('defaults to report for completed review_plus when report is available', () => {
    const reviewPlusTabs = ['overview', 'report', 'findings']
    expect(resolveActiveWorkbenchTab({
      visibleTabs: reviewPlusTabs,
      detail: mockDetail(reviewPlusTabs, 'completed', {
        review_type: 'review_plus',
        summary: {
          verdict: '',
          rationale: '',
          requires_arbitration: false,
          arbitration_status: '',
          report_available: true,
        },
      }),
      urlTab: null,
      currentTab: 'overview',
      mode: 'initial',
    })).toBe('report')
  })
})
