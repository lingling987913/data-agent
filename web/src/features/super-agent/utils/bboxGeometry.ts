/** MinerU bbox → viewport pixel rect (top-left origin). */

export interface BboxPixelRect {
  left: number
  top: number
  width: number
  height: number
}

/** Detect MinerU normalized space: 0–1 or 0–1000. */
export function detectBboxCoordinateSpace(bbox: number[]): 'unit' | 'milli' | 'absolute' {
  if (bbox.length < 4) return 'milli'
  const maxVal = Math.max(...bbox.map((v) => Math.abs(v)))
  if (maxVal <= 1.5) return 'unit'
  if (maxVal <= 1000) return 'milli'
  return 'absolute'
}

/** Convert [x0,y0,x1,y1] to pixel rect within page viewport. */
export function mineruBboxToPixelRect(
  bbox: number[],
  pageWidth: number,
  pageHeight: number,
): BboxPixelRect | null {
  if (bbox.length < 4 || pageWidth <= 0 || pageHeight <= 0) return null

  let [x0, y0, x1, y1] = bbox
  const space = detectBboxCoordinateSpace(bbox)

  if (space === 'unit') {
    x0 *= pageWidth
    x1 *= pageWidth
    y0 *= pageHeight
    y1 *= pageHeight
  } else if (space === 'milli') {
    x0 = (x0 / 1000) * pageWidth
    x1 = (x1 / 1000) * pageWidth
    y0 = (y0 / 1000) * pageHeight
    y1 = (y1 / 1000) * pageHeight
  }

  const left = Math.min(x0, x1)
  const top = Math.min(y0, y1)
  const width = Math.abs(x1 - x0)
  const height = Math.abs(y1 - y0)
  if (width <= 0 || height <= 0) return null

  return { left, top, width, height }
}

/** Scale a page-space rect to rendered display size. */
export function scalePixelRect(rect: BboxPixelRect, scale: number): BboxPixelRect {
  return {
    left: rect.left * scale,
    top: rect.top * scale,
    width: rect.width * scale,
    height: rect.height * scale,
  }
}

export interface BboxPercentRect {
  left: number
  top: number
  width: number
  height: number
}

/** Percent rect (0–100) for CSS absolute positioning in a page-sized container. */
export function mineruBboxToPercentRect(bbox: number[]): BboxPercentRect | null {
  return mineruBboxToPixelRect(bbox, 100, 100)
}

/** Rotate a percent-space rect clockwise within a square page (0–100). */
export function rotateBboxPercentRect(
  rect: BboxPercentRect,
  degrees: 0 | 90 | 180 | 270,
  bounds = 100,
): BboxPercentRect {
  const { left, top, width, height } = rect
  switch (degrees) {
    case 90:
      return {
        left: top,
        top: bounds - left - width,
        width: height,
        height: width,
      }
    case 180:
      return {
        left: bounds - left - width,
        top: bounds - top - height,
        width,
        height,
      }
    case 270:
      return {
        left: bounds - top - height,
        top: left,
        width: height,
        height: width,
      }
    default:
      return { left, top, width, height }
  }
}
