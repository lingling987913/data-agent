import reviewPlusExportTemplate from '@/features/review-plus-v2/reviewPlusExportTemplate.json'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import {
  JUDGMENT_LABELS,
  SEVERITY_LABELS,
  STATUS_LABELS,
} from '@/features/review-plus-v2/types'
import { formatReviewPlusScenarioLabel } from '@/features/review-plus-v2/utils/reviewPlusUx'
import { resolveBusinessExportMarkdown } from '@/features/review-plus-shared/utils/businessReportMarkdown'
import { resolveVerdictLabel } from '@/features/unified-review-workbench/utils/zhWorkbenchText'

type ExportTemplate = typeof reviewPlusExportTemplate

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleDateString('zh-CN')
}

function formatPercent(total: number, satisfied: number): string {
  if (total <= 0) return '0%'
  return `${Math.round((satisfied / total) * 100)}%`
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

  return `
            <table class="data-table">
                <thead><tr>${normalizedHeaders.map((header) => `<th>${header}</th>`).join('')}</tr></thead>
                <tbody>${bodyRows}</tbody>
            </table>`
}

function renderMarkdownTableBlock(block: string): string | null {
  const lines = block.split('\n').map((line) => line.trim()).filter(Boolean)
  const pipeLines = lines.filter((line) => line.includes('|'))
  if (pipeLines.length < 2 || pipeLines.length !== lines.length) return null

  const parsedRows = pipeLines.map(splitMarkdownTableRow).filter((row) => row.length > 1)
  if (parsedRows.length < 2) return null

  if (isMarkdownTableSeparator(parsedRows[1])) {
    return renderTableHtml(parsedRows[0], parsedRows.slice(2))
  }

  return renderTableHtml(parsedRows[0], parsedRows.slice(1))
}

function renderListBlock(block: string): string | null {
  const lines = block.split('\n').map((line) => line.trim()).filter(Boolean)
  if (!lines.length) return null

  const unordered = lines.every((line) => /^[-*]\s+/.test(line))
  if (unordered) {
    return `<ul>${lines.map((line) => `<li>${renderInlineMarkdown(line.replace(/^[-*]\s+/, ''))}</li>`).join('')}</ul>`
  }

  const ordered = lines.every((line) => /^\d+[.)、]\s+/.test(line))
  if (ordered) {
    return `<ol>${lines.map((line) => `<li>${renderInlineMarkdown(line.replace(/^\d+[.)、]\s+/, ''))}</li>`).join('')}</ol>`
  }

  return null
}

function headingClassForLevel(level: number): string {
  if (level <= 1) return 'report-title'
  if (level === 2) return 'section-title'
  if (level === 3) return 'subsection-title'
  return 'subsubsection-title'
}

/** First markdown H1, if the document starts with one. */
export function extractLeadingMarkdownTitle(markdown: string): string | null {
  const firstLine = markdown.trim().split(/\r?\n/, 1)[0]?.trim()
  if (!firstLine?.startsWith('# ')) return null
  return firstLine.slice(2).trim() || null
}

/** Remove a leading H1 block so the export shell does not render the title twice. */
export function stripLeadingMarkdownTitle(markdown: string): string {
  const lines = markdown.trim().split(/\r?\n/)
  if (!lines[0]?.trim().startsWith('# ')) return markdown
  lines.shift()
  while (lines.length && lines[0].trim() === '') lines.shift()
  return lines.join('\n')
}

function renderHeaderRule(): string {
  return '<table class="header-rule" width="100%" cellpadding="0" cellspacing="0" role="presentation"><tr><td>&nbsp;</td></tr></table>'
}

function renderMetaCell(label: string, value: unknown): string {
  return `<td><p class="meta-label">${escapeHtml(label)}</p><p class="meta-value">${escapeHtml(value)}</p></td>`
}

function renderSummaryCell(label: string, value: unknown): string {
  return `<td><p class="summary-label">${escapeHtml(label)}</p><p class="summary-value">${escapeHtml(value)}</p></td>`
}

function renderHeadingBlock(level: number, trimmed: string): string {
  const marker = '#'.repeat(level) + ' '
  if (!trimmed.startsWith(marker)) return ''
  const lines = trimmed.split('\n')
  const title = lines[0].slice(marker.length).trim()
  const body = lines.slice(1).join('\n').trim()
  const heading = `<h${level} class="${headingClassForLevel(level)}">${escapeHtml(title)}</h${level}>`
  if (!body) return heading
  return `${heading}\n<p>${renderInlineMarkdown(body).replace(/\n/g, '<br />')}</p>`
}

function renderMarkdownBody(markdown: string): string {
  if (!markdown.trim()) return ''
  return markdown
    .split(/\n{2,}/)
    .map((block) => {
      const trimmed = block.trim()
      if (!trimmed) return ''
      const table = renderMarkdownTableBlock(trimmed)
      if (table) return table
      const list = renderListBlock(trimmed)
      if (list) return list
      if (trimmed.startsWith('#### ')) return renderHeadingBlock(4, trimmed)
      if (trimmed.startsWith('### ')) return renderHeadingBlock(3, trimmed)
      if (trimmed.startsWith('## ')) return renderHeadingBlock(2, trimmed)
      if (trimmed.startsWith('# ')) return renderHeadingBlock(1, trimmed)
      if (trimmed.startsWith('> ')) {
        return `<blockquote>${renderInlineMarkdown(trimmed.replace(/^>\s?/, ''))}</blockquote>`
      }
      return `<p>${renderInlineMarkdown(trimmed).replace(/\n/g, '<br />')}</p>`
    })
    .filter(Boolean)
    .join('\n')
}

function formatJudgment(value?: string | null): string {
  return JUDGMENT_LABELS[String(value || '')] || value || '未检查'
}

function findingByCheckItem(task: ReviewPlusTaskDetail): Map<string, NonNullable<ReviewPlusTaskDetail['findings']>[number]> {
  const map = new Map<string, NonNullable<ReviewPlusTaskDetail['findings']>[number]>()
  for (const finding of task.findings || []) {
    if (finding.check_item_id) map.set(finding.check_item_id, finding)
  }
  return map
}

function buildChecklistConclusionTable(task: ReviewPlusTaskDetail): string {
  const checkItems = [...(task.check_items || [])]
  if (!checkItems.length) {
    return '<p class="muted">未提取到检查单或检查对照表条目。</p>'
  }

  const findingsByItem = findingByCheckItem(task)
  const sortedItems = checkItems.sort((a, b) => {
    const sourceA = `${a.source_material_name || ''}:${a.source_sheet || ''}`
    const sourceB = `${b.source_material_name || ''}:${b.source_sheet || ''}`
    if (sourceA !== sourceB) return sourceA.localeCompare(sourceB, 'zh-CN')
    return (a.source_row ?? 0) - (b.source_row ?? 0)
  })

  const rows = sortedItems.map((item) => {
    const finding = findingsByItem.get(item.check_item_id)
    const sourceParts = [
      item.source_material_name,
      item.source_sheet,
      item.source_row ? `第 ${item.source_row} 行` : '',
    ].filter(Boolean)
    const evidence = [
      finding?.reasoning,
      finding?.recommendation ? `建议：${finding.recommendation}` : '',
    ].filter(Boolean).join('\n')

    return [
      item.item_no || item.check_item_id,
      item.title || '—',
      item.requirement_text || item.source_quote || '—',
      item.acceptance_criteria || '—',
      sourceParts.join(' / ') || '—',
      formatJudgment(finding?.judgment),
      evidence || finding?.source_quote || item.source_quote || '—',
    ]
  })

  return renderTableHtml(
    ['原序号', '检查项目', '检查要求 / 原文', '验收准则', '来源位置', '审查结论', '判定依据与建议'],
    rows,
  )
}

function buildIssueRows(task: ReviewPlusTaskDetail): string {
  const issues = (task.findings || []).filter((finding) => {
    const judgment = String(finding.judgment || '')
    const severity = String(finding.severity || '').toLowerCase()
    return judgment === 'not_satisfied'
      || judgment === 'insufficient_evidence'
      || ['critical', 'major'].includes(severity)
  }).slice(0, 40)

  if (!issues.length) {
    return '<tr><td colspan="4">未发现需单独列示的不符合或证据不足项。</td></tr>'
  }

  return issues.map((finding) => `
            <tr>
                <td>${escapeHtml(SEVERITY_LABELS[String(finding.severity || '').toLowerCase()] || finding.severity || '—')}</td>
                <td>${escapeHtml(JUDGMENT_LABELS[String(finding.judgment || '')] || finding.judgment || '—')}</td>
                <td>${escapeHtml(finding.title || '未命名发现')}</td>
                <td>${escapeHtml(finding.reasoning || finding.recommendation || finding.source_quote || '—')}</td>
            </tr>
        `).join('')
}

function buildCrossDocRows(task: ReviewPlusTaskDetail): string {
  const report = task.report
  const crossDocItems = (report?.cross_document_items as Array<Record<string, unknown>> | undefined)
    ?? task.cross_document_review_items?.map((item) => ({
      title: item.title,
      description: item.description,
    }))
    ?? []

  if (!crossDocItems.length) {
    return '<tr><td colspan="3">未发现需记录的跨文档一致性问题。</td></tr>'
  }

  return crossDocItems.slice(0, 20).map((item, index) => `
            <tr>
                <td>${index + 1}</td>
                <td>${escapeHtml(String(item.title || item.description || '跨文档问题'))}</td>
                <td>${escapeHtml(String(item.description || item.recommendation || item.title || '—'))}</td>
            </tr>
        `).join('')
}

function buildSignatureTable(): string {
  return `
            <table class="data-table signature-table">
                <thead><tr><th style="width:25%;">角色</th><th style="width:25%;">签署/确认</th><th style="width:25%;">日期</th><th style="width:25%;">备注</th></tr></thead>
                <tbody>
                    <tr><td>送审负责人</td><td></td><td></td><td>确认送审包与材料角色</td></tr>
                    <tr><td>审查负责人</td><td></td><td></td><td>确认符合性审查结论</td></tr>
                    <tr><td>质量/归档</td><td></td><td></td><td>确认归档与问题闭环</td></tr>
                </tbody>
            </table>`
}

function markdownHasChecklistAppendix(markdown: string): boolean {
  return /##\s*附件[：:]\s*符合性检查清单/.test(markdown)
    || /##\s*[0-9]+[.、]\s*符合性检查单/.test(markdown)
}

export function buildExportStyles(template: ExportTemplate): string {
  const { document: doc, layout, palette } = template
  const bodyLineHeight = layout.lineHeight.includes('%') ? layout.lineHeight : '175%'
  return `
        @page Section1 {
            size: A4 portrait;
            margin: ${layout.pageMarginMm};
            mso-header-margin: 14.2pt;
            mso-footer-margin: 14.2pt;
        }
        @page { size: A4 portrait; margin: ${layout.pageMarginMm}; }
        body {
            font-family: ${doc.fontFamily};
            font-size: ${layout.bodyFontSize};
            line-height: ${bodyLineHeight};
            color: ${palette.text};
            background: ${palette.pageBg};
            margin: 0;
            mso-line-height-rule: at-least;
        }
        .sheet {
            width: 100%;
            margin: 0;
            background: ${palette.sheetBg};
            padding: 0;
        }
        .doc-header {
            width: 100%;
            border-collapse: collapse;
            font-size: ${layout.headerFontSize};
            color: ${palette.muted};
            margin: 0 0 6pt;
        }
        .doc-header td { border: 0; padding: 0 0 4pt; vertical-align: bottom; }
        .doc-header .right { text-align: right; }
        .header-rule {
            width: 100%;
            border-collapse: collapse;
            margin: 0 0 16pt;
        }
        .header-rule td {
            border: 0;
            border-top: 2pt solid ${palette.headerRule};
            padding: 0;
            font-size: 1pt;
            line-height: 1pt;
        }
        .title-block {
            text-align: center;
            margin: 0 0 18pt;
        }
        .doc-title, h1.doc-title {
            font-family: ${doc.titleFontFamily};
            font-size: ${layout.titleFontSize};
            font-weight: 700;
            line-height: 150%;
            margin: 0 0 8pt;
            padding: 0;
            color: ${palette.heading};
            text-align: center;
        }
        .report-title, h1.report-title {
            font-family: ${doc.headingFontFamily};
            font-size: ${layout.sectionTitleFontSize};
            font-weight: 700;
            line-height: 150%;
            margin: 16pt 0 8pt;
            padding: 0;
            color: ${palette.heading};
            text-align: left;
        }
        .subtitle {
            font-size: ${layout.subtitleFontSize};
            color: ${palette.muted};
            margin: 0;
            padding: 0;
            line-height: 150%;
            text-align: center;
        }
        .meta-grid {
            width: 100%;
            border-collapse: collapse;
            margin: 0 0 16pt;
            table-layout: fixed;
        }
        .meta-grid td {
            border: 1pt solid ${palette.border};
            padding: 8pt 10pt;
            vertical-align: top;
        }
        .meta-label, .meta-grid .label {
            font-family: ${doc.headingFontFamily};
            font-size: ${layout.tableFontSize};
            color: ${palette.muted};
            margin: 0 0 3pt;
            padding: 0;
            line-height: 140%;
        }
        .meta-value, .meta-grid .value {
            font-size: ${layout.bodyFontSize};
            line-height: ${bodyLineHeight};
            color: ${palette.text};
            margin: 0;
            padding: 0;
            word-wrap: break-word;
        }
        .summary-strip {
            width: 100%;
            border-collapse: collapse;
            margin: 0 0 18pt;
        }
        .summary-strip td {
            border: 1pt solid ${palette.border};
            padding: 8pt 10pt;
            text-align: center;
            vertical-align: top;
            width: 25%;
        }
        .summary-label, .summary-strip .label {
            font-size: ${layout.tableFontSize};
            color: ${palette.muted};
            margin: 0 0 4pt;
            padding: 0;
            line-height: 140%;
        }
        .summary-value, .summary-strip .value {
            font-family: ${doc.headingFontFamily};
            font-size: 16pt;
            font-weight: 700;
            margin: 0;
            padding: 0;
            line-height: 140%;
        }
        .section { margin-top: 14pt; }
        .report-body { margin: 0; padding: 0; }
        .section-title, h2.section-title {
            font-family: ${doc.headingFontFamily};
            font-size: ${layout.sectionTitleFontSize};
            font-weight: 700;
            line-height: 150%;
            color: ${palette.heading};
            margin: 14pt 0 8pt;
            padding: 0;
        }
        .subsection-title, h3.subsection-title {
            font-family: ${doc.headingFontFamily};
            font-size: ${layout.bodyFontSize};
            font-weight: 700;
            line-height: 150%;
            margin: 10pt 0 6pt;
            padding: 0;
        }
        .subsubsection-title, h4.subsubsection-title {
            font-family: ${doc.headingFontFamily};
            font-size: ${layout.tableFontSize};
            font-weight: 700;
            line-height: 150%;
            margin: 8pt 0 4pt;
            padding: 0;
        }
        .panel {
            border: 1pt solid ${palette.border};
            padding: 10pt 12pt;
            margin-top: 6pt;
        }
        .panel p, p {
            margin: 6pt 0;
            line-height: ${bodyLineHeight};
            text-align: justify;
            text-justify: inter-ideograph;
        }
        .appendix { page-break-before: always; margin-top: 24pt; }
        .appendix .section-title { text-align: center; }
        table.data-table {
            width: 100%;
            border-collapse: collapse;
            border-spacing: 0;
            margin: 10pt 0 14pt;
            table-layout: fixed;
            mso-table-layout-alt: fixed;
        }
        table.data-table th, table.data-table td {
            border: 1pt solid ${palette.border};
            padding: 6pt 7pt;
            vertical-align: top;
            text-align: left;
            font-size: ${layout.tableFontSize};
            line-height: 160%;
            word-wrap: break-word;
            mso-line-height-rule: at-least;
        }
        table.data-table th {
            font-family: ${doc.headingFontFamily};
            background: ${palette.tableHeadBg};
            font-weight: 700;
            text-align: center;
        }
        table.signature-table td { padding-top: 18pt; padding-bottom: 18pt; }
        blockquote {
            margin: 8pt 0;
            padding: 6pt 10pt;
            border-left: 3pt solid ${palette.border};
            color: ${palette.muted};
        }
        code {
            font-family: Consolas, "Courier New", monospace;
            font-size: 10pt;
            background: ${palette.tableHeadBg};
            padding: 1pt 3pt;
        }
        .muted { color: ${palette.muted}; font-size: ${layout.tableFontSize}; }
        .doc-footer {
            margin-top: 24pt;
            padding-top: 8pt;
            border-top: 1pt solid ${palette.border};
            font-size: ${layout.footerFontSize};
            color: ${palette.muted};
            text-align: center;
        }
        .doc-footer p { margin: 0; text-align: center; }
        ul, ol { margin: 6pt 0 6pt 18pt; padding: 0; }
        li { margin: 3pt 0; line-height: ${bodyLineHeight}; }
        @media print { body { background: ${palette.sheetBg}; } }
  `
}

export function buildReviewPlusExportHtml(
  task: ReviewPlusTaskDetail,
  reportMarkdown = '',
  options?: {
    documentTitle?: string
    documentSubtitle?: string
  },
): string {
  const template = reviewPlusExportTemplate
  const report = task.report
  const scenarioLabel = formatReviewPlusScenarioLabel(task.scenario) || '—'
  const rawMarkdown = resolveBusinessExportMarkdown(
    reportMarkdown || task.report_markdown || report?.markdown || '',
  )
  const leadingTitle = extractLeadingMarkdownTitle(rawMarkdown)
  const documentTitle = leadingTitle
    || options?.documentTitle
    || template.document.title
  const documentSubtitle = options?.documentSubtitle || template.document.subtitle
  const markdown = stripLeadingMarkdownTitle(rawMarkdown)

  const total = report?.total_check_items ?? task.check_items?.length ?? 0
  const satisfied = report?.satisfied_count ?? 0
  const notSatisfied = report?.not_satisfied_count ?? 0
  const insufficient = report?.insufficient_evidence_count ?? 0

  const residualRisks = report?.residual_risks?.length
    ? report.residual_risks.map((risk) => `<li>${escapeHtml(risk)}</li>`).join('')
    : ''

  const markdownBody = renderMarkdownBody(markdown)
  const useMarkdownLayout = Boolean(markdownBody)
  const showChecklistAppendix = !markdownHasChecklistAppendix(markdown)

  const mainSections = useMarkdownLayout
    ? `
        <section class="section">
            <div class="report-body">${markdownBody}</div>
        </section>`
    : `
        <section class="section">
            <h2 class="section-title">一、总体审查结论</h2>
            <div class="panel">
                <p><strong>结论：</strong>${escapeHtml(resolveVerdictLabel(report?.conclusion, report?.conclusion || '尚未形成审查结论'))}</p>
                <p><strong>摘要：</strong>${escapeHtml(report?.summary || '—')}</p>
                ${residualRisks ? `<p><strong>剩余风险：</strong></p><ul>${residualRisks}</ul>` : ''}
            </div>
        </section>
        <section class="section">
            <h2 class="section-title">二、不符合项与问题说明</h2>
            <table class="data-table">
                <thead><tr><th style="width:12%;">严重度</th><th style="width:12%;">判定</th><th style="width:26%;">问题</th><th style="width:50%;">说明</th></tr></thead>
                <tbody>${buildIssueRows(task)}</tbody>
            </table>
        </section>
        <section class="section">
            <h2 class="section-title">三、跨文档一致性审查</h2>
            <table class="data-table">
                <thead><tr><th style="width:8%;">序号</th><th style="width:30%;">问题</th><th style="width:62%;">说明与建议</th></tr></thead>
                <tbody>${buildCrossDocRows(task)}</tbody>
            </table>
        </section>
        <section class="section">
            <h2 class="section-title">四、审签栏</h2>
            ${buildSignatureTable()}
        </section>`

  const checklistAppendix = showChecklistAppendix
    ? `
        <section class="section appendix">
            <h2 class="section-title">附件：符合性检查清单</h2>
            <p class="muted">以下按原检查项来源顺序汇总检查单条目，并附本轮审查判定、依据与建议。</p>
            <p class="muted">统计：共 ${escapeHtml(total)} 项；符合 ${escapeHtml(satisfied)} 项；不符合 ${escapeHtml(notSatisfied)} 项；证据不足 ${escapeHtml(insufficient)} 项；通过率 ${escapeHtml(formatPercent(total, satisfied))}。</p>
            ${buildChecklistConclusionTable(task)}
        </section>`
    : ''

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
    <title>${escapeHtml(task.name || documentTitle)}</title>
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
        ${renderHeaderRule()}
        <div class="title-block">
            <h1 class="doc-title">${escapeHtml(documentTitle)}</h1>
            <p class="subtitle">${escapeHtml(documentSubtitle)}</p>
        </div>
        <table class="meta-grid">
            <tr>
                ${renderMetaCell('审查任务', task.name || '—')}
                ${renderMetaCell('审查场景', scenarioLabel)}
            </tr>
            <tr>
                ${renderMetaCell('审查日期', formatDateTime(task.updated_at || new Date().toISOString()))}
                ${renderMetaCell('送审材料数', task.materials?.length ?? 0)}
            </tr>
            <tr>
                ${renderMetaCell('任务状态', STATUS_LABELS[String(task.status)] || String(task.status || '—'))}
                ${renderMetaCell('归档用途', '审查结论归档与线下流转')}
            </tr>
        </table>
        <table class="summary-strip">
            <tr>
                ${renderSummaryCell('检查项', total)}
                ${renderSummaryCell('符合', satisfied)}
                ${renderSummaryCell('不符合', notSatisfied)}
                ${renderSummaryCell('通过率', formatPercent(total, satisfied))}
            </tr>
        </table>
        ${mainSections}
        ${checklistAppendix}
        <div class="doc-footer">
            <p>${escapeHtml(template.document.footerNote || '本审查单用于审查结论归档、问题闭环和打印留痕。')}</p>
        </div>
    </div>
</body>
</html>`
}

export function buildReviewPlusWordExportHtml(
  task: ReviewPlusTaskDetail,
  reportMarkdown = '',
): string {
  return buildReviewPlusExportHtml(task, reportMarkdown, {
    documentTitle: reviewPlusExportTemplate.document.title,
  })
}
