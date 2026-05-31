import { describe, expect, it } from 'vitest'
import { parseLightMarkdownBlocks } from '@/features/unified-review-workbench/utils/lightMarkdown'

describe('lightMarkdown', () => {
  it('parses headings and paragraphs', () => {
    const blocks = parseLightMarkdownBlocks('# Title\n\nBody line one.')
    expect(blocks[0]).toEqual({ type: 'heading', level: 1, text: 'Title' })
    expect(blocks[1]).toEqual({ type: 'paragraph', text: 'Body line one.' })
  })

  it('parses unordered and ordered lists', () => {
    expect(parseLightMarkdownBlocks('- a\n- b')[0]).toEqual({
      type: 'unordered_list',
      items: ['a', 'b'],
    })
    expect(parseLightMarkdownBlocks('1. first\n2. second')[0]).toEqual({
      type: 'ordered_list',
      items: ['first', 'second'],
    })
  })

  it('parses blockquotes', () => {
    expect(parseLightMarkdownBlocks('> quoted note')[0]).toEqual({
      type: 'blockquote',
      text: 'quoted note',
    })
  })
})
