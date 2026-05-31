import { describe, expect, it } from 'vitest'
import {
  isInternalReviewReport,
  resolveBusinessExportMarkdown,
  stripInternalBoilerplateLines,
} from '@/features/review-plus-shared/utils/businessReportMarkdown'

describe('businessReportMarkdown', () => {
  it('detects internal engineering markdown', () => {
    const internal = [
      '# GNC 统一审查报告',
      '- Report ID: `gnc-rda_b0c16154011a`',
      '- Review type: `gnc_review`',
      '## 2. 解析与结构化质量',
    ].join('\n')
    expect(isInternalReviewReport(internal)).toBe(true)
  })

  it('strips boilerplate export lines', () => {
    const markdown = [
      '# GNC 设计文档审查报告',
      'Word 兼容格式导出，用于线下流转与归档。',
      '> 参考 CASA COA 201（Form 282）设计/制造质量体系检查单逻辑，',
      '## 1. 基本信息',
    ].join('\n')
    const cleaned = stripInternalBoilerplateLines(markdown)
    expect(cleaned).not.toContain('Word 兼容格式导出')
    expect(cleaned).not.toContain('CASA COA 201')
    expect(cleaned).toContain('## 1. 基本信息')
  })

  it('returns empty string for internal markdown exports', () => {
    const internal = [
      '# GNC 统一审查报告',
      '- Report ID: `gnc-rda_b0c16154011a`',
      '- Review type: `gnc_review`',
      '## 3. 结构化解析结果',
    ].join('\n')
    expect(resolveBusinessExportMarkdown(internal)).toBe('')
  })

  it('localizes bare verdict tokens after 结论：', () => {
    const markdown = [
      '### 4.1 专业审查',
      '- 结论：reject',
      '- 裁定结论：reject',
    ].join('\n')
    const cleaned = resolveBusinessExportMarkdown(markdown)
    expect(cleaned).toContain('结论：不通过')
    expect(cleaned).not.toContain('结论：reject')
  })
})
