import type { ParsePreviewBlock } from '@/features/super-agent/types'
import { blockLayoutDisplayText } from '@/features/super-agent/utils/parsePreviewBlocks'
import {
  ensureMathDelimitersInMarkdown,
  formulaToDisplayMarkdown,
  isFormulaBlockType,
  looksLikeLatexFormula,
  resolveLayoutBlockFormula,
  stripLatexPipeMarkers,
} from '@/features/super-agent/utils/formulaLayoutContent'
import { renderFormulasInLayoutTableHtml } from '@/features/super-agent/utils/layoutTableFormulaHtml'

function escapeGfmCell(value: string): string {
  return value.replace(/\|/g, '\\|').replace(/\n/g, '<br>')
}

function splitPipeRow(line: string): string[] {
  let stripped = line.trim()
  if (stripped.startsWith('|') && stripped.endsWith('|')) {
    stripped = stripped.slice(1, -1)
  }
  return stripped.split('|').map((cell) => cell.trim())
}

function isGfmSeparatorRow(line: string): boolean {
  return /^\|?\s*:?-{3,}/.test(line.trim())
}

export function isHtmlTable(text: string): boolean {
  return /<table[\s>]/i.test(text)
}

export function isTableBlockType(blockType: string): boolean {
  const value = blockType.toLowerCase()
  return value === 'table' || value.includes('table')
}

export function isFigureBlockType(blockType: string): boolean {
  const value = blockType.toLowerCase()
  return value === 'figure' || value.includes('image') || value.includes('figure')
}

/** Parse pipe-delimited or GFM-style table text into rows. */
export function parsePipeDelimitedRows(text: string): string[][] | null {
  const lines = stripLatexPipeMarkers(text)
    .trim()
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

  if (!lines.length) return null

  const rows: string[][] = []
  for (const line of lines) {
    if (!line.includes('|')) {
      if (rows.length) break
      continue
    }
    if (isGfmSeparatorRow(line)) continue
    rows.push(splitPipeRow(line))
  }

  if (!rows.length) return null

  const width = Math.max(...rows.map((row) => row.length))
  if (width < 2) return null

  return rows.map((row) => [...row, ...Array(Math.max(0, width - row.length)).fill('')])
}

export function looksLikeGfmMarkdownTable(text: string): boolean {
  const lines = text
    .trim()
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (lines.length < 2) return false
  return lines.some((line) => isGfmSeparatorRow(line))
}

export function looksLikePipeTable(text: string, blockType?: string): boolean {
  if (isFormulaBlockType(blockType ?? '') && looksLikeLatexFormula(text)) return false
  if (isTableBlockType(blockType ?? '')) return text.includes('|')
  if (looksLikeGfmMarkdownTable(text)) return true
  const pipeProbe = stripLatexPipeMarkers(text)
  if (!pipeProbe.includes('|')) return false
  const lines = pipeProbe
    .trim()
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (!lines.length) return false
  if (lines.length === 1) {
    const cells = splitPipeRow(lines[0]).map((cell) => cell.trim())
    if (cells.length < 2) return false
    if (cells.some((cell) => looksLikeLatexFormula(cell))) return false
    return true
  }
  return lines.filter((line) => line.includes('|')).length >= 2
}

export function pipeRowsToGfmTable(rows: string[][]): string {
  if (!rows.length) return ''
  const width = Math.max(...rows.map((row) => row.length))
  const padded = rows.map((row) => [...row, ...Array(Math.max(0, width - row.length)).fill('')])
  const [header, ...body] = padded
  const headerLine = `| ${header.map(escapeGfmCell).join(' | ')} |`
  const separatorLine = `| ${header.map(() => '---').join(' | ')} |`
  const bodyLines = body.map((row) => `| ${row.map(escapeGfmCell).join(' | ')} |`)
  return [headerLine, separatorLine, ...bodyLines].join('\n')
}

function escapeHtmlCell(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** Build a compact HTML table for layout-view mini rendering. */
export function pipeRowsToHtmlTable(rows: string[][]): string {
  if (!rows.length) return ''
  const width = Math.max(...rows.map((row) => row.length))
  const padded = rows.map((row) => [...row, ...Array(Math.max(0, width - row.length)).fill('')])
  const [first, ...rest] = padded
  if (!rest.length) {
    const cells = first.map((cell) => `<td>${escapeHtmlCell(cell)}</td>`).join('')
    return `<table><tbody><tr>${cells}</tr></tbody></table>`
  }
  const headerCells = first.map((cell) => `<th>${escapeHtmlCell(cell)}</th>`).join('')
  const bodyRows = rest
    .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtmlCell(cell)}</td>`).join('')}</tr>`)
    .join('')
  return `<table><thead><tr>${headerCells}</tr></thead><tbody>${bodyRows}</tbody></table>`
}

/** Strip wrapper noise so MinerU table HTML renders in the mini layout view. */
export function normalizeLayoutTableHtml(html: string): string {
  const trimmed = html.trim()
  const bodyMatch = trimmed.match(/<body[^>]*>([\s\S]*?)<\/body>/i)
  const inner = bodyMatch ? bodyMatch[1].trim() : trimmed
  if (isHtmlTable(inner)) return inner
  const tableMatch = inner.match(/<table[\s\S]*?<\/table>/i)
  return tableMatch ? tableMatch[0] : inner
}

function finalizeLayoutTableHtml(html: string): string {
  return renderFormulasInLayoutTableHtml(html)
}

/** Resolve layout block content as HTML when table-shaped; otherwise null. */
export function resolveLayoutBlockHtml(block: ParsePreviewBlock): string | null {
  const raw = blockLayoutDisplayText(block)
  if (!raw) return null
  if (isFormulaBlockType(block.block_type) && looksLikeLatexFormula(raw)) return null
  if (isHtmlTable(raw)) return finalizeLayoutTableHtml(normalizeLayoutTableHtml(raw))
  if (looksLikePipeTable(raw, block.block_type)) {
    const rows = parsePipeDelimitedRows(raw)
    if (rows?.length) return finalizeLayoutTableHtml(pipeRowsToHtmlTable(rows))
  }
  return null
}

/** Normalize block text for layout-view markdown rendering. */
export function resolveLayoutBlockMarkdown(block: ParsePreviewBlock): string {
  const formula = resolveLayoutBlockFormula(block)
  if (formula) return formulaToDisplayMarkdown(formula)

  const raw = blockLayoutDisplayText(block)
  if (!raw || isHtmlTable(raw)) return raw
  if (looksLikeGfmMarkdownTable(raw)) return raw
  if (looksLikePipeTable(raw, block.block_type)) {
    const rows = parsePipeDelimitedRows(raw)
    if (rows?.length) return pipeRowsToGfmTable(rows)
  }
  return ensureMathDelimitersInMarkdown(raw)
}
