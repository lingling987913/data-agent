export type LightMarkdownBlock =
  | { type: 'heading'; level: 1 | 2 | 3; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'unordered_list'; items: string[] }
  | { type: 'ordered_list'; items: string[] }
  | { type: 'blockquote'; text: string }

function isOrderedListLine(line: string): boolean {
  return /^\d+[.)、]\s+/.test(line.trim())
}

function isUnorderedListLine(line: string): boolean {
  return /^[-*]\s+/.test(line.trim())
}

function stripListPrefix(line: string): string {
  return line.trim().replace(/^[-*]\s+/, '').replace(/^\d+[.)、]\s+/, '')
}

function parseHeading(line: string): LightMarkdownBlock | null {
  const trimmed = line.trim()
  if (trimmed.startsWith('### ')) return { type: 'heading', level: 3, text: trimmed.slice(4).trim() }
  if (trimmed.startsWith('## ')) return { type: 'heading', level: 2, text: trimmed.slice(3).trim() }
  if (trimmed.startsWith('# ')) return { type: 'heading', level: 1, text: trimmed.slice(2).trim() }
  if (trimmed.startsWith('> ')) return { type: 'blockquote', text: trimmed.slice(2).trim() }
  return null
}

function parseListBlock(lines: string[]): LightMarkdownBlock | null {
  if (!lines.length) return null
  const ordered = lines.every(isOrderedListLine)
  const unordered = lines.every(isUnorderedListLine)
  if (!ordered && !unordered) return null
  const items = lines.map(stripListPrefix).filter(Boolean)
  if (!items.length) return null
  return ordered
    ? { type: 'ordered_list', items }
    : { type: 'unordered_list', items }
}

/** 轻量 Markdown 分块（段落 / 标题 / 列表 / 引用），不依赖额外运行时。 */
export function parseLightMarkdownBlocks(markdown: string): LightMarkdownBlock[] {
  const normalized = String(markdown || '').replace(/\r\n/g, '\n').trim()
  if (!normalized) return []

  const blocks: LightMarkdownBlock[] = []
  const chunks = normalized.split(/\n{2,}/)

  for (const chunk of chunks) {
    const lines = chunk.split('\n').map((line) => line.trim()).filter(Boolean)
    if (!lines.length) continue

    if (lines.length === 1) {
      const heading = parseHeading(lines[0])
      if (heading) {
        blocks.push(heading)
        continue
      }
    }

    const listBlock = parseListBlock(lines)
    if (listBlock) {
      blocks.push(listBlock)
      continue
    }

    const firstHeading = parseHeading(lines[0])
    if (firstHeading && lines.length === 1) {
      blocks.push(firstHeading)
      continue
    }

    blocks.push({ type: 'paragraph', text: lines.join('\n') })
  }

  return blocks
}
