import type { ParsePreviewBlock } from '@/features/super-agent/types'
import {
  mineruBboxToPercentRect,
  rotateBboxPercentRect,
  type BboxPercentRect,
} from '@/features/super-agent/utils/bboxGeometry'
import { isTableBlockType } from '@/features/super-agent/utils/layoutBlockContent'
import { resolveLayoutBlockRotation } from '@/features/super-agent/utils/layoutBlockRotation'

export type LayoutPageRotation = 0 | 90 | 180 | 270

export interface LayoutPageLayout {
  rotation: LayoutPageRotation
  aspectRatio: string
}

const PORTRAIT_ASPECT = '210 / 297'
const LANDSCAPE_ASPECT = '297 / 210'
/** Whole-page rotation only when most positioned blocks share the same angle (not table-only). */
const PAGE_ANGLE_VOTE_THRESHOLD = 0.75
const TABLE_DOMINANCE_THRESHOLD = 0.35

const VALID_ANGLES = new Set<LayoutPageRotation>([0, 90, 180, 270])

function normalizePageRotation(value: number | null | undefined): LayoutPageRotation | null {
  if (value == null || !Number.isFinite(value)) return null
  const angle = ((Math.round(value) % 360) + 360) % 360 as LayoutPageRotation
  return VALID_ANGLES.has(angle) && angle !== 0 ? angle : angle === 0 ? 0 : null
}

function normalizeAngle(value: number): LayoutPageRotation {
  const angle = ((value % 360) + 360) % 360 as LayoutPageRotation
  return VALID_ANGLES.has(angle) ? angle : 0
}

function simplifyAspectRatio(width: number, height: number): string {
  if (width <= 0 || height <= 0) return PORTRAIT_ASPECT
  const w = Math.round(width * 1000)
  const h = Math.round(height * 1000)
  const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b))
  const divisor = gcd(w, h)
  return `${w / divisor} / ${h / divisor}`
}

export function layoutAspectRatioForPage(
  rotation: LayoutPageRotation,
  pageSize?: { width: number; height: number } | null,
): string {
  if (pageSize && pageSize.width > 0 && pageSize.height > 0) {
    const swap = rotation % 180 === 90
    const width = swap ? pageSize.height : pageSize.width
    const height = swap ? pageSize.width : pageSize.height
    return simplifyAspectRatio(width, height)
  }
  return rotation % 180 === 90 ? LANDSCAPE_ASPECT : PORTRAIT_ASPECT
}

function layoutForRotation(
  rotation: LayoutPageRotation,
  pageSize?: { width: number; height: number } | null,
): LayoutPageLayout {
  return {
    rotation,
    aspectRatio: layoutAspectRatioForPage(rotation, pageSize),
  }
}

function positionedBlocks(blocks: ParsePreviewBlock[]): ParsePreviewBlock[] {
  return blocks.filter((block) => Array.isArray(block.bbox) && block.bbox.length >= 4)
}

/** Vote on explicit MinerU block angles — majority 90/270/180 wins. */
export function voteLayoutPageRotationFromAngles(
  blocks: ParsePreviewBlock[],
): LayoutPageRotation | null {
  const counts: Record<LayoutPageRotation, number> = { 0: 0, 90: 0, 180: 0, 270: 0 }
  let total = 0

  for (const block of blocks) {
    if (typeof block.angle !== 'number' || !Number.isFinite(block.angle)) continue
    const angle = normalizeAngle(block.angle)
    counts[angle]++
    total++
  }

  if (!total) return null

  for (const candidate of [90, 270, 180] as const) {
    if (counts[candidate] / total >= PAGE_ANGLE_VOTE_THRESHOLD) return candidate
  }

  return null
}

/** Heuristic: table-heavy page whose union/tables are tall-narrow → landscape-on-portrait. */
export function detectLayoutPageRotationFromBboxes(
  blocks: ParsePreviewBlock[],
): LayoutPageRotation | null {
  const positioned = positionedBlocks(blocks)
  if (!positioned.length) return null

  const tableRects: BboxPercentRect[] = []
  let minLeft = 100
  let minTop = 100
  let maxRight = 0
  let maxBottom = 0

  for (const block of positioned) {
    const rect = mineruBboxToPercentRect(block.bbox!)
    if (!rect) continue

    minLeft = Math.min(minLeft, rect.left)
    minTop = Math.min(minTop, rect.top)
    maxRight = Math.max(maxRight, rect.left + rect.width)
    maxBottom = Math.max(maxBottom, rect.top + rect.height)

    if (isTableBlockType(block.block_type)) {
      tableRects.push(rect)
    }
  }

  if (!tableRects.length) return null
  if (tableRects.length / positioned.length < TABLE_DOMINANCE_THRESHOLD) return null

  const unionWidth = maxRight - minLeft
  const unionHeight = maxBottom - minTop
  const tallTables = tableRects.filter((rect) => rect.height > rect.width * 1.2).length
  const tallTableRatio = tallTables / tableRects.length

  if (unionHeight > unionWidth * 1.15 && tallTableRatio >= 0.4) return 90
  if (tableRects.length / positioned.length >= 0.55 && tallTableRatio >= 0.5) return 90

  return null
}

/** Resolve whole-page rotation for layout canvas (document-agnostic). */
export function resolveLayoutPageRotation(
  blocks: ParsePreviewBlock[],
  options?: {
    pageRotation?: number | null
    pageSize?: { width: number; height: number } | null
  },
): LayoutPageLayout {
  const pageSize = options?.pageSize

  const explicit = normalizePageRotation(options?.pageRotation)
  if (explicit !== null && explicit !== 0) {
    return layoutForRotation(explicit, pageSize)
  }

  const positioned = positionedBlocks(blocks)
  const angleVote = voteLayoutPageRotationFromAngles(positioned)
  if (angleVote !== null && angleVote !== 0) {
    return layoutForRotation(angleVote, pageSize)
  }

  // Bbox table heuristic is exported for tests only — do not rotate the layout canvas
  // independently of PdfBlockOverlayViewer, or blocks drift from the PDF overlay.

  return layoutForRotation(0, pageSize)
}

/** Block content rotation relative to page-level correction. */
export function layoutBlockRotationOnPage(
  block: ParsePreviewBlock,
  pageRotation: LayoutPageRotation,
): number {
  const blockRotation = resolveLayoutBlockRotation(block)
  return normalizeAngle(blockRotation - pageRotation)
}

/** Map block bbox into page-rotated layout coordinate space. */
export function layoutBlockRectOnPage(
  block: ParsePreviewBlock,
  pageRotation: LayoutPageRotation,
): BboxPercentRect | null {
  if (!Array.isArray(block.bbox) || block.bbox.length < 4) return null
  const rect = mineruBboxToPercentRect(block.bbox)
  if (!rect) return null
  if (!pageRotation) return rect
  return rotateBboxPercentRect(rect, pageRotation)
}
