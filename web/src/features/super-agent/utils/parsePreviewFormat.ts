import type { MaterialParsePreviewItem, ParsePreviewResponse } from '@/features/super-agent/types'

export const PARSING_TIER_LABELS: Record<string, string> = {
  lite: '轻量解析',
  standard: '标准解析',
  full: '深度解析',
}

/** Info-only warnings that must not trigger degraded/capability UI. */
const INFO_ONLY_PARSE_WARNING_PATTERNS: RegExp[] = [
  /^MinerU local backend=/i,
  /^已合并 \d+ 组跨页表格。$/,
]

export function isInfoOnlyParseWarning(warning: string): boolean {
  const normalized = warning.trim()
  if (!normalized) return true
  if (normalized === 'postprocess skipped for parse preview') return true
  return INFO_ONLY_PARSE_WARNING_PATTERNS.some((pattern) => pattern.test(normalized))
}

export function filterPreviewWarnings(warnings: string[]): string[] {
  return warnings.filter((warning) => !isInfoOnlyParseWarning(warning))
}

export function formatParseStatus(status: string): { label: string; tone: 'ok' | 'warn' | 'fail' } {
  const normalized = status.trim().toLowerCase()
  if (normalized === 'ok') return { label: '解析成功', tone: 'ok' }
  if (normalized === 'degraded' || normalized === 'partial') return { label: '降级解析', tone: 'warn' }
  if (!normalized) return { label: '未知', tone: 'warn' }
  return { label: status, tone: 'fail' }
}

export function resolvePreviewMarkdown(item: MaterialParsePreviewItem): string {
  const markdown = item.content_markdown?.trim()
  if (markdown) return markdown
  return item.content_preview || ''
}

/** v1 checkpoint 仅有 content_preview，无 blocks/content_markdown，需重新 parse。 */
export function isStaleParsePreviewItem(item: MaterialParsePreviewItem): boolean {
  if (item.blocks?.length) return false
  if (item.content_markdown?.trim()) return false
  return true
}

export function isStaleParsePreview(preview: ParsePreviewResponse | null | undefined): boolean {
  if (!preview?.materials?.length) return false
  return preview.materials.some(isStaleParsePreviewItem)
}

export function shouldShowCapabilityFailure(item: MaterialParsePreviewItem): boolean {
  if (item.capability_passed !== false) return false
  const status = item.parse_status.trim().toLowerCase()
  return status === 'failed' || status === 'error'
}

export function shouldShowDegradedNotice(item: MaterialParsePreviewItem): boolean {
  if (shouldShowCapabilityFailure(item)) return false
  const status = item.parse_status.trim().toLowerCase()
  if (status === 'ok') return false
  return Boolean(item.degraded) || ['degraded', 'partial'].includes(status)
}

/** MinerU extract batch_id from parsed document enhancement_log. */
export function resolveMineruBatchId(
  item: MaterialParsePreviewItem,
  preview?: ParsePreviewResponse,
): string | null {
  const parseArtifact = preview?.parse_artifact
  const parsedDocuments = Array.isArray(parseArtifact?.parsed_documents)
    ? (parseArtifact.parsed_documents as Array<Record<string, unknown>>)
    : []
  const parsedDoc = parsedDocuments.find((doc) => doc.file_name === item.file_name)
  const document =
    parsedDoc?.document && typeof parsedDoc.document === 'object'
      ? (parsedDoc.document as Record<string, unknown>)
      : null
  const enhancementLog = Array.isArray(document?.enhancement_log)
    ? (document.enhancement_log as Array<Record<string, unknown>>)
    : []
  for (const entry of [...enhancementLog].reverse()) {
    const batchId = entry.batch_id
    if (typeof batchId === 'string' && batchId.trim()) return batchId.trim()
  }
  const fileResults = Array.isArray(parseArtifact?.file_results)
    ? (parseArtifact.file_results as Array<Record<string, unknown>>)
    : []
  const fileResult = fileResults.find((result) => result.file_name === item.file_name)
  const trace = Array.isArray(fileResult?.parser_chain) ? fileResult.parser_chain : []
  if (trace.some((name) => String(name).includes('mineru'))) {
    const subset = item.parse_artifact_subset
    const subsetBatch = subset?.batch_id
    if (typeof subsetBatch === 'string' && subsetBatch.trim()) return subsetBatch.trim()
  }
  return null
}

export function shouldShowPreviewWarnings(item: MaterialParsePreviewItem): boolean {
  const status = item.parse_status.trim().toLowerCase()
  if (status === 'ok' && !shouldShowDegradedNotice(item) && !shouldShowCapabilityFailure(item)) {
    return false
  }
  return filterPreviewWarnings(item.warnings).length > 0
}

export function isPdfFileName(fileName: string): boolean {
  return fileName.toLowerCase().endsWith('.pdf')
}

export function isImageFileName(fileName: string): boolean {
  return /\.(png|jpe?g|webp|gif|bmp)$/i.test(fileName)
}

export function isTextLikeFileName(fileName: string): boolean {
  return /\.(txt|md|csv|json|xml|html?)$/i.test(fileName)
}

export type OfficePreviewKind = 'word' | 'excel' | 'ppt'

export function isWordFileName(fileName: string): boolean {
  return /\.docx?$/i.test(fileName)
}

export function isExcelFileName(fileName: string): boolean {
  return /\.xlsx?$/i.test(fileName)
}

export function isPptFileName(fileName: string): boolean {
  return /\.pptx?$/i.test(fileName)
}

export function isLegacyOfficeFileName(fileName: string): boolean {
  const lower = fileName.toLowerCase()
  return lower.endsWith('.doc') || lower.endsWith('.ppt')
}

/** Office formats with in-browser preview (.docx / .xls / .xlsx / .pptx). */
export function resolveOfficePreviewKind(fileName: string): OfficePreviewKind | null {
  const lower = fileName.toLowerCase()
  if (lower.endsWith('.docx')) return 'word'
  if (lower.endsWith('.xlsx') || lower.endsWith('.xls')) return 'excel'
  if (lower.endsWith('.pptx')) return 'ppt'
  return null
}

export function isOfficeFileName(fileName: string): boolean {
  return isWordFileName(fileName) || isExcelFileName(fileName) || isPptFileName(fileName)
}
