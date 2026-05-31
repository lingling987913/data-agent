import { sanitizeBusinessReportText } from '@/features/super-agent/utils/diagnosticsSanitizer'
import { resolveVerdictLabel } from '@/features/unified-review-workbench/utils/zhWorkbenchText'

const INTERNAL_REPORT_MARKERS = [
  'Report ID:',
  'Review type:',
  'Generated at:',
  '## 2. 解析与结构化质量',
  '## 3. 结构化解析结果',
  'Layout blocks:',
  'Source block:',
  'Finding ID:',
  '## 附录 A：解析产物摘要',
  '## 附录 B：原始结构化数据索引',
  'Super Agent 统一审查报告',
  'GNC 统一审查报告',
] as const

const INTERNAL_BOILERPLATE_LINES = [
  'Word 兼容格式导出，用于线下流转与归档。',
  '参考 CASA COA 201（Form 282）检查单逻辑与 QJ 3200/QJ 20065.13 航天标准化审查报告结构，并结合文件组审查场景做工程化裁剪。',
  '参考 CASA COA 201（Form 282）设计/制造质量体系检查单逻辑，',
] as const

export function isInternalReviewReport(markdown: string): boolean {
  const text = String(markdown || '')
  if (!text.trim()) return false
  const hits = INTERNAL_REPORT_MARKERS.filter((marker) => text.includes(marker)).length
  return hits >= 2
}

export function stripInternalBoilerplateLines(markdown: string): string {
  return markdown
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim()
      if (!trimmed) return true
      if (INTERNAL_BOILERPLATE_LINES.some((item) => trimmed.includes(item))) return false
      if (trimmed.startsWith('> 参考 CASA COA 201')) return false
      return true
    })
    .join('\n')
}

export function localizeConclusionVerdicts(markdown: string): string {
  return String(markdown || '')
    .split('\n')
    .map((line) =>
      line.replace(/(结论[：:]\s*)([A-Za-z][A-Za-z0-9_]*)\b/g, (_, prefix: string, token: string) => {
        const localized = resolveVerdictLabel(token, token)
        return `${prefix}${localized}`
      }),
    )
    .join('\n')
}

export function resolveBusinessExportMarkdown(markdown: string): string {
  const sanitized = localizeConclusionVerdicts(
    stripInternalBoilerplateLines(sanitizeBusinessReportText(String(markdown || ''))),
  )
  if (!sanitized.trim()) return ''
  if (isInternalReviewReport(sanitized)) return ''
  return sanitized.trim()
}
