import { describe, expect, it } from 'vitest'
import type { SuperAgentRun } from '@/features/super-agent/types'
import {
  buildFallbackOverviewMetrics,
  extractReviewSummary,
  shouldLoadReviewPlusResult,
} from '@/features/super-agent/utils/superAgentResultOverview'
import { buildSuperAgentResultExplainability } from '@/features/super-agent/utils/superAgentProcessingViewModel'

function baseRun(overrides: Partial<SuperAgentRun> = {}): SuperAgentRun {
  return {
    run_id: 'run-1',
    name: 'test',
    status: 'completed',
    objective: 'test objective',
    processing_mode: 'OPTIMAL',
    input_mode: 'upload',
    source_review_id: '',
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
  it('returns false without source_review_id', () => {
    expect(shouldLoadReviewPlusResult(baseRun())).toBe(false)
  })

  it('returns true when completed with source_review_id for review plus routes', () => {
    expect(shouldLoadReviewPlusResult(baseRun({
      source_review_id: 'review-1',
      status: 'completed',
      route_decision: { route: 'review_plus' } as SuperAgentRun['route_decision'],
    }))).toBe(true)
  })

  it('returns false for gnc-only completed runs', () => {
    expect(shouldLoadReviewPlusResult(baseRun({
      source_review_id: 'review-1',
      status: 'completed',
      requested_route: 'gnc_review_only',
      route_decision: { route: 'gnc_review_only' } as SuperAgentRun['route_decision'],
      gnc_review_result: { status: 'completed' },
    }))).toBe(false)
  })
})

describe('extractReviewSummary', () => {
  it('maps report counts when findings are absent', () => {
    const summary = extractReviewSummary(baseRun({
      review_plus_result: {
        report: {
          satisfied_count: 8,
          insufficient_evidence_count: 2,
          not_satisfied_count: 1,
        },
      },
    }))
    expect(summary.passed).toBe(8)
    expect(summary.attention).toBe(2)
    expect(summary.failed).toBe(1)
  })
})

describe('buildSuperAgentResultExplainability gnc findings', () => {
  it('surfaces gnc_review_result findings when review_plus report is empty', () => {
    const run = baseRun({
      requested_route: 'gnc_review_only',
      gnc_review_result: {
        status: 'completed',
        findings: [
          {
            finding_id: 'GNC-001',
            title: '相对导航精度判据不完整',
            description: '远地点段未给出三轴位置误差上限。',
            severity: 'major',
            judgment: 'not_satisfied',
          },
        ],
        editorial_synthesis: {
          conclusion_draft: '建议补充远地点导航精度指标与仿真判据。',
        },
      },
    })
    const explainability = buildSuperAgentResultExplainability(run)
    expect(explainability.reviewItems.length).toBe(1)
    expect(explainability.reviewItems[0]?.title).toContain('相对导航精度')
    expect(explainability.conclusionSummary).toContain('远地点')
  })
})

describe('buildSuperAgentResultExplainability chief comprehensive review', () => {
  it('surfaces chief engineering conclusions without dropping checklist findings', () => {
    const run = baseRun({
      review_plus_result: {
        findings: [
          {
            finding_id: 'f-1',
            title: '模板证据不足项',
            judgment: 'insufficient_evidence',
            reasoning: '证据不足',
          },
        ],
        report: {
          conclusion: '统计结论',
          chief_comprehensive_review: {
            status: 'ok',
            overall_assessment: '建议有条件放行，需先补充最坏情况分析。',
            engineering_conclusions: [
              {
                conclusion_id: 'c-1',
                title: '最坏情况分析缺失',
                description: '报告未覆盖关键工况边界。',
                severity: 'major',
                recommendation: '补充 WCA 章节。',
                evidence_sources: ['第 4 章 可靠性分析'],
              },
            ],
          },
        },
      },
    })
    const explainability = buildSuperAgentResultExplainability(run)
    expect(explainability.conclusionSummary).toContain('有条件放行')
    expect(explainability.chiefReviewItems.length).toBe(1)
    expect(explainability.chiefReviewItems[0]?.title).toContain('最坏情况')
    expect(explainability.reviewItems.length).toBe(1)
  })
})

describe('buildFallbackOverviewMetrics', () => {
  it('maps summary counts into ResultSummaryBar items', () => {
    const run = baseRun({
      review_plus_result: {
        report: {
          conclusion: '审查通过',
          summary: '整体满足要求',
          total_check_items: 10,
          satisfied_count: 7,
          not_satisfied_count: 2,
          insufficient_evidence_count: 1,
        },
      },
    })
    const summary = extractReviewSummary(run)
    const explainability = buildSuperAgentResultExplainability(run)
    const metrics = buildFallbackOverviewMetrics(run, summary, explainability)

    expect(metrics.totalCheckItems).toBe(10)
    expect(metrics.satisfied).toBe(7)
    expect(metrics.notSatisfied).toBe(2)
    expect(metrics.insufficientEvidence).toBe(1)
    expect(metrics.passRate).toBe('70%')
    expect(metrics.verdict).toBe('pass')
    expect(metrics.summaryItems.map((item) => item.label)).toEqual([
      '检查项',
      '满足',
      '不满足',
      '证据不足',
      '通过率',
    ])
  })
})
