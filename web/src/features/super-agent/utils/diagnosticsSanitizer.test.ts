import { describe, expect, it } from 'vitest'
import {
  filterBusinessLines,
  isInternalDiagnosticText,
  sanitizeBusinessReportText,
  sanitizeSmartDiagnosticText,
} from '@/features/super-agent/utils/diagnosticsSanitizer'
import { buildSuperAgentExportMarkdown, buildSuperAgentResultExplainability } from '@/features/super-agent/utils/superAgentProcessingViewModel'
import type { SuperAgentRun } from '@/features/super-agent/types'

describe('diagnosticsSanitizer', () => {
  it('detects SMART execution_mode_summary raw strings', () => {
    const rawLines = [
      "SMART execution_mode_summary={'harness_count': 0, 'generic_llm_harness_count': 4}",
      "SMART committee execution_mode_summary={'generic_llm_harness_count': 4, 'deterministic_count': 1}",
    ]
    for (const line of rawLines) {
      expect(isInternalDiagnosticText(line)).toBe(true)
    }
  })

  it('filters screenshot raw diagnostics from business lines', () => {
    const items = [
      "SMART execution_mode_summary={'harness_count': 0, 'generic_llm_harness_count': 4}",
      "SMART committee execution_mode_summary={'generic_llm_harness_count': 4}",
      '未满足 Review-Plus / GNC 条件',
    ]
    expect(filterBusinessLines(items)).toEqual(['未满足 Review-Plus / GNC 条件'])
  })

  it('sanitizes markdown bullets and plain diagnostic lines', () => {
    const markdown = [
      '## 最终结论与追溯依据',
      '',
      "SMART execution_mode_summary={'harness_count': 0, 'generic_llm_harness_count': 4}",
      "- SMART committee execution_mode_summary={'deterministic_count': 1}",
      '- 引用/证据覆盖率 80%（task_board），部分结论可能缺少充分引用',
    ].join('\n')

    const cleaned = sanitizeBusinessReportText(markdown)
    expect(sanitizeSmartDiagnosticText(markdown)).toBe(cleaned)
    expect(cleaned).not.toContain('execution_mode_summary=')
    expect(cleaned).toContain('引用/证据覆盖率 80%')
  })
})

describe('buildSuperAgentResultExplainability', () => {
  it('does not expose raw diagnostics in risk items', () => {
    const run = {
      structured_bundle: { materials: [], stats: { material_count: 1 }, warnings: [] },
      review_plus_result: { finding_count: 0 },
      trace_report: {
        degradation_summary: [
          "SMART execution_mode_summary={'harness_count': 0, 'generic_llm_harness_count': 4}",
          "SMART committee execution_mode_summary={'generic_llm_harness_count': 4}",
        ],
      },
      quality_report: {
        warnings: [
          "SMART execution_mode_summary={'harness_count': 0, 'generic_llm_harness_count': 4}",
        ],
      },
    } as unknown as SuperAgentRun

    const result = buildSuperAgentResultExplainability(run)
    expect(result.riskItems.some((item) => item.includes('execution_mode_summary='))).toBe(false)
  })
})

describe('buildSuperAgentExportMarkdown', () => {
  it('sanitizes legacy backend report_markdown on export', () => {
    const run = {
      run_id: 'legacy-run',
      name: 'legacy',
      status: 'limited',
      report_markdown: [
        '# 报告',
        '',
        "- SMART execution_mode_summary={'harness_count': 0}",
        '- 未满足 Review-Plus / GNC 条件',
      ].join('\n'),
      structured_bundle: { materials: [], stats: {}, warnings: [] },
      review_plus_result: {},
      trace_report: { degradation_summary: [] },
      quality_report: { warnings: [] },
    } as unknown as SuperAgentRun

    const markdown = buildSuperAgentExportMarkdown(run)
    expect(markdown).not.toContain('execution_mode_summary=')
    expect(markdown).toContain('未满足 Review-Plus / GNC 条件')
  })
})
