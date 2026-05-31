import JSZip from 'jszip'
import XLSX from 'xlsx'
import { describe, expect, it } from 'vitest'
import {
  buildOfficePreview,
  extractPptxSlideTexts,
  sortPptxSlideNames,
  wrapWordPreviewHtml,
} from '@/features/super-agent/utils/officePreview'

describe('officePreview', () => {
  it('wraps word html in page containers and splits on page breaks', () => {
    expect(wrapWordPreviewHtml('<p>One</p>')).toBe('<div class="docx-preview-page"><p>One</p></div>')
    expect(wrapWordPreviewHtml('<p>One</p><hr class="docx-page-break" /><p>Two</p>')).toBe(
      '<div class="docx-preview-page"><p>One</p></div><div class="docx-preview-page"><p>Two</p></div>',
    )
  })

  it('builds xlsx preview from a minimal workbook', async () => {
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([['Name', 'Value'], ['foo', 42]]), 'Data')
    const buffer = XLSX.write(workbook, { type: 'buffer', bookType: 'xlsx' })
    const data = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength)

    const preview = await buildOfficePreview('sample.xlsx', data)

    expect(preview?.kind).toBe('excel')
    expect(preview?.pageCount).toBe(1)
    expect(preview?.sheets?.[0]?.name).toBe('Data')
    expect(preview?.sheets?.[0]?.html).toContain('<table')
    expect(preview?.sheets?.[0]?.html).toContain('foo')
  })

  it('skips empty sheets without failing other sheets', async () => {
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([['Name', 'Value'], ['foo', 42]]), 'Sheet1')
    XLSX.utils.book_append_sheet(workbook, {}, 'Sheet2')
    const buffer = XLSX.write(workbook, { type: 'buffer', bookType: 'xlsx' })
    const data = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength)

    const preview = await buildOfficePreview('sample.xlsx', data)

    expect(preview?.kind).toBe('excel')
    expect(preview?.pageCount).toBe(2)
    expect(preview?.sheets).toHaveLength(2)
    expect(preview?.sheets?.[0]?.html).toContain('<table')
    expect(preview?.sheets?.[0]?.html).toContain('foo')
    expect(preview?.sheets?.[1]?.html).toContain('office-preview-empty-sheet')
    expect(preview?.sheets?.[1]?.html).not.toContain('<table')
  })

  it('uses stable sheet ids when building xlsx preview html', async () => {
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([['A']]), 'My Sheet')
    const buffer = XLSX.write(workbook, { type: 'buffer', bookType: 'xlsx' })
    const data = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength)

    const preview = await buildOfficePreview('sample.xlsx', data)

    expect(preview?.sheets?.[0]?.html).toContain('id="sheet-1"')
    expect(preview?.sheets?.[0]?.html).not.toContain('id="sheet-My Sheet"')
  })

  it('extracts text nodes from pptx slide xml', () => {
    const xml = `
      <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
        <a:t>Hello</a:t>
        <a:t>World</a:t>
      </p:sld>
    `
    expect(extractPptxSlideTexts(xml)).toEqual(['Hello', 'World'])
  })

  it('sorts pptx slide xml paths numerically', () => {
    expect(
      sortPptxSlideNames(['ppt/slides/slide10.xml', 'ppt/slides/slide2.xml', 'ppt/media/image1.png']),
    ).toEqual(['ppt/slides/slide2.xml', 'ppt/slides/slide10.xml'])
  })

  it('builds pptx preview from a minimal archive', async () => {
    const zip = new JSZip()
    zip.file(
      'ppt/slides/slide1.xml',
      '<a:t xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">Title</a:t>',
    )
    zip.file(
      'ppt/slides/slide2.xml',
      '<a:t xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">Body</a:t>',
    )
    const data = await zip.generateAsync({ type: 'arraybuffer' })
    const preview = await buildOfficePreview('deck.pptx', data)
    expect(preview?.kind).toBe('ppt')
    expect(preview?.pageCount).toBe(2)
    expect(preview?.slides?.[0]?.lines).toEqual(['Title'])
    expect(preview?.slides?.[1]?.lines).toEqual(['Body'])
  })
})
