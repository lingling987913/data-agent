import { describe, expect, it } from 'vitest'
import type { ParsePreviewBlock } from '@/features/super-agent/types'
import {
  detectLayoutPageRotationFromBboxes,
  layoutBlockRectOnPage,
  layoutBlockRotationOnPage,
  resolveLayoutPageRotation,
  voteLayoutPageRotationFromAngles,
} from '@/features/super-agent/utils/layoutPageRotation'

describe('layoutPageRotation', () => {
  it('does not rotate page when only a subset of blocks share an angle', () => {
    const blocks: ParsePreviewBlock[] = [
      { id: 'a', block_type: 'table', content: 'x', angle: 90, bbox: [1, 2, 3, 4] },
      { id: 'b', block_type: 'table', content: 'y', angle: 90, bbox: [5, 6, 7, 8] },
      { id: 'c', block_type: 'text', content: 'z', angle: 0, bbox: [9, 10, 11, 12] },
    ]
    expect(voteLayoutPageRotationFromAngles(blocks)).toBeNull()
    expect(resolveLayoutPageRotation(blocks).rotation).toBe(0)
  })

  it('votes page rotation when most blocks share the same angle', () => {
    const blocks: ParsePreviewBlock[] = [
      { id: 'a', block_type: 'text', content: 'x', angle: 90, bbox: [1, 2, 3, 4] },
      { id: 'b', block_type: 'text', content: 'y', angle: 90, bbox: [5, 6, 7, 8] },
      { id: 'c', block_type: 'text', content: 'z', angle: 90, bbox: [9, 10, 11, 12] },
      { id: 'd', block_type: 'text', content: 'w', angle: 0, bbox: [12, 13, 14, 15] },
    ]
    expect(voteLayoutPageRotationFromAngles(blocks)).toBe(90)
    expect(resolveLayoutPageRotation(blocks).rotation).toBe(90)
  })

  it('uses pdf page size for aspect ratio when provided', () => {
    const blocks: ParsePreviewBlock[] = [
      { id: 'a', block_type: 'text', content: 'x', bbox: [1, 2, 3, 4] },
    ]
    const layout = resolveLayoutPageRotation(blocks, {
      pageSize: { width: 612, height: 792 },
    })
    expect(layout.rotation).toBe(0)
    expect(layout.aspectRatio).toBe('17 / 22')
  })

  it('uses explicit pageRotation when provided', () => {
    const blocks: ParsePreviewBlock[] = [
      { id: 'a', block_type: 'text', content: 'x', bbox: [1, 2, 3, 4] },
    ]
    expect(resolveLayoutPageRotation(blocks, { pageRotation: 270 }).rotation).toBe(270)
  })

  it('detects landscape tables on portrait page via bbox heuristic (not applied to canvas)', () => {
    const blocks: ParsePreviewBlock[] = [
      { id: 't1', block_type: 'table', content: 'a | b', bbox: [400, 100, 600, 900] },
      { id: 't2', block_type: 'table', content: 'c | d', bbox: [620, 100, 820, 900] },
      { id: 'p', block_type: 'paragraph', content: 'note', bbox: [100, 100, 350, 140] },
    ]
    expect(detectLayoutPageRotationFromBboxes(blocks)).toBe(90)
    expect(resolveLayoutPageRotation(blocks).rotation).toBe(0)
  })

  it('maps block rotation relative to page rotation', () => {
    const block: ParsePreviewBlock = {
      id: 't1',
      block_type: 'table',
      content: 'a | b',
      angle: 90,
    }
    expect(layoutBlockRotationOnPage(block, 90)).toBe(0)
  })

  it('rotates block bbox when page is rotated', () => {
    const block: ParsePreviewBlock = {
      id: 't1',
      block_type: 'table',
      content: 'a | b',
      bbox: [100, 200, 500, 400],
    }
    expect(layoutBlockRectOnPage(block, 90)).toEqual({
      left: 20,
      top: 50,
      width: 20,
      height: 40,
    })
  })
})
