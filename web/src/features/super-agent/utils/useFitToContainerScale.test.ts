import { describe, expect, it } from 'vitest'
import { computeFitScale } from '@/features/super-agent/utils/useFitToContainerScale'

describe('computeFitScale', () => {
  it('returns 1 when content fits within container', () => {
    expect(computeFitScale(800, 600, 400, 300)).toBe(1)
  })

  it('scales down when content is taller than container', () => {
    expect(computeFitScale(400, 300, 400, 600)).toBe(0.5)
  })

  it('scales down when content is wider than container', () => {
    expect(computeFitScale(300, 400, 600, 400)).toBe(0.5)
  })

  it('uses the smaller scale when both dimensions overflow', () => {
    expect(computeFitScale(200, 200, 400, 400)).toBe(0.5)
  })

  it('returns 1 for invalid dimensions', () => {
    expect(computeFitScale(0, 200, 400, 400)).toBe(1)
  })
})
