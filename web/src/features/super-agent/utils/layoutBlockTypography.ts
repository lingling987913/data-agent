import type { CSSProperties } from 'react'
import type { BboxPercentRect } from '@/features/super-agent/utils/bboxGeometry'

export const LAYOUT_TYPO_MIN_FONT_PX = 6
export const LAYOUT_TYPO_MAX_FONT_PX = 9
export const LAYOUT_TYPO_BASE_FONT_PX = 8
export const LAYOUT_TYPO_TABLE_MIN_FONT_PX = 7
/** Readable fixed size for text/heading blocks — full content over bbox fit. */
export const LAYOUT_READABLE_FONT_PX = 10
/** Slightly larger size for KaTeX formulas in layout blocks. */
export const LAYOUT_FORMULA_FONT_PX = 11
/** Floor height when OCR bbox height is a thin strip (percent of page). */
export const LAYOUT_BLOCK_MIN_HEIGHT_PX = 18

export interface LayoutBlockTypography {
  fontSizePx: number
  wrapperStyle: CSSProperties
}

function clamp(min: number, value: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/** Effective bbox after block-level rotation (swap w/h for 90/270). */
export function layoutBlockEffectiveRect(
  rect: BboxPercentRect,
  rotation = 0,
): BboxPercentRect {
  if (rotation % 180 === 0) return rect
  return { left: rect.left, top: rect.top, width: rect.height, height: rect.width }
}

/** Estimate visible character count for typography heuristics. */
export function layoutBlockTextLength(text: string, isTable = false): number {
  const trimmed = text.trim()
  if (!trimmed) return 0
  if (isTable) {
    return trimmed.replace(/\s+/g, '').length
  }
  return trimmed.replace(/\s+/g, ' ').length
}

/**
 * Typography for layout blocks. Text blocks use a fixed readable size and no
 * transform scale so content can grow with height:auto containers.
 */
export function resolveLayoutBlockTypography(
  rect: BboxPercentRect,
  textLength: number,
  options?: { rotation?: number; isTable?: boolean; isFormula?: boolean },
): LayoutBlockTypography {
  const effective = layoutBlockEffectiveRect(rect, options?.rotation ?? 0)
  const isTable = options?.isTable ?? false
  const isFormula = options?.isFormula ?? false
  const area = Math.max(effective.width * effective.height, 1)
  const minDim = Math.min(effective.width, effective.height)
  const geomMean = Math.sqrt(area)

  let fontSizePx: number

  if (isTable) {
    fontSizePx = LAYOUT_TYPO_BASE_FONT_PX
    if (minDim < 12 || area < 900) {
      const dimFactor = clamp(0.45, minDim / 12, 1)
      const areaFactor = clamp(0.45, Math.sqrt(area / 900), 1)
      fontSizePx = LAYOUT_TYPO_BASE_FONT_PX * Math.min(dimFactor, areaFactor)
    }
    const density = textLength / Math.max(geomMean, 2)
    if (density > 3) {
      fontSizePx = Math.min(fontSizePx, LAYOUT_TYPO_BASE_FONT_PX * (3 / density))
    }
    fontSizePx = clamp(LAYOUT_TYPO_TABLE_MIN_FONT_PX, fontSizePx, LAYOUT_TYPO_MAX_FONT_PX)
  } else if (isFormula) {
    fontSizePx = LAYOUT_FORMULA_FONT_PX
  } else {
    fontSizePx = LAYOUT_READABLE_FONT_PX
  }

  const wrapperStyle: CSSProperties = {
    fontSize: `${fontSizePx}px`,
    lineHeight: 1.35,
    width: '100%',
  }

  return { fontSizePx, wrapperStyle }
}

/** Prose classes that inherit parent font-size instead of fixed px. */
export const LAYOUT_BLOCK_PROSE_INHERIT =
  'prose-sm max-w-none [&_*]:text-inherit [&_*]:leading-[inherit] [&_h1]:my-0.5 [&_h1]:text-[1.1em] [&_h1]:font-semibold [&_h2]:my-0.5 [&_h2]:text-[1em] [&_h2]:font-semibold [&_h3]:my-0.5 [&_h3]:text-[0.95em] [&_h3]:font-medium [&_p]:my-0.5 [&_p]:text-primary/90 [&_li]:text-primary/90 [&_ul]:my-0.5 [&_ol]:my-0.5 [&_table]:my-0.5 [&_table]:w-full [&_table]:border-collapse [&_table]:border [&_table]:border-border/25 [&_th]:border [&_th]:border-border/25 [&_th]:bg-surface/80 [&_th]:px-0.5 [&_th]:py-0 [&_th]:text-left [&_th]:font-medium [&_td]:border [&_td]:border-border/20 [&_td]:px-0.5 [&_td]:py-0 [&_td]:break-words [&_code]:rounded [&_code]:bg-primaryAccent/5 [&_code]:px-0.5 [&_code]:text-[0.85em]'

export const LAYOUT_HTML_TABLE_INHERIT =
  '[&_table]:w-full [&_table]:border-collapse [&_table]:border [&_table]:border-border/25 [&_th]:border [&_th]:border-border/25 [&_th]:bg-surface/80 [&_th]:px-0.5 [&_th]:py-0 [&_th]:text-left [&_th]:font-medium [&_td]:border [&_td]:border-border/20 [&_td]:px-0.5 [&_td]:py-0 [&_td]:break-words [&_.katex]:text-[length:inherit] [&_.katex]:inline-block [&_.katex-display]:my-0'
