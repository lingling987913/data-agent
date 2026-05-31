import { describe, expect, it } from 'vitest'
import type { ParsePreviewResponse } from '@/features/super-agent/types'
import { buildParseAdmissionSummary } from '@/features/super-agent/utils/parseAdmissionSummary'

function basePreview(overrides: Partial<ParsePreviewResponse> = {}): ParsePreviewResponse {
  return {
    classification: {
      doc_type: '设计报告',
      domain: 'GNC',
      recommended_route: 'smart',
      reason: 'test',
    },
    materials: [
      {
        file_name: 'report.pdf',
        role: 'subject_document',
        role_confidence: 0.9,
        role_reason: 'test',
        parsing_tier: 'full',
        parser_type: 'mineru',
        processing_mode: 'OPTIMAL',
        parse_status: 'ok',
        parser_name: 'MinerU',
        content_preview: 'hello',
        content_markdown: '# hello',
        content_length: 5,
        line_count: 1,
        warnings: [],
        parser_trace: [],
        blocks: [{ id: 'b1', block_type: 'paragraph', content: 'hello', markdown: 'hello' }],
      },
    ],
    summary: {
      material_count: 1,
      parsed_ok: 1,
      degraded_count: 0,
    },
    structure_summary: {
      section_count: 3,
      evidence_count: 12,
      structure_ready: true,
    },
    ...overrides,
  }
}

describe('buildParseAdmissionSummary', () => {
  it('returns incomplete when preview is missing', () => {
    const summary = buildParseAdmissionSummary(null)
    expect(summary.status).toBe('incomplete')
    expect(summary.headline).toBe('待启动解析')
  })

  it('returns parsing headline when busy', () => {
    const summary = buildParseAdmissionSummary(null, { loading: true, parseBusy: true })
    expect(summary.status).toBe('incomplete')
    expect(summary.headline).toBe('解析进行中')
  })

  it('returns ready when parse succeeds without risks', () => {
    const summary = buildParseAdmissionSummary(basePreview())
    expect(summary.status).toBe('ready')
    expect(summary.headline).toBe('解析已完成')
    expect(summary.materialCount).toBe(1)
    expect(summary.parsedOk).toBe(1)
  })

  it('returns review_required when degraded material exists', () => {
    const preview = basePreview({
      summary: { material_count: 1, parsed_ok: 1, degraded_count: 1 },
      materials: [
        {
          ...basePreview().materials[0],
          parse_status: 'degraded',
          degraded: true,
        },
      ],
    })
    const summary = buildParseAdmissionSummary(preview)
    expect(summary.status).toBe('review_required')
    expect(summary.headline).toBe('需核对解析结果')
    expect(summary.risks.some((risk) => risk.includes('降级解析'))).toBe(true)
  })

  it('returns incomplete when structure is not ready', () => {
    const preview = basePreview({
      structure_summary: {
        section_count: 1,
        evidence_count: 0,
        structure_ready: false,
      },
    })
    const summary = buildParseAdmissionSummary(preview)
    expect(summary.status).toBe('incomplete')
    expect(summary.headline).toBe('结构化未完成')
    expect(summary.risks.some((risk) => risk.includes('结构化产物尚未就绪'))).toBe(true)
  })

  it('caps risk list to two items', () => {
    const preview = basePreview({
      summary: { material_count: 3, parsed_ok: 3, degraded_count: 3 },
      materials: [
        { ...basePreview().materials[0], file_name: 'a.pdf', parse_status: 'degraded', degraded: true },
        { ...basePreview().materials[0], file_name: 'b.pdf', parse_status: 'degraded', degraded: true },
        { ...basePreview().materials[0], file_name: 'c.pdf', parse_status: 'degraded', degraded: true },
      ],
    })
    const summary = buildParseAdmissionSummary(preview)
    expect(summary.risks.length).toBeLessThanOrEqual(2)
  })
})
