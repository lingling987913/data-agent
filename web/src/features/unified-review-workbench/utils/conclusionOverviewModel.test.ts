import { describe, expect, it } from 'vitest'
import {
  BUSINESS_BUCKET_LABELS,
  buildConclusionOverviewFromDetail,
  buildReviewPlanLines,
  buildReviewSubjectLines,
  deriveReviewTaskDisplayName,
  normalizeIssueBuckets,
} from '@/features/unified-review-workbench/utils/conclusionOverviewModel'
import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'

function baseDetail(overrides: Partial<UnifiedReviewWorkbenchDetail> = {}): UnifiedReviewWorkbenchDetail {
  return {
    review_id: 'rp-1',
    name: '智能审查 2026/5/31',
    review_type: 'review_plus',
    status: 'completed',
    workbench_phase: 'completed',
    visible_tabs: ['overview', 'findings', 'coverage', 'report'],
    current_step: '',
    metrics: {
      finding_count: 3,
      rid_count: 0,
      open_rid_count: 1,
      evidence_count: 5,
      conflict_count: 1,
      requires_arbitration: false,
    },
    summary: {
      verdict: '有条件通过',
      rationale: '需补充仿真依据',
      requires_arbitration: false,
      arbitration_status: '',
      report_available: true,
      headline_verdict: '部分审查点证据不足',
      one_line_conclusion: '部分审查点证据不足，需补充材料后复审（非失败兜底）。',
      review_mode_label: '通用审查',
    },
    conclusion_overview: {
      headline_verdict: '部分审查点证据不足',
      one_line_conclusion: '部分审查点证据不足，需补充材料后复审（非失败兜底）。',
      issue_buckets: {
        severe_error: 1,
        content_nonconforming: 2,
        insufficient_evidence: 1,
        verified: 4,
      },
      bucket_labels: BUSINESS_BUCKET_LABELS,
      review_scope: {
        review_mode_label: '通用审查',
        actual_scope: ['通用审查（结构正确性 + 内容正确性 + 跨文档一致性）', '文档类型待确认'],
        document_type_pending: true,
        material_names: ['任务书.docx', '设计报告.pdf'],
        material_summary_lines: ['任务书.docx（task_book）', '设计报告.pdf（subject_document）'],
        review_plan_lines: ['通用审查（结构正确性 + 内容正确性 + 跨文档一致性）'],
      },
      priority_items: [
        {
          id: 'f-1',
          title: '接口指标冲突',
          business_bucket: 'cross_document_inconsistency',
          business_bucket_label: '文文不一致',
          reason: '任务书与报告指标不一致',
          tab_hint: 'cross_doc',
        },
      ],
      coverage_summary: {
        total_check_items: 12,
        verified_count: 4,
        evidence_count: 5,
        coverage_rate: 0.33,
        document_type_label: '文档类型待确认',
        notes: ['文档类型待确认'],
      },
    },
    error: '',
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

describe('normalizeIssueBuckets', () => {
  it('orders business buckets with Chinese labels', () => {
    const cards = normalizeIssueBuckets(
      { verified: 2, severe_error: 1, insufficient_evidence: 0 },
      BUSINESS_BUCKET_LABELS,
    )
    expect(cards[0].key).toBe('severe_error')
    expect(cards[0].label).toBe('严重错误')
    expect(cards.find((c) => c.key === 'verified')?.count).toBe(2)
  })
})

describe('buildConclusionOverviewFromDetail', () => {
  it('builds Chinese overview vm from workbench detail', () => {
    const vm = buildConclusionOverviewFromDetail(baseDetail(), 'review_plus')
    expect(vm.reviewModeLabel).toBe('通用审查')
    expect(vm.taskDisplayName).toBe('任务书 等 2 份材料')
    expect(vm.reviewSubjectLines).toEqual(['任务书.docx（task_book）', '设计报告.pdf（subject_document）'])
    expect(vm.reviewPlanLines.length).toBeGreaterThan(0)
    expect(vm.documentTypePending).toBe(true)
    expect(vm.bucketCards.some((c) => c.label === '文文不一致')).toBe(false)
    expect(vm.bucketCards.some((c) => c.label === '严重错误')).toBe(true)
    expect(vm.priorityItems[0].business_bucket_label).toBe('文文不一致')
    expect(vm.coverageSummary.documentTypeLabel).toBe('文档类型待确认')
    expect(vm.drillDownTabs.every((t) => !/findings|coverage/i.test(t.label))).toBe(true)
  })

  it('localizes English verdict and rationale for super agent workbench', () => {
    const vm = buildConclusionOverviewFromDetail(
      baseDetail({
        review_type: 'super_agent',
        summary: {
          verdict: 'conditional_rejection',
          rationale: 'Primary design document missing; cannot complete full GNC CDR review at this time.',
          requires_arbitration: false,
          arbitration_status: '',
          report_available: true,
          review_mode_label: 'Super Agent 审查',
        },
        conclusion_overview: {
          headline_verdict: '材料不足，无法完成完整 GNC 审查，请先补齐材料后复审',
          one_line_conclusion: '材料不足，无法完成完整 GNC 审查，请先补齐材料后复审',
          issue_buckets: { insufficient_evidence: 5, manual_review: 1 },
          bucket_labels: BUSINESS_BUCKET_LABELS,
          review_scope: {
            review_mode_label: 'Super Agent 审查',
            actual_scope: ['智能审查（按路由执行 GNC 或通用/专家委员会）'],
            document_type_pending: false,
            material_insufficiency: true,
            material_names: ['GNC-CDR-主报告.docx'],
            material_summary_lines: ['GNC-CDR-主报告.docx'],
            review_plan_lines: ['智能审查（按路由执行 GNC 或通用/专家委员会）', '执行路由：GNC 专项'],
          },
          priority_items: [],
          coverage_summary: {},
        },
      }),
      'super_agent',
    )
    expect(vm.reviewModeLabel).toBe('智能审查')
    expect(vm.taskDisplayName).toBe('GNC-CDR-主报告')
    expect(vm.reviewSubjectLines).toEqual(['GNC-CDR-主报告.docx'])
    expect(vm.reviewPlanLines.some((line) => line.includes('GNC'))).toBe(true)
    expect(vm.verdictLabel).toBe('材料不足，暂无法完成完整审查')
    expect(vm.verdictLabel).not.toContain('conditional_rejection')
    expect(vm.rationaleDisplay).toContain('资料包')
    expect(vm.rationaleDisplay).not.toMatch(/primary design document/i)
  })

  it('assigns unique ids when priority items share the same title', () => {
    const duplicateTitle = '检查单条款未形成任务书到报告的闭环证据'
    const vm = buildConclusionOverviewFromDetail(
      baseDetail({
        conclusion_overview: {
          ...baseDetail().conclusion_overview!,
          priority_items: [
            {
              title: duplicateTitle,
              business_bucket: 'insufficient_evidence',
              business_bucket_label: '证据不足',
            },
            {
              title: duplicateTitle,
              business_bucket: 'insufficient_evidence',
              business_bucket_label: '证据不足',
            },
          ],
        },
      }),
      'review_plus',
    )
    const ids = vm.priorityItems.map((item) => item.id)
    expect(ids).toEqual([duplicateTitle, `${duplicateTitle}#1`])
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('derives task name from custom detail name', () => {
    expect(deriveReviewTaskDisplayName(baseDetail({ name: '飞轮控制专项审查' }))).toBe('飞轮控制专项审查')
  })

  it('builds subject and plan lines from review scope', () => {
    const scope = baseDetail().conclusion_overview?.review_scope || {}
    expect(buildReviewSubjectLines(scope)).toEqual(['任务书.docx（task_book）', '设计报告.pdf（subject_document）'])
    expect(buildReviewPlanLines(scope, '通用审查')[0]).toContain('通用审查')
  })
})
