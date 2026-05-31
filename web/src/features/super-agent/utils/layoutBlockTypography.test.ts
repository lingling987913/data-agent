import { describe, expect, it } from 'vitest'
import {
  LAYOUT_READABLE_FONT_PX,
  LAYOUT_TYPO_MIN_FONT_PX,
  layoutBlockEffectiveRect,
  layoutBlockTextLength,
  resolveLayoutBlockTypography,
} from '@/features/super-agent/utils/layoutBlockTypography'

describe('layoutBlockTypography', () => {
  it('shrinks font for small table bbox areas', () => {
    const large = resolveLayoutBlockTypography(
      { left: 10, top: 10, width: 40, height: 20 },
      20,
      { isTable: true },
    )
    const small = resolveLayoutBlockTypography(
      { left: 80, top: 5, width: 8, height: 4 },
      20,
      { isTable: true },
    )
    expect(small.fontSizePx).toBeLessThan(large.fontSizePx)
    expect(small.fontSizePx).toBeGreaterThanOrEqual(LAYOUT_TYPO_MIN_FONT_PX)
  })

  it('uses readable fixed font for text blocks without scale transform', () => {
    const result = resolveLayoutBlockTypography(
      { left: 0, top: 0, width: 10, height: 6 },
      120,
      { isTable: false },
    )
    expect(result.fontSizePx).toBe(LAYOUT_READABLE_FONT_PX)
    expect(result.wrapperStyle.transform).toBeUndefined()
  })

  it('swaps dimensions for 90° block rotation', () => {
    const rect = { left: 5, top: 10, width: 20, height: 40 }
    expect(layoutBlockEffectiveRect(rect, 90)).toEqual({
      left: 5,
      top: 10,
      width: 40,
      height: 20,
    })
  })

  it('counts table text without whitespace noise', () => {
    expect(layoutBlockTextLength('a | b\nc | d', true)).toBe(6)
  })
})
