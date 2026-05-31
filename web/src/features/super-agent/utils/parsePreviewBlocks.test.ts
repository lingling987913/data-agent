import { describe, expect, it } from 'vitest'
import type { MaterialParsePreviewItem, ParsePreviewBlock } from '@/features/super-agent/types'
import {
  blockContentEdited,
  blockDisplayMarkdown,
  blockDoubleClickNavigation,
  blocksForPage,
  buildMaterialJsonPreview,
  buildPdfViewerSrc,
  applyCalibrationHighlightsToHtml,
  calibrationHighlightTerms,
  firstBlockPage,
  jsonBlockClickNavigation,
  previewBlockMarkdownSegments,
  renderCalibrationHighlightedHtml,
  previewBlocksMatchJsonExport,
  resolvePageCount,
  resolvePreviewBlocks,
  updateBlockContent,
} from '@/features/super-agent/utils/parsePreviewBlocks'

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

describe('parsePreviewBlocks', () => {
  it('prefers structured blocks over fallback markdown', () => {
    const item = buildItem({
      content_markdown: '# Title',
      blocks: [
        { id: 'b1', block_type: 'heading', content: 'Title', markdown: '# Title', page_hint: 2 },
        { id: 'b2', block_type: 'paragraph', content: 'Body', markdown: 'Body', page_hint: 2 },
      ],
    })
    expect(resolvePreviewBlocks(item)).toHaveLength(2)
    expect(resolvePageCount(item, resolvePreviewBlocks(item))).toBe(2)
  })

  it('falls back to markdown when blocks are missing', () => {
    const item = buildItem({ content_markdown: '# Only markdown' })
    const blocks = resolvePreviewBlocks(item)
    expect(blocks).toHaveLength(1)
    expect(blocks[0]?.markdown).toBe('# Only markdown')
  })

  it('builds pdf viewer url with page fragment', () => {
    expect(buildPdfViewerSrc('blob:http://localhost/abc', 3)).toBe('blob:http://localhost/abc#page=3')
  })

  it('filters blocks by page hint', () => {
    const blocks: ParsePreviewBlock[] = [
      { id: 'a', block_type: 'paragraph', content: 'p1', page_hint: 1 },
      { id: 'b', block_type: 'paragraph', content: 'p2', page_hint: 2 },
    ]
    expect(blocksForPage(blocks, 2)).toEqual([blocks[1]])
    expect(blocksForPage(blocks, 4)).toEqual([])
    expect(firstBlockPage(blocks)).toBe(1)
  })

  it('uses the max hinted page when backend page_count is distinct-page count', () => {
    const blocks: ParsePreviewBlock[] = [
      { id: 'a', block_type: 'paragraph', content: 'p1', page_hint: 1 },
      { id: 'b', block_type: 'paragraph', content: 'p3', page_hint: 3 },
      { id: 'c', block_type: 'paragraph', content: 'p5', page_hint: 5 },
    ]
    const item = buildItem({
      page_count: 3,
      document_ir_stats: { page_count: 3 },
    })
    expect(resolvePageCount(item, blocks)).toBe(5)
  })

  it('builds json preview payload for active file', () => {
    const item = buildItem({
      file_name: 'a.pdf',
      blocks: [{ id: 'b1', block_type: 'paragraph', content: 'hello' }],
      parse_artifact_subset: { parse_status: 'ok' },
    })
    const payload = buildMaterialJsonPreview(item, {
      classification: { doc_type: 'x', domain: 'y', recommended_route: 'auto', reason: 'z' },
      materials: [item],
      summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      parse_artifact: {
        parsed_documents: [{ file_name: 'a.pdf', parse_status: 'ok' }],
        file_results: [{ file_name: 'a.pdf', parse_status: 'ok' }],
      },
    })
    expect(payload.file_name).toBe('a.pdf')
    expect(payload.blocks).toHaveLength(1)
    expect(payload.parsed_document).toEqual({ file_name: 'a.pdf', parse_status: 'ok' })
  })

  it('uses block content when rendering block markdown', () => {
    const block: ParsePreviewBlock = {
      id: 'b1',
      block_type: 'paragraph',
      content: 'original',
      markdown: 'original',
    }
    expect(blockDisplayMarkdown(block)).toBe('original')
  })

  it('renders calibration suggestion while preserving original block text', () => {
    const item = buildItem({
      blocks: [
        {
          id: 'b1',
          block_type: 'paragraph',
          content: '检查结果：温度环境为238°C。',
          markdown: '检查结果：温度环境为238°C。',
          calibration_records: [
            {
              block_id: 'b1',
              issue_type: 'numeric_outlier',
              severity: 'critical',
              original_text: '检查结果：温度环境为238°C。',
              suggested_text: '检查结果：温度环境为[需复核：238°C]。',
              reason: '超出上下文范围。',
              confidence: 0.9,
              status: 'needs_review',
            },
          ],
        },
      ],
    })

    const [block] = resolvePreviewBlocks(item)

    expect(block?.content).toBe('检查结果：温度环境为[需复核：238°C]。')
    expect(block?.markdown).toBe('检查结果：温度环境为[需复核：238°C]。')
    expect(block?.original_content).toBe('检查结果：温度环境为238°C。')
    expect(block?.calibrated).toBe(true)
  })

  it('highlights calibrated or review-needed fields', () => {
    const block = resolvePreviewBlocks(buildItem({
      blocks: [
        {
          id: 'b1',
          block_type: 'paragraph',
          content: '检查结果：温度环境为238°C。',
          markdown: '检查结果：温度环境为238°C。',
          calibration_records: [
            {
              block_id: 'b1',
              issue_type: 'numeric_outlier',
              severity: 'critical',
              original_text: '检查结果：温度环境为238°C。',
              suggested_text: '检查结果：温度环境为[需复核：238°C]。',
              evidence: ['20°C±5°C', '238°C'],
              reason: '超出上下文范围。',
              confidence: 0.9,
              status: 'needs_review',
            },
          ],
        },
      ],
    }))[0]!

    expect(calibrationHighlightTerms(block)).toContain('[需复核：238°C]')
    expect(renderCalibrationHighlightedHtml(block)).toContain('<mark')
    expect(renderCalibrationHighlightedHtml(block)).toContain('[需复核：238°C]')
  })

  it('highlights corrected fields inside HTML table blocks', () => {
    const block = resolvePreviewBlocks(buildItem({
      blocks: [
        {
          id: 'b1',
          block_type: 'table',
          content: '<table><tr><td>实测值</td><td>4100.58</td></tr></table>',
          markdown: '<table><tr><td>实测值</td><td>4100.58</td></tr></table>',
          calibration_records: [
            {
              block_id: 'b1',
              issue_type: 'symbol_confusion',
              severity: 'warning',
              original_text: '<table><tr><td>实测值</td><td>4100.58</td></tr></table>',
              suggested_text: '<table><tr><td>实测值</td><td>Φ100.58</td></tr></table>',
              evidence: ['4100.58', 'Φ100.58'],
              reason: '疑似 Φ 被识别为 4。',
              confidence: 0.82,
              status: 'needs_review',
            },
          ],
        },
      ],
    }))[0]!

    expect(calibrationHighlightTerms(block)).toContain('Φ100.58')
    expect(applyCalibrationHighlightsToHtml(block, block.content)).toContain('<mark')
    expect(applyCalibrationHighlightsToHtml(block, block.content)).toContain('Φ100.58')
  })

  it('shows review badge and highlights evidence without suggested text', () => {
    const block = resolvePreviewBlocks(buildItem({
      blocks: [
        {
          id: 'b1',
          block_type: 'paragraph',
          content: '电机定子外径 Φ150 415003',
          markdown: '电机定子外径 Φ150 415003',
          calibration_records: [
            {
              block_id: 'b1',
              issue_type: 'symbol_confusion',
              severity: 'warning',
              original_text: '电机定子外径 Φ150 415003',
              reason: '疑似 Φ 被识别为 4。',
              evidence: ['415003', 'Φ150.3'],
              confidence: 0.84,
              status: 'needs_review',
            },
          ],
        },
      ],
    }))[0]!

    expect(block?.calibrated).toBeFalsy()
    expect(block?.needs_calibration_review).toBe(true)
    expect(calibrationHighlightTerms(block)).toContain('415003')
    expect(renderCalibrationHighlightedHtml(block, block.content)).toContain('<mark')
    expect(renderCalibrationHighlightedHtml(block, block.content)).toContain('415003')
  })

  it('updateBlockContent syncs content and markdown fields', () => {
    const blocks: ParsePreviewBlock[] = [
      { id: 'b1', block_type: 'paragraph', content: 'a', markdown: 'a' },
      { id: 'b2', block_type: 'paragraph', content: 'b', markdown: 'b' },
    ]
    const updated = updateBlockContent(blocks, 'b1', 'edited')
    expect(updated[0]?.content).toBe('edited')
    expect(updated[0]?.markdown).toBe('edited')
    expect(updated[1]?.content).toBe('b')
  })

  it('buildMaterialJsonPreview uses display blocks when provided', () => {
    const item = buildItem({
      blocks: [{ id: 'b1', block_type: 'paragraph', content: 'hello' }],
    })
    const displayBlocks = [{ id: 'b1', block_type: 'paragraph', content: 'edited', markdown: 'edited' }]
    const payload = buildMaterialJsonPreview(item, undefined, displayBlocks)
    expect(payload.blocks).toEqual(displayBlocks)
  })

  it('blockDoubleClickNavigation switches to json tab with block id', () => {
    expect(blockDoubleClickNavigation('block-42')).toEqual({
      nextTab: 'json',
      activeBlockId: 'block-42',
    })
  })

  it('jsonBlockClickNavigation switches to markdown tab with block id', () => {
    expect(jsonBlockClickNavigation('block-42')).toEqual({
      nextTab: 'markdown',
      activeBlockId: 'block-42',
    })
  })

  it('blockContentEdited detects content changes', () => {
    const original: ParsePreviewBlock = {
      id: 'b1',
      block_type: 'paragraph',
      content: 'a',
      markdown: 'a',
    }
    const edited: ParsePreviewBlock = { ...original, content: 'b', markdown: 'b' }
    expect(blockContentEdited(original, edited)).toBe(true)
    expect(blockContentEdited(original, original)).toBe(false)
  })

  it('markdown segments and json export share the same preview blocks', () => {
    const item = buildItem({
      content_markdown: '# Legacy markdown should not drive JSON',
      blocks: [
        { id: 'b1', block_type: 'heading', content: 'Title', markdown: '# Title', page_hint: 1 },
        { id: 'b2', block_type: 'paragraph', content: 'Body', markdown: 'Body', page_hint: 1 },
      ],
    })
    const blocks = resolvePreviewBlocks(item)
    const payload = buildMaterialJsonPreview(item, undefined, blocks)

    expect(previewBlocksMatchJsonExport(blocks, payload)).toBe(true)
    expect(previewBlockMarkdownSegments(blocks)).toEqual(['# Title', 'Body'])
    expect((payload.blocks as ParsePreviewBlock[]).map((block) => blockDisplayMarkdown(block))).toEqual([
      '# Title',
      'Body',
    ])
  })

  it('edited draft blocks stay consistent between markdown and json export', () => {
    const item = buildItem({
      blocks: [{ id: 'b1', block_type: 'paragraph', content: 'hello', markdown: 'hello' }],
    })
    const blocks = resolvePreviewBlocks(item)
    const edited = updateBlockContent(blocks, 'b1', 'edited draft')
    const payload = buildMaterialJsonPreview(item, undefined, edited)

    expect(previewBlocksMatchJsonExport(edited, payload)).toBe(true)
    expect(blockDisplayMarkdown(edited[0]!)).toBe('edited draft')
    expect((payload.blocks as ParsePreviewBlock[])[0]?.content).toBe('edited draft')
    expect((payload.blocks as ParsePreviewBlock[])[0]?.markdown).toBe('edited draft')
  })
})
