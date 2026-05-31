import type { ParsePreviewResponse, SuperAgentMaterialInput } from '@/features/super-agent/types'

export function getComprehensiveReviewMineruConfig() {
  const parserType = (process.env.NEXT_PUBLIC_COMPREHENSIVE_REVIEW_MINERU_PARSER || '').trim()
  const parseMode = (process.env.NEXT_PUBLIC_COMPREHENSIVE_REVIEW_MINERU_PARSE_MODE || '').trim()
  return {
    parserType,
    parseMode,
    displayLabel: [parserType || 'MinerU', parseMode].filter(Boolean).join(' / '),
  }
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function markdownFileName(fileName: string): string {
  const trimmed = fileName.trim() || 'material'
  const withoutExt = trimmed.replace(/\.[^.]+$/, '')
  return `${withoutExt || 'material'}.md`
}

function parsedMarkdownByName(preview: ParsePreviewResponse): Map<string, string> {
  const parsed = new Map<string, string>()
  const parseArtifact = preview.parse_artifact
  const documents = Array.isArray(parseArtifact?.parsed_documents)
    ? parseArtifact.parsed_documents
    : []

  for (const item of documents) {
    if (!item || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const fileName = textValue(record.file_name)
    if (!fileName) continue
    const content = textValue(record.content)
    if (content) {
      parsed.set(fileName, content)
      continue
    }
    const document = record.document && typeof record.document === 'object'
      ? record.document as Record<string, unknown>
      : {}
    const blocks = Array.isArray(document.blocks) ? document.blocks : []
    const blockMarkdown = blocks
      .map((block) => {
        if (!block || typeof block !== 'object') return ''
        const blockRecord = block as Record<string, unknown>
        return textValue(blockRecord.table_markdown) || textValue(blockRecord.text)
      })
      .filter(Boolean)
      .join('\n\n')
    if (blockMarkdown) {
      parsed.set(fileName, blockMarkdown)
    }
  }
  return parsed
}

function roleBySourceName(preview: ParsePreviewResponse): Map<string, string> {
  const roles = new Map<string, string>()
  for (const item of preview.classification?.material_roles || []) {
    const fileName = textValue(item.file_name)
    const role = textValue(item.role)
    if (fileName && role) roles.set(fileName, role)
  }
  for (const material of preview.materials) {
    const fileName = material.file_name || ''
    const role = material.role || ''
    if (fileName && role && role !== 'unknown') roles.set(fileName, role)
  }
  return roles
}

export function buildMarkdownMaterialsFromPreview(preview: ParsePreviewResponse): SuperAgentMaterialInput[] {
  const markdownByName = parsedMarkdownByName(preview)
  const rolesByName = roleBySourceName(preview)

  return preview.materials.map((material) => {
    const sourceName = material.file_name || 'material'
    const markdown = markdownByName.get(sourceName)
      || material.content_markdown
      || material.content_preview
      || ''
    const role = rolesByName.get(sourceName) || material.role || 'unknown'

    return {
      name: markdownFileName(sourceName),
      file_type: 'md',
      content: markdown,
      content_preview: markdown.slice(0, 1200),
      content_base64: '',
      file_path: '',
      upload_id: material.upload_id,
      file_id: material.file_id,
      parser_type: 'local',
      role,
    }
  })
}
