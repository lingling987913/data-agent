import { describe, expect, it } from 'vitest'
import { detectBboxCoordinateSpace, mineruBboxToPercentRect, mineruBboxToPixelRect, rotateBboxPercentRect, scalePixelRect } from '@/features/super-agent/utils/bboxGeometry'

describe('bboxGeometry', () => {
  it('detects 0-1000 MinerU space', () => {
    expect(detectBboxCoordinateSpace([83, 121, 917, 156])).toBe('milli')
  })

  it('detects 0-1 unit space', () => {
    expect(detectBboxCoordinateSpace([0, 0, 1, 1])).toBe('unit')
  })

  it('converts milli bbox to pixel rect', () => {
    const rect = mineruBboxToPixelRect([100, 200, 500, 400], 1000, 2000)
    expect(rect).toEqual({ left: 100, top: 400, width: 400, height: 400 })
  })

  it('converts unit bbox to pixel rect', () => {
    const rect = mineruBboxToPixelRect([0.1, 0.2, 0.5, 0.4], 1000, 1000)
    expect(rect).toEqual({ left: 100, top: 200, width: 400, height: 200 })
  })

  it('scales rect for display', () => {
    const scaled = scalePixelRect({ left: 10, top: 20, width: 100, height: 50 }, 0.5)
    expect(scaled).toEqual({ left: 5, top: 10, width: 50, height: 25 })
  })

  it('converts milli bbox to percent rect for CSS layout', () => {
    const rect = mineruBboxToPercentRect([100, 200, 500, 400])
    expect(rect).toEqual({ left: 10, top: 20, width: 40, height: 20 })
  })

  it('rotates percent rect 90° clockwise', () => {
    const rotated = rotateBboxPercentRect({ left: 10, top: 20, width: 30, height: 40 }, 90)
    expect(rotated).toEqual({ left: 20, top: 60, width: 40, height: 30 })
  })

  it('rotates percent rect 270° clockwise', () => {
    const rotated = rotateBboxPercentRect({ left: 10, top: 20, width: 30, height: 40 }, 270)
    expect(rotated).toEqual({ left: 40, top: 10, width: 40, height: 30 })
  })
})
