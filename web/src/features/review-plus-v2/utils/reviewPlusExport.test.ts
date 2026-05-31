import { describe, expect, it } from 'vitest'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import {
  buildExportStyles,
  buildReviewPlusExportHtml,
  extractLeadingMarkdownTitle,
  stripLeadingMarkdownTitle,
} from '@/features/review-plus-v2/utils/reviewPlusExport'
import reviewPlusExportTemplate from '@/features/review-plus-v2/reviewPlusExportTemplate.json'

function minimalTask(overrides: Partial<ReviewPlusTaskDetail> = {}): ReviewPlusTaskDetail {
  return {
    review_plus_id: 'rp-test-001',
    name: '飞轮设计审查',
    status: 'completed',
    scenario: 'design_compliance',
    materials: [{ material_id: 'm1', name: '设计报告.pdf' }],
    check_items: [
      {
        check_item_id: 'ci-1',
        item_no: '1',
        title: '设计文件完整性',
        requirement_text: '目录、章节与签署栏齐全',
        acceptance_criteria: '齐全',
      },
    ],
    findings: [
      {
        finding_id: 'f-1',
        check_item_id: 'ci-1',
        title: '指标口径不一致',
        judgment: 'not_satisfied',
        severity: 'major',
        reasoning: '任务书与设计报告单位不一致',
      },
    ],
    report: {
      conclusion: '总体符合，建议闭环跨文档问题。',
      summary: '完成 1 项检查。',
      total_check_items: 1,
      satisfied_count: 0,
      not_satisfied_count: 1,
      insufficient_evidence_count: 0,
      not_checked_count: 0,
    },
    ...overrides,
  } as ReviewPlusTaskDetail
}

describe('reviewPlusExport', () => {
  it('maps severity enums to Chinese labels in fallback issue table', () => {
    const html = buildReviewPlusExportHtml(minimalTask(), '')
    expect(html).toContain('主要问题')
    expect(html).not.toMatch(/>\s*major\s*</i)
    expect(html).not.toMatch(/>\s*not_satisfied\s*</i)
  })

  it('renders business markdown before checklist appendix', () => {
    const markdown = [
      '# GNC 设计文档审查报告',
      '## 1. 基本信息',
      '## 2. 审查总览',
      '### 2.3 裁定结论',
      '## 3. 材料质量结论',
      '## 4. 总体审查结论',
      '## 5. 专业审查发现',
      '## 8. 审签栏',
      '## 附件 B：符合性检查清单',
      '| 序号 | 检查项 | 检查对象 | 检查要求 | 结论 | 证据/位置 | 备注 |',
    ].join('\n')

    const html = buildReviewPlusExportHtml(minimalTask(), markdown)
    const bodyPos = html.indexOf('report-body')
    const appendixPos = html.indexOf('附件 B：符合性检查清单')
    expect(bodyPos).toBeGreaterThan(-1)
    expect(html).not.toContain('RP-')
    expect(html).not.toContain('review_plus_id')
    expect(html).toContain('FangSong')
    expect(html).toContain('xmlns:w=')
    if (appendixPos >= 0) {
      expect(appendixPos).toBeGreaterThan(bodyPos)
    }
  })

  it('appends checklist appendix when markdown lacks checklist section', () => {
    const html = buildReviewPlusExportHtml(minimalTask(), '')
    const conclusionPos = html.indexOf('一、总体审查结论')
    const appendixPos = html.indexOf('附件：符合性检查清单')
    expect(conclusionPos).toBeGreaterThan(-1)
    expect(appendixPos).toBeGreaterThan(conclusionPos)
    expect(html).toContain('设计文件完整性')
  })

  it('uses Word-safe line-height and avoids crushing text', () => {
    const styles = buildExportStyles(reviewPlusExportTemplate)
    expect(styles).toContain('line-height: 175%')
    expect(styles).not.toContain('mso-line-height-rule: exactly')
    expect(styles).toContain('mso-line-height-rule: at-least')
  })

  it('renders document title once when markdown starts with h1', () => {
    const markdown = [
      '# 设计过程符合性审查单',
      '## 1. 基本信息',
      '正文段落。',
    ].join('\n')
    expect(extractLeadingMarkdownTitle(markdown)).toBe('设计过程符合性审查单')
    expect(stripLeadingMarkdownTitle(markdown)).not.toMatch(/^#\s/)

    const html = buildReviewPlusExportHtml(minimalTask(), markdown)
    expect(html.match(/class="doc-title"/g)?.length).toBe(1)
    expect(html).toContain('<h1 class="doc-title">设计过程符合性审查单</h1>')
    expect(html).not.toMatch(/<h1 class="report-title"/)
    expect(html).toContain('<h2 class="section-title">1. 基本信息</h2>')
    expect(html).toContain('正文段落。')
    expect(html.indexOf('report-body')).toBeGreaterThan(html.indexOf('doc-title'))
    expect(html).not.toContain('<hr class="header-rule"')
    expect(html).toContain('class="header-rule"')
  })

  // Manual Word check: export .doc from workbench, open in Microsoft Word —
  // titles should not overlap, tables should not cover body text, red rule visible once.
})
