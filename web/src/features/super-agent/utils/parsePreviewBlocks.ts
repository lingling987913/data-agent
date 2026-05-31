import type { MaterialParsePreviewItem, ParsePreviewBlock, ParsePreviewResponse } from '@/features/super-agent/types'
import { resolveFigureDisplayText, isVisualImageBlock, resolveFigureDescription } from '@/features/super-agent/utils/figureBlockContent'
import {
  ensureMathDelimitersInMarkdown,
  formulaToDisplayMarkdown,
  isFormulaBlockType,
  isStandaloneFormulaText,
  normalizeFormulaLatex,
  shouldRenderPreviewWithMarkdown,
} from '@/features/super-agent/utils/formulaLayoutContent'
import {
  isHtmlTable,
  looksLikeGfmMarkdownTable,
  looksLikePipeTable,
  parsePipeDelimitedRows,
  pipeRowsToGfmTable,
} from '@/features/super-agent/utils/layoutBlockContent'
import { resolvePreviewMarkdown } from '@/features/super-agent/utils/parsePreviewFormat'

const CALIBRATION_HIGHLIGHT_STYLE = 'background-color:#fee2e2;color:#b91c1c;border:1px solid #fecaca;border-radius:3px;padding:0 2px;font-weight:600;'

export function resolvePreviewBlocks(item: MaterialParsePreviewItem): ParsePreviewBlock[] {
  if (item.blocks?.length) {
    return item.blocks.map((block, index) => applyCalibrationToPreviewBlock({
      ...block,
      id: block.id || `block-${index}`,
      markdown: block.markdown || block.content,
    }))
  }
  const markdown = resolvePreviewMarkdown(item).trim()
  if (!markdown) return []
  return [
    {
      id: 'fallback-markdown',
      block_type: 'paragraph',
      content: markdown,
      markdown,
      page_hint: 1,
    },
  ]
}

export function activeCalibrationRecord(block: ParsePreviewBlock) {
  return (block.calibration_records ?? []).find((item) => {
    const status = item.status ?? 'needs_review'
    return status !== 'dismissed'
  })
}

export function needsCalibrationReview(block: ParsePreviewBlock): boolean {
  const record = activeCalibrationRecord(block)
  if (!record) return false
  return Boolean(record.suggested_text?.trim()) || (record.status ?? 'needs_review') === 'needs_review'
}

export function activeCalibrationSuggestion(block: ParsePreviewBlock): string {
  const record = (block.calibration_records ?? []).find((item) => {
    const status = item.status ?? 'needs_review'
    return status !== 'dismissed' && Boolean(item.suggested_text?.trim())
  })
  return record?.suggested_text?.trim() ?? ''
}

export function applyCalibrationToPreviewBlock(block: ParsePreviewBlock): ParsePreviewBlock {
  const suggested = activeCalibrationSuggestion(block)
  const needsReview = needsCalibrationReview(block)
  if (!suggested && !needsReview) return block
  if (suggested) {
    return {
      ...block,
      original_content: block.original_content ?? block.content,
      original_markdown: block.original_markdown ?? (block.markdown ?? block.content),
      content: suggested,
      markdown: suggested,
      calibrated: true,
      needs_calibration_review: needsReview,
    }
  }
  return {
    ...block,
    needs_calibration_review: true,
  }
}

export function resolvePageCount(item: MaterialParsePreviewItem, blocks: ParsePreviewBlock[]): number {
  const fromItem = item.page_count ?? item.document_ir_stats?.page_count ?? 0
  const hinted = blocks
    .map((block) => block.page_hint)
    .filter((page): page is number => typeof page === 'number' && page > 0)
  const maxHinted = hinted.length ? Math.max(...hinted) : 0
  return Math.max(fromItem, maxHinted, 1)
}

export function buildPdfViewerSrc(baseUrl: string, page: number): string {
  const normalized = baseUrl.split('#')[0]
  if (!normalized) return ''
  return `${normalized}#page=${Math.max(1, page)}`
}

export function blocksForPage(blocks: ParsePreviewBlock[], page: number): ParsePreviewBlock[] {
  if (page <= 0) return blocks
  return blocks.filter((block) => (block.page_hint ?? 1) === page)
}

export function firstBlockPage(blocks: ParsePreviewBlock[]): number {
  for (const block of blocks) {
    if (typeof block.page_hint === 'number' && block.page_hint > 0) {
      return block.page_hint
    }
  }
  return 1
}

export function scrollMarkdownToPage(container: HTMLElement | null, page: number): void {
  if (!container || page <= 0) return
  const target = container.querySelector<HTMLElement>(`[data-page-hint="${page}"]`)
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

export function scrollMarkdownToBlock(container: HTMLElement | null, blockId: string): void {
  if (!container || !blockId) return
  const target = container.querySelector<HTMLElement>(`[data-block-id="${blockId}"]`)
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

export function scrollJsonToBlock(container: HTMLElement | null, blockId: string): void {
  if (!container || !blockId) return
  const target = container.querySelector<HTMLElement>(`[data-json-block-id="${blockId}"]`)
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

export function updateBlockContent(
  blocks: ParsePreviewBlock[],
  blockId: string,
  content: string,
): ParsePreviewBlock[] {
  return blocks.map((block) =>
    block.id === blockId ? { ...block, content, markdown: content } : block,
  )
}

export type PreviewResultTab = 'markdown' | 'json'

/** 双击 Markdown 块：切 JSON Tab 并定位到对应 block。 */
export function blockDoubleClickNavigation(blockId: string): {
  nextTab: PreviewResultTab
  activeBlockId: string
} {
  return { nextTab: 'json', activeBlockId: blockId }
}

/** JSON 块点击：切 Markdown Tab 并定位到对应 block。 */
export function jsonBlockClickNavigation(blockId: string): {
  nextTab: PreviewResultTab
  activeBlockId: string
} {
  return { nextTab: 'markdown', activeBlockId: blockId }
}

export function buildMaterialJsonPreview(
  item: MaterialParsePreviewItem,
  preview?: ParsePreviewResponse,
  displayBlocks?: ParsePreviewBlock[],
): Record<string, unknown> {
  const fileName = item.file_name
  const parseArtifact = preview?.parse_artifact
  const parsedDocuments = Array.isArray(parseArtifact?.parsed_documents)
    ? (parseArtifact?.parsed_documents as Array<Record<string, unknown>>)
    : []
  const fileResults = Array.isArray(parseArtifact?.file_results)
    ? (parseArtifact?.file_results as Array<Record<string, unknown>>)
    : []

  return {
    file_name: fileName,
    blocks: displayBlocks ?? item.blocks ?? [],
    parse_artifact_subset: item.parse_artifact_subset ?? {},
    parsed_document: parsedDocuments.find((doc) => doc.file_name === fileName) ?? null,
    file_result: fileResults.find((result) => result.file_name === fileName) ?? null,
    document_ir_stats: item.document_ir_stats ?? {},
    parse_status: item.parse_status,
    parser_name: item.parser_name,
    warnings: item.warnings,
  }
}

export function blockDisplayMarkdown(block: ParsePreviewBlock): string {
  const raw = (block.markdown ?? block.content).trim()
  if (!raw) return raw
  if (isFormulaBlockType(block.block_type) && !isStandaloneFormulaText(raw)) {
    return formulaToDisplayMarkdown(normalizeFormulaLatex(raw) || raw)
  }
  if (isHtmlTable(raw)) return raw
  if (looksLikeGfmMarkdownTable(raw)) return raw
  if (looksLikePipeTable(raw, block.block_type)) {
    const rows = parsePipeDelimitedRows(raw)
    if (rows?.length) return pipeRowsToGfmTable(rows)
  }
  return ensureMathDelimitersInMarkdown(raw)
}

export { shouldRenderPreviewWithMarkdown }

/** Full block text for layout view — prefer untruncated content over markdown. */
export function blockLayoutDisplayText(block: ParsePreviewBlock): string {
  if (isVisualImageBlock(block)) {
    return resolveFigureDisplayText(block)
  }
  return (block.content || block.markdown || '').trim()
}

export function calibrationHighlightTerms(block: ParsePreviewBlock): string[] {
  if (!block.calibrated && !block.needs_calibration_review) return []
  const displaySource = block.original_content
    ?? block.original_markdown
    ?? (blockLayoutDisplayText(block) || blockDisplayMarkdown(block))
  const display = block.calibrated
    ? (blockLayoutDisplayText(block) || blockDisplayMarkdown(block))
    : displaySource
  if (!display) return []

  const terms = new Set<string>()
  for (const match of display.matchAll(/\[需复核[^\]]+\]/g)) {
    if (match[0]) terms.add(match[0])
  }

  for (const record of block.calibration_records ?? []) {
    if (record.status === 'dismissed') continue
    const evidence = Array.isArray(record.evidence) ? record.evidence : []
    for (let index = 0; index < evidence.length; index += 2) {
      const replacement = evidence[index + 1]
      if (replacement && display.includes(replacement)) terms.add(replacement)
      const original = evidence[index]
      if (original && display.includes(original)) terms.add(original)
    }
    for (const item of evidence) {
      if (item && display.includes(item)) terms.add(item)
    }
  }

  return Array.from(terms)
    .map((term) => term.trim())
    .filter(Boolean)
    .sort((a, b) => b.length - a.length)
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function renderCalibrationHighlightedHtml(block: ParsePreviewBlock, source?: string): string {
  const text = source ?? blockLayoutDisplayText(block)
  const terms = calibrationHighlightTerms(block)
  if (!text || !terms.length) return escapeHtml(text)

  const pattern = new RegExp(`(${terms.map(escapeRegExp).join('|')})`, 'g')
  return text
    .split(pattern)
    .map((part) => {
      if (!part) return ''
      const escaped = escapeHtml(part)
      return terms.includes(part)
        ? `<mark style="${CALIBRATION_HIGHLIGHT_STYLE}">${escaped}</mark>`
        : escaped
    })
    .join('')
}

export function applyCalibrationHighlightsToHtml(block: ParsePreviewBlock, html: string): string {
  const terms = calibrationHighlightTerms(block)
  if (!html || !terms.length) return html
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join('|')})`, 'g')
  return html.replace(pattern, `<mark style="${CALIBRATION_HIGHLIGHT_STYLE}">$1</mark>`)
}

export function blockContentEdited(original: ParsePreviewBlock, current: ParsePreviewBlock): boolean {
  return original.content !== current.content || (original.markdown ?? '') !== (current.markdown ?? '')
}

/** Markdown segments rendered in the UI — one entry per preview block. */
export function previewBlockMarkdownSegments(blocks: ParsePreviewBlock[]): string[] {
  return blocks.map((block) => blockDisplayMarkdown(block))
}

/** True when JSON export blocks match the active preview blocks array. */
export function previewBlocksMatchJsonExport(
  blocks: ParsePreviewBlock[],
  payload: Record<string, unknown>,
): boolean {
  const exported = payload.blocks
  if (!Array.isArray(exported) || exported.length !== blocks.length) return false
  return blocks.every((block, index) => {
    const other = exported[index] as ParsePreviewBlock | undefined
    if (!other) return false
    return (
      block.id === other.id
      && block.block_type === other.block_type
      && block.content === other.content
      && (block.markdown ?? block.content) === (other.markdown ?? other.content)
    )
  })
}
