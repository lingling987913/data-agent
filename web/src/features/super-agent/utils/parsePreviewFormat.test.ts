import { describe, expect, it } from 'vitest'
import type { MaterialParsePreviewItem, ParsePreviewResponse } from '@/features/super-agent/types'
import {
  filterPreviewWarnings,
  isLegacyOfficeFileName,
  isStaleParsePreview,
  isStaleParsePreviewItem,
  resolveMineruBatchId,
  resolveOfficePreviewKind,
  resolvePreviewMarkdown,
  shouldShowCapabilityFailure,
  shouldShowDegradedNotice,
  shouldShowPreviewWarnings,
} from '@/features/super-agent/utils/parsePreviewFormat'

function buildItem(partial: Partial<MaterialParsePreviewItem>): MaterialParsePreviewItem {
  return {
    file_name: 'sample.pdf',
    role: 'subject_document',
    role_confidence: 0.9,
    role_reason: '',
    parsing_tier: 'standard',
    parser_type: 'auto',
    processing_mode: 'OPTIMAL',
    parse_status: 'ok',
    parser_name: 'mineru',
    content_preview: 'preview text',
    content_length: 100,
    line_count: 5,
    warnings: [],
    parser_trace: [],
    ...partial,
  }
}

describe('parsePreviewFormat', () => {
  it('prefers content_markdown over content_preview', () => {
    const item = buildItem({
      content_preview: 'plain preview',
      content_markdown: '# Title\n\nBody',
    })
    expect(resolvePreviewMarkdown(item)).toBe('# Title\n\nBody')
  })

  it('detects stale preview items missing blocks and content_markdown', () => {
    const stale = buildItem({ content_preview: '| a | b |', blocks: undefined, content_markdown: undefined })
    const modern = buildItem({ content_markdown: '# ok', blocks: [{ id: 'b1', block_type: 'heading', content: '# ok' }] })
    expect(isStaleParsePreviewItem(stale)).toBe(true)
    expect(isStaleParsePreviewItem(modern)).toBe(false)
    expect(
      isStaleParsePreview({
        classification: {} as ParsePreviewResponse['classification'],
        materials: [stale],
        summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      }),
    ).toBe(true)
  })

  it('does not show capability failure for ok parse with info-only degradation flags', () => {
    const item = buildItem({
      parse_status: 'ok',
      capability_passed: true,
      degraded: false,
    })
    expect(shouldShowCapabilityFailure(item)).toBe(false)
    expect(shouldShowDegradedNotice(item)).toBe(false)
  })

  it('shows capability failure only for failed parse status', () => {
    const item = buildItem({
      parse_status: 'failed',
      capability_passed: false,
      degraded: true,
    })
    expect(shouldShowCapabilityFailure(item)).toBe(true)
    expect(shouldShowDegradedNotice(item)).toBe(false)
  })

  it('shows degraded notice for partial parse without capability failure', () => {
    const item = buildItem({
      parse_status: 'partial',
      capability_passed: true,
      degraded: true,
    })
    expect(shouldShowCapabilityFailure(item)).toBe(false)
    expect(shouldShowDegradedNotice(item)).toBe(true)
  })

  it('does not show degraded notice when parse_status is ok', () => {
    const item = buildItem({
      parse_status: 'ok',
      degraded: true,
      warnings: ['postprocess skipped for parse preview'],
    })
    expect(shouldShowDegradedNotice(item)).toBe(false)
    expect(shouldShowPreviewWarnings(item)).toBe(false)
    expect(filterPreviewWarnings(item.warnings)).toEqual([])
  })

  it('filters info-only warnings from preview warning list', () => {
    const warnings = [
      'postprocess skipped for parse preview',
      'MinerU local backend=pipeline version=2.1.0',
      '已合并 2 组跨页表格。',
      'table extraction incomplete',
    ]
    expect(filterPreviewWarnings(warnings)).toEqual(['table extraction incomplete'])
  })

  it('does not show preview warnings for mineru-local success info notes', () => {
    const item = buildItem({
      parse_status: 'ok',
      degraded: false,
      warnings: ['MinerU local backend=pipeline version=2.1.0', '已合并 1 组跨页表格。'],
    })
    expect(shouldShowPreviewWarnings(item)).toBe(false)
  })

  it('extracts mineru batch_id from enhancement_log', () => {
    const item = buildItem({ file_name: 'report.pdf' })
    const preview = {
      parse_artifact: {
        parsed_documents: [
          {
            file_name: 'report.pdf',
            document: {
              enhancement_log: [{ kind: 'mineru_extract_payload', batch_id: 'batch-abc-123' }],
            },
          },
        ],
      },
      classification: {} as ParsePreviewResponse['classification'],
      materials: [],
      summary: { material_count: 0, parsed_ok: 0, degraded_count: 0 },
    } satisfies ParsePreviewResponse
    expect(resolveMineruBatchId(item, preview)).toBe('batch-abc-123')
  })

  it('resolves office preview kinds for modern office formats', () => {
    expect(resolveOfficePreviewKind('report.docx')).toBe('word')
    expect(resolveOfficePreviewKind('checks.xlsx')).toBe('excel')
    expect(resolveOfficePreviewKind('legacy.xls')).toBe('excel')
    expect(resolveOfficePreviewKind('deck.pptx')).toBe('ppt')
    expect(resolveOfficePreviewKind('legacy.doc')).toBeNull()
    expect(resolveOfficePreviewKind('legacy.ppt')).toBeNull()
  })

  it('marks legacy binary office formats as unsupported preview', () => {
    expect(isLegacyOfficeFileName('spec.doc')).toBe(true)
    expect(isLegacyOfficeFileName('slides.ppt')).toBe(true)
    expect(isLegacyOfficeFileName('data.xls')).toBe(false)
    expect(isLegacyOfficeFileName('report.docx')).toBe(false)
  })
})
