import { describe, expect, it } from 'vitest'
import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'
import {
  buildWorkbenchOverviewMarkdown,
  markdownHasWorkbenchOverview,
  mergeWorkbenchOverviewIntoMarkdown,
} from '@/features/review-plus-shared/utils/workbenchOverviewMarkdown'

function baseDetail(): UnifiedReviewWorkbenchDetail {
  return {
    review_id: 'run-1',
    name: '飞轮设计报告',
    review_type: 'super_agent',
    status: 'completed',
    workbench_phase: 'completed',
    visible_tabs: ['overview'],
    current_step: 'review_results',
    metrics: {
      finding_count: 8,
      problem_count: 8,
      pending_confirm: 5,
      rid_count: 2,
      open_rid_count: 1,
      evidence_count: 10,
      conflict_count: 0,
      requires_arbitration: false,
      material_count: 1,
    },
    summary: {
      verdict: 'reject',
      verdict_label_zh: '不通过',
      rationale: '',
      rationale_zh: '存在严重错误，需先整改。',
      requires_arbitration: false,
      arbitration_status: '',
      report_available: true,
      headline_verdict: '存在严重错误，建议暂停放行并优先整改。',
      one_line_conclusion: '存在严重错误，建议暂停放行并优先整改。',
      review_mode_label: 'GNC 审查',
    },
    conclusion_overview: {
      headline_verdict: '存在严重错误，建议暂停放行并优先整改。',
      one_line_conclusion: '存在严重错误，建议暂停放行并优先整改。',
      verdict_label_zh: '不通过',
      rationale_zh: '存在严重错误，需先整改。',
      issue_buckets: { severe_error: 3, manual_review: 5 },
      review_scope: {
        review_mode_label: 'GNC 审查',
        material_summary_lines: ['飞轮设计报告.docx'],
        review_plan_lines: ['审查模式：GNC 专业审查', '审查模板：GNC_AC'],
      },
      priority_items: [],
      coverage_summary: {},
    },
    error: '',
    created_at: '',
    updated_at: '',
  }
}

describe('workbenchOverviewMarkdown', () => {
  it('renders Chinese overview with reject mapped to 不通过', () => {
    const md = buildWorkbenchOverviewMarkdown(baseDetail())
    expect(md).toContain('## 2. 审查总览')
    expect(md).toContain('- 裁定结论：不通过')
    expect(md).toContain('不通过')
    expect(md).not.toContain('reject')
    expect(md).toContain('存在严重错误，建议暂停放行并优先整改')
    expect(md).toContain('GNC 审查')
    expect(md).toContain('| 问题数量 | 8 |')
    expect(md).toContain('| 待确认事项 | 5 |')
  })

  it('merges overview into legacy markdown without duplicating', () => {
    const legacy = [
      '# GNC 设计文档审查报告',
      '## 1. 基本信息',
      '- 审查任务：demo',
      '## 2. 材料质量结论',
      '- 可审查',
    ].join('\n')
    const merged = mergeWorkbenchOverviewIntoMarkdown(legacy, baseDetail())
    expect(markdownHasWorkbenchOverview(merged)).toBe(true)
    expect(merged).toContain('## 3. 材料质量结论')
    expect(merged.indexOf('## 2. 审查总览')).toBeLessThan(merged.indexOf('## 3. 材料质量结论'))
    const twice = mergeWorkbenchOverviewIntoMarkdown(merged, baseDetail())
    expect((twice.match(/## 2\. 审查总览/g) || []).length).toBe(1)
  })
})
