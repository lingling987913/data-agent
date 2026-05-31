import { describe, expect, it } from 'vitest'
import type { ParsePreviewBlock } from '@/features/super-agent/types'
import { mergeLayoutTableFragments } from '@/features/super-agent/utils/layoutTableMerge'

describe('mergeLayoutTableFragments', () => {
  it('merges vertically stacked pipe table row fragments', () => {
    const blocks: ParsePreviewBlock[] = [
      {
        id: 'r1',
        block_type: 'table',
        content: 'A | B',
        bbox: [100, 700, 900, 730],
      },
      {
        id: 'r2',
        block_type: 'table',
        content: 'C | D',
        bbox: [100, 735, 900, 765],
      },
      {
        id: 'p1',
        block_type: 'paragraph',
        content: 'intro',
        bbox: [100, 100, 900, 150],
      },
    ]
    const merged = mergeLayoutTableFragments(blocks)
    expect(merged).toHaveLength(2)
    const table = merged.find((block) => block.block_type === 'table')
    expect(table?.content).toContain('<table>')
    expect(table?.content).toContain('A')
    expect(table?.content).toContain('C')
    expect(table?.bbox).toEqual([100, 700, 900, 765])
  })

  it('leaves non-fragment tables unchanged', () => {
    const blocks: ParsePreviewBlock[] = [
      {
        id: 't1',
        block_type: 'table',
        content: '| H1 | H2 |\n| --- | --- |\n| a | b |',
        bbox: [100, 400, 900, 650],
      },
    ]
    expect(mergeLayoutTableFragments(blocks)).toEqual(blocks)
  })
})
