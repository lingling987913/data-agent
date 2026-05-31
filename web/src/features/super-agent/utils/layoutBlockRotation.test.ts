import { describe, expect, it } from 'vitest'
import type { ParsePreviewBlock } from '@/features/super-agent/types'
import {
  layoutBlockRotationStyle,
  resolveLayoutBlockRotation,
} from '@/features/super-agent/utils/layoutBlockRotation'

describe('layoutBlockRotation', () => {
  it('uses MinerU angle when present', () => {
    const block: ParsePreviewBlock = {
      id: 't1',
      block_type: 'table',
      content: 'a | b',
      angle: 90,
    }
    expect(resolveLayoutBlockRotation(block)).toBe(90)
  })

  it('infers rotation for compact tall narrow table bbox only', () => {
    const block: ParsePreviewBlock = {
      id: 't2',
      block_type: 'table',
      content: 'a | b',
      bbox: [450, 200, 520, 550],
    }
    expect(resolveLayoutBlockRotation(block)).toBe(90)
  })

  it('does not infer rotation for full-height table regions', () => {
    const block: ParsePreviewBlock = {
      id: 't3',
      block_type: 'table',
      content: 'a | b',
      bbox: [400, 100, 600, 900],
    }
    expect(resolveLayoutBlockRotation(block)).toBe(0)
  })

  it('returns counter-rotation css for non-zero angle', () => {
    expect(layoutBlockRotationStyle(90)).toEqual({
      transform: 'rotate(-90deg)',
      transformOrigin: 'center center',
    })
    expect(layoutBlockRotationStyle(0)).toBeUndefined()
  })
})
