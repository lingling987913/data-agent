import { describe, expect, it } from 'vitest'
import type { SuperAgentRun } from '@/features/super-agent/types'
import { buildSuperAgentResultExplainability } from '@/features/super-agent/utils/superAgentProcessingViewModel'
import {
  buildFallbackOverviewMetrics,
  extractReviewSummary,
  shouldLoadReviewPlusResult,
} from '@/features/super-agent/utils/superAgentResultOverview'
import {
  buildReviewPlusResultPreviewModel,
  buildReviewWorkbenchResultPreviewModel,
  buildWorkbenchTabHref,
} from '@/features/unified-review-workbench/utils/reviewWorkbenchResultPreviewModel'
import { defaultWorkbenchTabForRun } from '@/features/unified-review-workbench/utils/superAgentWorkbenchLink'

function baseRun(overrides: Partial<SuperAgentRun> = {}): SuperAgentRun {
  return {
    run_id: 'run-1',
    name: 'test',
    status: 'completed',
    objective: 'test objective',
    processing_mode: 'OPTIMAL',
    input_mode: 'upload',
    source_review_id: 'rev-1',
    requested_route: 'auto',
    review_mode: 'full',
    materials: [],
    review_plus_result: {},
    structured_bundle: {},
    quality_report: {},
    trace_report: {},
    execution_metrics_snapshot: {},
    ...overrides,
  } as SuperAgentRun
}

describe('shouldLoadReviewPlusResult', () => {
  it('skips review plus embed for gnc-only completed runs', () => {
    expect(shouldLoadReviewPlusResult(baseRun({
      requested_route: 'gnc_review_only',
      route_decision: { route: 'gnc_review_only' } as SuperAgentRun['route_decision'],
      gnc_review_result: { status: 'completed' },
    }))).toBe(false)
  })
})

describe('buildReviewWorkbenchResultPreviewModel gnc', () => {
  it('builds gnc workbench preview with rid/decision sections and deep links', () => {
    const run = baseRun({
      requested_route: 'gnc_review_only',
      route_decision: { route: 'gnc_review_only' } as SuperAgentRun['route_decision'],
      gnc_review_result: {
        status: 'completed',
        workbench_phase: 'completed',
        open_rid_count: 2,
        rid_count: 5,
        finding_count: 3,
        evidence_count: 4,
        findings: [{ title: '导航精度指标缺失', severity: 'major' }],
        chief_decision: {
          verdict: 'conditionally_approved',
          rationale: '需补充远地点仿真判据。',
        },
        report: { summary: 'GNC 审查报告摘要' },
      },
    })
    const summary = extractReviewSummary(run)
    const explainability = buildSuperAgentResultExplainability(run)
    const model = buildReviewWorkbenchResultPreviewModel(run, summary, explainability)

    expect(model?.reviewKind).toBe('gnc')
    expect(model?.reviewType).toBe('gnc')
    expect(model?.sections.some((section) => section.key === 'rid')).toBe(true)
    expect(model?.sections.some((section) => section.key === 'decision')).toBe(true)
    expect(model?.verdict).toBe('有条件通过')
    expect(model?.workbenchHref).toContain('reviewType=gnc')
    expect(model?.workbenchHref).toContain('reviewId=rev-1')
    expect(defaultWorkbenchTabForRun(run)).toBe('rid')

    const ridHref = buildWorkbenchTabHref(model!, 'rid', 'rev-1')
    expect(ridHref).toContain('tab=rid')
    expect(ridHref).toContain('reviewType=gnc')
  })
})

describe('buildReviewPlusResultPreviewModel', () => {
  it('builds review plus preview with findings/coverage actions and report tab deep link', () => {
    const run = baseRun({
      requested_route: 'review_plus',
      route_decision: { route: 'review_plus' } as SuperAgentRun['route_decision'],
      review_plus_result: {
        status: 'completed',
        findings: [
          { finding_id: 'f-1', title: '接口一致性', judgment: 'not_satisfied' },
        ],
        coverage_matrix: { rows: [{ check_item_id: 'c-1' }, { check_item_id: 'c-2' }] },
        cross_document_review_items: [{ id: 'x-1' }],
        report: {
          conclusion: '审查通过',
          summary: '整体满足要求',
          total_check_items: 10,
          satisfied_count: 8,
          not_satisfied_count: 1,
          insufficient_evidence_count: 1,
          markdown: '# Report',
        },
      },
    })
    const summary = extractReviewSummary(run)
    const explainability = buildSuperAgentResultExplainability(run)
    const model = buildReviewPlusResultPreviewModel(run, summary, explainability)

    expect(model?.reviewKind).toBe('review_plus')
    expect(model?.reviewType).toBe('review_plus')
    expect(model?.sections.find((section) => section.key === 'findings')?.title).toBe('审查发现')
    expect(model?.sections.find((section) => section.key === 'findings')?.items.length).toBe(1)
    expect(model?.sections.find((section) => section.key === 'coverage')?.title).toBe('覆盖矩阵')
    expect(model?.sections.find((section) => section.key === 'coverage')?.items[0]?.detail).toContain('2')
    expect(model?.workbenchHref).toContain('reviewType=review_plus')
    expect(defaultWorkbenchTabForRun(run)).toBe('report')

    const reportHref = buildWorkbenchTabHref(model!, 'report', 'rev-1')
    expect(reportHref).toContain('tab=report')
    expect(reportHref).toContain('reviewType=review_plus')
  })
})

describe('buildReviewWorkbenchResultPreviewModel smart fallback', () => {
  it('uses generic findings/experts/report structure for smart routes', () => {
    const run = baseRun({
      requested_route: 'smart',
      route_decision: { route: 'smart' } as SuperAgentRun['route_decision'],
      review_plus_result: {
        findings: [
          { finding_id: 'f-1', title: '模板证据不足项', judgment: 'insufficient_evidence' },
        ],
        report: {
          conclusion: '统计结论',
          chief_comprehensive_review: {
            overall_assessment: '建议有条件放行',
            engineering_conclusions: [
              {
                conclusion_id: 'c-1',
                title: '最坏情况分析缺失',
                description: '报告未覆盖关键工况边界。',
                severity: 'major',
              },
            ],
          },
        },
      },
    })
    const summary = extractReviewSummary(run)
    const explainability = buildSuperAgentResultExplainability(run)
    const metrics = buildFallbackOverviewMetrics(run, summary, explainability)
    const model = buildReviewWorkbenchResultPreviewModel(run, summary, explainability)

    expect(metrics.conclusionText).toContain('统计结论')
    expect(model?.reviewKind).toBe('smart')
    expect(model?.sections.find((section) => section.key === 'experts')?.items.length).toBeGreaterThan(0)
    expect(model?.sections.find((section) => section.key === 'findings')).toBeTruthy()
    expect(model?.workbenchHref).toContain('reviewType=review_plus')
    expect(model?.actions.some((action) => action.tab === 'findings')).toBe(true)
  })
})
