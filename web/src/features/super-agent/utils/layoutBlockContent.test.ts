import { describe, expect, it } from 'vitest'
import { stripLatexPipeMarkers } from '@/features/super-agent/utils/formulaLayoutContent'
import {
  looksLikePipeTable,
  parsePipeDelimitedRows,
  pipeRowsToGfmTable,
  pipeRowsToHtmlTable,
  resolveLayoutBlockHtml,
  resolveLayoutBlockMarkdown,
} from '@/features/super-agent/utils/layoutBlockContent'
import type { ParsePreviewBlock } from '@/features/super-agent/types'

describe('layoutBlockContent', () => {
  it('parses single-line pipe-delimited table cells', () => {
    const rows = parsePipeDelimitedRows('产品代号 | 20-82C | 提出方 | 航天科技')
    expect(rows).toEqual([['产品代号', '20-82C', '提出方', '航天科技']])
  })

  it('converts pipe-delimited table block to gfm markdown', () => {
    const block: ParsePreviewBlock = {
      id: 't1',
      block_type: 'table',
      content: '产品代号 | 20-82C\n型号 | XX-1',
    }
    const markdown = resolveLayoutBlockMarkdown(block)
    expect(markdown).toContain('| 产品代号 | 20-82C |')
    expect(markdown).toContain('| --- | --- |')
    expect(markdown).toContain('| 型号 | XX-1 |')
  })

  it('keeps existing gfm markdown tables unchanged', () => {
    const gfm = '| A | B |\n| --- | --- |\n| 1 | 2 |'
    const block: ParsePreviewBlock = {
      id: 't2',
      block_type: 'table',
      content: gfm,
    }
    expect(resolveLayoutBlockMarkdown(block)).toBe(gfm)
  })

  it('detects pipe tables for table block type', () => {
    expect(looksLikePipeTable('a | b', 'table')).toBe(true)
    expect(looksLikePipeTable('plain text', 'paragraph')).toBe(false)
  })

  it('builds gfm table from parsed rows', () => {
    expect(pipeRowsToGfmTable([['H1', 'H2'], ['V1', 'V2']])).toBe(
      '| H1 | H2 |\n| --- | --- |\n| V1 | V2 |',
    )
  })

  it('builds html table from single-line pipe rows', () => {
    const html = pipeRowsToHtmlTable([['产品代号', '20-82C', '提出方', '航天科技']])
    expect(html).toContain('<table>')
    expect(html).toContain('<td>产品代号</td>')
    expect(html).toContain('<td>20-82C</td>')
  })

  it('resolves pipe-delimited table block to html', () => {
    const block: ParsePreviewBlock = {
      id: 't3',
      block_type: 'table',
      content: '产品代号 | 20-82C | 提出方 | 航天科技',
    }
    const html = resolveLayoutBlockHtml(block)
    expect(html).toContain('<table>')
    expect(html).not.toContain('|')
  })

  it('renders inline latex in pipe table cells', () => {
    const block: ParsePreviewBlock = {
      id: 't3b',
      block_type: 'table',
      content: '项目 | 值\n温度 | $230^{\\circ}C$',
    }
    const html = resolveLayoutBlockHtml(block)
    expect(html).toContain('class="katex"')
    expect(html).not.toContain('$230')
  })

  it('extracts table element from html wrapper', () => {
    const block: ParsePreviewBlock = {
      id: 't4b',
      block_type: 'table',
      content: '<html><body><table><tr><td>A</td></tr></table></body></html>',
    }
    expect(resolveLayoutBlockHtml(block)).toBe('<table><tr><td>A</td></tr></table>')
  })

  it('preserves html table content', () => {
    const block: ParsePreviewBlock = {
      id: 't4',
      block_type: 'table',
      content: '<table><tr><td>A</td><td>B</td></tr></table>',
    }
    expect(resolveLayoutBlockHtml(block)).toContain('<table>')
  })

  it('prefers full content over truncated markdown for layout display', () => {
    const block: ParsePreviewBlock = {
      id: 't5',
      block_type: 'table',
      content: '产品代号 | 20-82C | 提出方 | 航天科技',
      markdown: '产品代号 | 20-82C | …',
    }
    expect(resolveLayoutBlockMarkdown(block)).toContain('航天科技')
    expect(resolveLayoutBlockMarkdown(block)).not.toContain('…')
  })

  it('does not split Jacobian Bigg| lines into pipe table rows', () => {
    const jacobian =
      '\\boldsymbol{H}=\\frac{a}{b}\\Bigg|_{x=1}\\approx\\left[\\begin{array}{cc}1&0\\\\0&1\\end{array}\\right]'
    expect(stripLatexPipeMarkers(jacobian)).not.toContain('|')
    expect(parsePipeDelimitedRows(jacobian)).toBeNull()
    expect(looksLikePipeTable(jacobian, 'paragraph')).toBe(false)
  })

  it('preserves colspan and rowspan in html tables', () => {
    const block: ParsePreviewBlock = {
      id: 't6',
      block_type: 'table',
      content:
        '<table><tr><td colspan="2">提出方</td><td rowspan="3">郭丹</td></tr><tr><td>A</td></tr></table>',
    }
    const html = resolveLayoutBlockHtml(block)
    expect(html).toContain('colspan="2"')
    expect(html).toContain('rowspan="3"')
  })
})
