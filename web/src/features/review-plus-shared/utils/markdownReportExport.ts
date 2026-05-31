import reviewPlusExportTemplate from '@/features/review-plus-v2/reviewPlusExportTemplate.json'
import {
  buildExportStyles,
  extractLeadingMarkdownTitle,
  stripLeadingMarkdownTitle,
} from '@/features/review-plus-v2/utils/reviewPlusExport'
import { resolveBusinessExportMarkdown } from '@/features/review-plus-shared/utils/businessReportMarkdown'

type ExportTemplate = typeof reviewPlusExportTemplate

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInlineMarkdown(value: unknown): string {
  return escapeHtml(value)
    .replace(/&lt;br\s*\/?&gt;/gi, '<br />')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function splitMarkdownTableRow(row: string): string[] {
  const trimmed = row.trim().replace(/^\|/, '').replace(/\|$/, '')
  const cells: string[] = []
  let current = ''
  let escaped = false
  for (const char of trimmed) {
    if (escaped) {
      current += char
      escaped = false
      continue
    }
    if (char === '\\') {
      escaped = true
      continue
    }
    if (char === '|') {
      cells.push(current.trim())
      current = ''
      continue
    }
    current += char
  }
  cells.push(current.trim())
  return cells
}

function isMarkdownTableSeparator(cells: string[]): boolean {
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
}

function renderTableHtml(headers: string[], rows: string[][]): string {
  const safeHeaders = headers.map((header) => renderInlineMarkdown(header || ' '))
  const width = Math.max(safeHeaders.length, ...rows.map((row) => row.length), 1)
  const normalizedHeaders = Array.from({ length: width }, (_, index) => safeHeaders[index] || ' ')
  const bodyRows = rows.length
    ? rows.map((row) => {
      const cells = Array.from({ length: width }, (_, index) => renderInlineMarkdown(row[index] || '—'))
      return `<tr>${cells.map((cell) => `<td>${cell}</td>`).join('')}</tr>`
    }).join('')
    : `<tr><td colspan="${width}">—</td></tr>`
  return `<table class="data-table"><thead><tr>${normalizedHeaders.map((header) => `<th>${header}</th>`).join('')}</tr></thead><tbody>${bodyRows}</tbody></table>`
}

function headingClassForLevel(level: number): string {
  if (level <= 1) return 'report-title'
  if (level === 2) return 'section-title'
  if (level === 3) return 'subsection-title'
  return 'subsubsection-title'
}

function renderMarkdownBody(markdown: string): string {
  const lines = markdown.split(/\r?\n/)
  const chunks: string[] = []
  let paragraph: string[] = []
  let inList = false
  let tableLines: string[] = []

  const flushParagraph = () => {
    if (!paragraph.length) return
    chunks.push(`<p>${renderInlineMarkdown(paragraph.join(' '))}</p>`)
    paragraph = []
  }

  const closeList = () => {
    if (!inList) return
    chunks.push('</ul>')
    inList = false
  }

  const flushTable = () => {
    if (tableLines.length < 2) {
      tableLines = []
      return
    }
    const parsedRows = tableLines.map(splitMarkdownTableRow).filter((row) => row.length > 1)
    if (parsedRows.length >= 2) {
      if (isMarkdownTableSeparator(parsedRows[1])) {
        chunks.push(renderTableHtml(parsedRows[0], parsedRows.slice(2)))
      } else {
        chunks.push(renderTableHtml(parsedRows[0], parsedRows.slice(1)))
      }
    }
    tableLines = []
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      flushParagraph()
      closeList()
      flushTable()
      continue
    }
    if (line.includes('|') && !/^#{1,6}\s+/.test(line)) {
      flushParagraph()
      closeList()
      tableLines.push(line.trim())
      continue
    }
    flushTable()
    if (/^#{1,6}\s+/.test(line)) {
      flushParagraph()
      closeList()
      const level = Math.min(6, line.match(/^#+/)?.[0].length || 2)
      const text = line.replace(/^#{1,6}\s+/, '')
      chunks.push(`<h${level} class="${headingClassForLevel(level)}">${renderInlineMarkdown(text)}</h${level}>`)
      continue
    }
    if (/^[-*]\s+/.test(line)) {
      flushParagraph()
      if (!inList) {
        chunks.push('<ul>')
        inList = true
      }
      chunks.push(`<li>${renderInlineMarkdown(line.replace(/^[-*]\s+/, ''))}</li>`)
      continue
    }
    closeList()
    paragraph.push(line)
  }

  flushParagraph()
  closeList()
  flushTable()
  return chunks.join('\n') || '<p>—</p>'
}

export interface MarkdownReportExportOptions {
  title: string
  subtitle?: string
  markdown: string
  metaRows?: Array<{ label: string; value: string }>
}

export function buildMarkdownReportExportHtml(options: MarkdownReportExportOptions): string {
  const template = reviewPlusExportTemplate as ExportTemplate
  const resolvedMarkdown = resolveBusinessExportMarkdown(options.markdown)
  const leadingTitle = extractLeadingMarkdownTitle(resolvedMarkdown)
  const documentTitle = leadingTitle || options.title || template.document.title
  const documentSubtitle = options.subtitle || template.document.subtitle
  const bodyMarkdown = stripLeadingMarkdownTitle(resolvedMarkdown)
  const metaRows = options.metaRows?.length
    ? options.metaRows
    : [
        { label: '审查日期', value: new Date().toLocaleDateString('zh-CN') },
        { label: '归档用途', value: '审查结论归档与线下流转' },
      ]

  const metaHtml = metaRows
    .reduce<string[][]>((rows, item, index) => {
      if (index % 2 === 0) rows.push([])
      rows[rows.length - 1].push(
        `<td><p class="meta-label">${escapeHtml(item.label)}</p><p class="meta-value">${escapeHtml(item.value)}</p></td>`,
      )
      return rows
    }, [])
    .map((cells) => {
      while (cells.length < 2) {
        cells.push('<td><p class="meta-label">—</p><p class="meta-value">—</p></td>')
      }
      return `<tr>${cells.join('')}</tr>`
    })
    .join('')

  return `<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:w="urn:schemas-microsoft-com:office:word"
      xmlns="http://www.w3.org/TR/REC-html40"
      lang="zh-CN">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="ProgId" content="Word.Document" />
    <meta name="Generator" content="Microsoft Word" />
    <title>${escapeHtml(documentTitle)}</title>
    <!--[if gte mso 9]><xml>
      <w:WordDocument>
        <w:View>Print</w:View>
        <w:Zoom>100</w:Zoom>
        <w:DoNotOptimizeForBrowser/>
      </w:WordDocument>
    </xml><![endif]-->
    <style>${buildExportStyles(template)}</style>
</head>
<body>
    <div class="sheet">
        <table class="doc-header">
            <tr>
                <td>${escapeHtml(template.document.headerTitle)}</td>
                <td class="right">${escapeHtml(template.document.issuingOrg)}</td>
            </tr>
        </table>
        <table class="header-rule" width="100%" cellpadding="0" cellspacing="0" role="presentation"><tr><td>&nbsp;</td></tr></table>
        <div class="title-block">
            <h1 class="doc-title">${escapeHtml(documentTitle)}</h1>
            <p class="subtitle">${escapeHtml(documentSubtitle)}</p>
        </div>
        <table class="meta-grid">${metaHtml}</table>
        <section class="section">
            <div class="report-body">${renderMarkdownBody(bodyMarkdown)}</div>
        </section>
        <div class="doc-footer">
            <p>${escapeHtml(template.document.footerNote || '本报告由审查工作台导出，用于审查归档、问题闭环和打印留痕。')}</p>
        </div>
    </div>
</body>
</html>`
}

export function buildMarkdownReportWordExportHtml(options: MarkdownReportExportOptions): string {
  return buildMarkdownReportExportHtml(options)
}
