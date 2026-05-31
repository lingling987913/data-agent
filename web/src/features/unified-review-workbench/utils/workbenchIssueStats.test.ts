import { describe, expect, it } from 'vitest'
import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'
import {
  resolveWorkbenchPendingConfirm,
  resolveWorkbenchProblemCount,
  sumProblemBuckets,
} from '@/features/unified-review-workbench/utils/workbenchIssueStats'

describe('workbenchIssueStats', () => {
  it('sums non-verified buckets only', () => {
    expect(
      sumProblemBuckets({
        severe_error: 9,
        template_structure_nonconforming: 19,
        cross_document_inconsistency: 1,
        insufficient_evidence: 17,
        verified: 1,
      }),
    ).toBe(46)
  })

  it('prefers backend problem_count over bucket fallback', () => {
    const detail = {
      metrics: {
        finding_count: 42,
        problem_count: 46,
        pending_confirm: 6,
        rid_count: 0,
        open_rid_count: 1,
        evidence_count: 0,
        conflict_count: 0,
        requires_arbitration: false,
      },
      conclusion_overview: {
        issue_buckets: { severe_error: 3 },
      },
    } as UnifiedReviewWorkbenchDetail
    expect(resolveWorkbenchProblemCount(detail)).toBe(46)
    expect(resolveWorkbenchPendingConfirm(detail)).toBe(6)
  })
})
