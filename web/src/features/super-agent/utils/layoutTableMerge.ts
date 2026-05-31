import type { ParsePreviewBlock } from '@/features/super-agent/types'
import {
  detectBboxCoordinateSpace,
  mineruBboxToPercentRect,
  type BboxPercentRect,
} from '@/features/super-agent/utils/bboxGeometry'
import {
  isHtmlTable,
  isTableBlockType,
  looksLikePipeTable,
  parsePipeDelimitedRows,
  pipeRowsToHtmlTable,
} from '@/features/super-agent/utils/layoutBlockContent'
import { blockLayoutDisplayText } from '@/features/super-agent/utils/parsePreviewBlocks'

const TABLE_FRAGMENT_MAX_HEIGHT_PERCENT = 10
const TABLE_MERGE_VERTICAL_GAP_PERCENT = 4
const TABLE_MERGE_MIN_HORIZONTAL_OVERLAP = 0.35

function percentRectToBbox(rect: BboxPercentRect, space: ReturnType<typeof detectBboxCoordinateSpace>): number[] {
  if (space === 'unit') {
    return [
      rect.left / 100,
      rect.top / 100,
      (rect.left + rect.width) / 100,
      (rect.top + rect.height) / 100,
    ]
  }
  const scale = space === 'milli' ? 10 : 1
  return [
    rect.left * scale,
    rect.top * scale,
    (rect.left + rect.width) * scale,
    (rect.top + rect.height) * scale,
  ]
}

function unionPercentRect(rects: BboxPercentRect[]): BboxPercentRect {
  const left = Math.min(...rects.map((r) => r.left))
  const top = Math.min(...rects.map((r) => r.top))
  const right = Math.max(...rects.map((r) => r.left + r.width))
  const bottom = Math.max(...rects.map((r) => r.top + r.height))
  return { left, top, width: right - left, height: bottom - top }
}

function horizontalOverlapRatio(a: BboxPercentRect, b: BboxPercentRect): number {
  const overlap = Math.min(a.left + a.width, b.left + b.width) - Math.max(a.left, b.left)
  if (overlap <= 0) return 0
  const narrower = Math.min(a.width, b.width)
  return narrower > 0 ? overlap / narrower : 0
}

function verticalGapBetween(a: BboxPercentRect, b: BboxPercentRect): number {
  if (a.top + a.height <= b.top) return b.top - (a.top + a.height)
  if (b.top + b.height <= a.top) return a.top - (b.top + b.height)
  return 0
}

function isTableLayoutFragment(block: ParsePreviewBlock): boolean {
  if (!Array.isArray(block.bbox) || block.bbox.length < 4) return false
  const rect = mineruBboxToPercentRect(block.bbox)
  if (!rect) return false

  const text = blockLayoutDisplayText(block)
  if (!text) return false

  if (isHtmlTable(text)) {
    return rect.height <= TABLE_FRAGMENT_MAX_HEIGHT_PERCENT
  }

  if (isTableBlockType(block.block_type) || looksLikePipeTable(text, block.block_type)) {
    const rows = parsePipeDelimitedRows(text)
    if (!rows?.length) return false
    const multiRow = rows.length > 1
    if (multiRow && rect.height > TABLE_FRAGMENT_MAX_HEIGHT_PERCENT * 2) return false
    return rect.height <= TABLE_FRAGMENT_MAX_HEIGHT_PERCENT || rows.length === 1
  }

  return false
}

function mergeTableFragmentContent(blocks: ParsePreviewBlock[]): string {
  const htmlBlocks = blocks
    .map((block) => blockLayoutDisplayText(block))
    .filter((text) => isHtmlTable(text))

  if (htmlBlocks.length) {
    return htmlBlocks.reduce((best, next) => (next.length > best.length ? next : best), htmlBlocks[0])
  }

  const rows: string[][] = []
  for (const block of blocks) {
    const parsed = parsePipeDelimitedRows(blockLayoutDisplayText(block))
    if (parsed?.length) rows.push(...parsed)
  }
  if (rows.length) return pipeRowsToHtmlTable(rows)

  return blocks
    .map((block) => blockLayoutDisplayText(block))
    .filter(Boolean)
    .join('\n')
}

function buildMergedTableBlock(group: ParsePreviewBlock[]): ParsePreviewBlock {
  const primary = group[0]
  const rects = group
    .map((block) => (block.bbox ? mineruBboxToPercentRect(block.bbox) : null))
    .filter((rect): rect is BboxPercentRect => rect !== null)
  const union = unionPercentRect(rects)
  const space = detectBboxCoordinateSpace(primary.bbox!)
  const content = mergeTableFragmentContent(group)

  return {
    ...primary,
    block_type: 'table',
    content,
    markdown: content,
    bbox: percentRectToBbox(union, space),
  }
}

/**
 * Merge vertically stacked table row/cell fragments (MinerU) into one layout block.
 * Document-agnostic: uses bbox proximity + pipe/html table shape only.
 */
export function mergeLayoutTableFragments(blocks: ParsePreviewBlock[]): ParsePreviewBlock[] {
  const fragments = blocks.filter(isTableLayoutFragment)
  if (fragments.length < 2) return blocks

  const fragmentIds = new Set(fragments.map((block) => block.id))
  const rest = blocks.filter((block) => !fragmentIds.has(block.id))

  const sorted = [...fragments].sort((a, b) => {
    const ra = mineruBboxToPercentRect(a.bbox!)!
    const rb = mineruBboxToPercentRect(b.bbox!)!
    return ra.top - rb.top || ra.left - rb.left
  })

  const merged: ParsePreviewBlock[] = []
  const consumed = new Set<string>()

  for (const seed of sorted) {
    if (consumed.has(seed.id)) continue

    const group: ParsePreviewBlock[] = [seed]
    consumed.add(seed.id)
    let union = mineruBboxToPercentRect(seed.bbox!)!

    let extended = true
    while (extended) {
      extended = false
      for (const candidate of sorted) {
        if (consumed.has(candidate.id)) continue
        const rect = mineruBboxToPercentRect(candidate.bbox!)!
        if (horizontalOverlapRatio(union, rect) < TABLE_MERGE_MIN_HORIZONTAL_OVERLAP) continue
        if (verticalGapBetween(union, rect) > TABLE_MERGE_VERTICAL_GAP_PERCENT) continue
        group.push(candidate)
        consumed.add(candidate.id)
        union = unionPercentRect([union, rect])
        extended = true
      }
    }

    merged.push(group.length >= 2 ? buildMergedTableBlock(group) : seed)
  }

  return [...rest, ...merged]
}
