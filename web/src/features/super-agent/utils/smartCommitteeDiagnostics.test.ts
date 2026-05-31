import { describe, expect, it } from 'vitest'
import type { SuperAgentRun } from '@/features/super-agent/types'
import {
  filterBusinessFindings,
  formatExecutionModeSummaryLines,
  isSmartInternalDiagnostic,
  resolveSmartCommitteeDiagnostics,
} from '@/features/super-agent/utils/smartCommitteeDiagnostics'

describe('smartCommitteeDiagnostics', () => {
  it('filters SMART internal diagnostic warnings', () => {
    const items = [
      "SMART execution_mode_summary={'harness_count': 0, 'generic_llm_harness_count': 4}",
      "SMART committee execution_mode_summary={'generic_llm_harness_count': 4}",
      '未满足 Review-Plus / GNC 条件',
      '未满足 Review-Plus / GNC 条件',
    ]
    expect(isSmartInternalDiagnostic(items[0])).toBe(true)
    expect(filterBusinessFindings(items)).toEqual(['未满足 Review-Plus / GNC 条件'])
  })

  it('formats execution_mode_summary in Chinese business language', () => {
    const lines = formatExecutionModeSummaryLines(
      {
        harness_count: 0,
        generic_llm_harness_count: 4,
        deterministic_count: 0,
        failed_count: 0,
        blocked_count: 0,
      },
      { limited: false },
    )
    expect(lines).toContain('本次智能审查由 4 个通用 LLM 专家完成。')
    expect(lines).toContain('未启用 Review-Plus Harness，已使用 Generic LLM Harness。')
    expect(lines).toContain('当前结果为完整智能审查。')
  })

  it('puts formatted summary lines on diagnostics card model', () => {
    const run = {
      review_plus_result: {
        review_mode: 'smart_committee',
        limited: true,
        execution_mode_summary: {
          harness_count: 0,
          generic_llm_harness_count: 4,
          deterministic_count: 1,
          failed_count: 0,
          blocked_count: 0,
        },
        citation_coverage: 0.8,
        citation_coverage_source: 'task_board',
      },
      trace_report: {
        degradation_summary: [
          "SMART execution_mode_summary={'generic_llm_harness_count': 4}",
          'SMART committee 审查为 limited（deterministic/fallback/无充分 citations）',
        ],
      },
    } as unknown as SuperAgentRun

    const diagnostics = resolveSmartCommitteeDiagnostics(run)
    expect(diagnostics.executionModeSummaryLines.some((line) => line.includes('4 个通用 LLM 专家'))).toBe(true)
    expect(diagnostics.degradationNotes.some((note) => note.includes('execution_mode_summary='))).toBe(false)
    expect(diagnostics.degradationNotes).toContain(
      'SMART committee 审查为 limited（deterministic/fallback/无充分 citations）',
    )
  })
})
