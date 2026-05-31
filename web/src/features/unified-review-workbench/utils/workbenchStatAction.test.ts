import { describe, expect, it } from 'vitest'
import {
  bucketKeyFromStatKey,
  resolveSuperAgentStatAction,
  resolveStatActionAriaLabel,
  statKeyForBucket,
} from '@/features/unified-review-workbench/utils/workbenchStatAction'
import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'

function superAgentDetail(
  overrides: Partial<UnifiedReviewWorkbenchDetail> = {},
): UnifiedReviewWorkbenchDetail {
  return {
    review_id: 'run-1',
    name: '智能审查',
    review_type: 'super_agent',
    status: 'completed',
    workbench_phase: 'completed',
    visible_tabs: ['overview', 'materials', 'routes', 'findings', 'closure', 'quality'],
    current_step: '',
    metrics: {
      finding_count: 5,
      rid_count: 0,
      open_rid_count: 1,
      evidence_count: 3,
      conflict_count: 0,
      requires_arbitration: false,
      material_count: 2,
    },
    summary: {
      verdict: '',
      rationale: '',
      requires_arbitration: false,
      arbitration_status: '',
      report_available: false,
    },
    conclusion_overview: {
      headline_verdict: '',
      one_line_conclusion: '',
      issue_buckets: { manual_review: 2 },
      bucket_labels: {},
      review_scope: {},
      priority_items: [],
      coverage_summary: {},
    },
    error: '',
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

describe('workbenchStatAction', () => {
  it('maps overview situation stats to target tabs', () => {
    expect(resolveSuperAgentStatAction('material_count')?.tab).toBe('materials')
    expect(resolveSuperAgentStatAction('finding_count')?.tab).toBe('findings')
    expect(resolveSuperAgentStatAction('review_route_label')?.tab).toBe('routes')
    expect(resolveSuperAgentStatAction('quality_status')?.tab).toBe('quality')
  })

  it('maps bucket stat keys to findings with Chinese hint', () => {
    const key = statKeyForBucket('severe_error')
    expect(bucketKeyFromStatKey(key)).toBe('severe_error')
    const action = resolveSuperAgentStatAction(key)
    expect(action?.tab).toBe('findings')
    expect(action?.bucket).toBe('severe_error')
    expect(action?.hint).toContain('严重错误')
  })

  it('routes pending confirm to manual_review bucket', () => {
    const action = resolveSuperAgentStatAction('pending_confirm', superAgentDetail())
    expect(action?.tab).toBe('findings')
    expect(action?.bucket).toBe('manual_review')
    expect(action?.hint).toMatch(/待人工确认|待确认/)
  })

  it('disables pending confirm drill-down when count is zero', () => {
    const action = resolveSuperAgentStatAction(
      'pending_confirm',
      superAgentDetail({
        metrics: {
          finding_count: 0,
          rid_count: 0,
          open_rid_count: 0,
          evidence_count: 0,
          conflict_count: 0,
          requires_arbitration: false,
        },
        conclusion_overview: {
          headline_verdict: '',
          one_line_conclusion: '',
          issue_buckets: {},
          bucket_labels: {},
          review_scope: {},
          priority_items: [],
          coverage_summary: {},
        },
      }),
    )
    expect(action?.disabled).toBe(true)
  })

  it('exposes Chinese aria labels without English keys', () => {
    const action = resolveSuperAgentStatAction('finding_count')
    const label = resolveStatActionAriaLabel('问题数量', action)
    expect(label).toContain('发现与证据')
    expect(label).not.toMatch(/findings|severe_error/i)
  })
})
