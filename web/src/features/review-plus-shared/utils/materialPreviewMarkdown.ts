/**
 * 材料预览 Markdown 归一化
 * DOCX 等解析链路可能产出 `a | b | c` 伪表格文本，需补 GFM 分隔行后才能被 MarkdownRenderer 渲染为表格。
 */

function splitPipeTableRow(line: string): string[] {
  let stripped = line.trim()
  if (stripped.startsWith('|') && stripped.endsWith('|')) {
    stripped = stripped.slice(1, -1)
  }
  return stripped.split('|').map((cell) => cell.trim())
}

function looksLikeGfmMarkdownTable(text: string): boolean {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean)
  if (lines.length < 2) return false
  return lines.slice(1).some((line) => /^\|?\s*:?-{3,}/.test(line))
}

function escapeMarkdownTableCell(value: string): string {
  return value.replace(/\n/g, '<br>').replace(/\|/g, '\\|')
}

function buildMarkdownTable(headers: string[], rows: string[][]): string {
  const safeHeaders = headers.map((header) => escapeMarkdownTableCell(header || ' '))
  const headerLine = `| ${safeHeaders.join(' | ')} |`
  const separatorLine = `| ${safeHeaders.map(() => '---').join(' | ')} |`
  const bodyLines = rows.map((row) => {
    const safeRow = row.map((cell) => escapeMarkdownTableCell(cell))
    return `| ${safeRow.join(' | ')} |`
  })
  return [headerLine, separatorLine, ...bodyLines].join('\n')
}

function convertPipeBlockToMarkdownTable(block: string): string | null {
  const lines = block.split('\n').map((line) => line.trim()).filter(Boolean)
  if (lines.length < 2) return null

  const rows: string[][] = []
  for (const line of lines) {
    if (!line.includes('|')) {
      if (rows.length) break
      continue
    }
    rows.push(splitPipeTableRow(line))
  }

  if (rows.length < 2) return null
  const width = Math.max(...rows.map((row) => row.length))
  if (width < 2) return null

  const padded = rows.map((row) => [...row, ...Array(width - row.length).fill('')])
  return buildMarkdownTable(padded[0], padded.slice(1))
}

function normalizeTableBlock(block: string): string {
  const trimmed = block.trim()
  if (!trimmed) return block
  if (looksLikeGfmMarkdownTable(trimmed)) return trimmed
  return convertPipeBlockToMarkdownTable(trimmed) ?? trimmed
}

/** 将材料 content 中的伪表格块转为可渲染的 GFM Markdown */
export function normalizeMaterialPreviewMarkdown(content: string): string {
  if (!content.trim()) return content

  const blocks = content.split(/\n{2,}/)
  return blocks
    .map((block) => {
      const trimmed = block.trim()
      if (!trimmed.includes('|')) return block
      if (looksLikeGfmMarkdownTable(trimmed)) return block
      if (trimmed.split('\n').every((line) => line.trim().includes('|'))) {
        return normalizeTableBlock(trimmed)
      }
      return block
    })
    .join('\n\n')
}
