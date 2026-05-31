const INTERNAL_TELEMETRY_KEYS = [
  'execution_mode_summary',
  'scheduler_summary',
  'task_board_summary',
  'fallback_reason',
  'harness_count',
  'generic_llm_harness_count',
  'deterministic_count',
  'blocked_count',
  'failed_count',
] as const

const TELEMETRY_PATTERNS: RegExp[] = [
  /\bexecution_mode_summary\s*[=:]\s*[\{\[]/i,
  /\bscheduler_summary\s*[=:]\s*[\{\[]/i,
  /\btask_board_summary\s*[=:]\s*[\{\[]/i,
  /\bfallback_reason\s*=/i,
  /\b\w+_summary\s*=\s*[\{\[]/,
  /\bexecution_mode\s*=\s*[\{]/i,
  /\bexecution_mode\s*=\s*deterministic/i,
  /\blimited\s*=\s*(true|false)/i,
  /\bbootstrap_mode\s*=/i,
  /\bgate_limited:/i,
  /\b(harness_count|generic_llm_harness_count|deterministic_count|blocked_count|failed_count)\s*[=:]\s*\d/i,
  /['"](harness_count|generic_llm_harness_count|deterministic_count|blocked_count|failed_count)['"]\s*:\s*\d/i,
  /\btraceability_summary\s*=/i,
  /\bdeterministic_items\s*=/i,
]

const DICT_TELEMETRY_INNER = /[\{\[][^}\]]*(harness_count|generic_llm_harness_count|deterministic_count|blocked_count|failed_count|execution_mode)[^}\]]*[\}\]]/i

const KEY_VALUE_DICT_LINE = /^[\w.\s/-]+=\{.*\}$/

function cjkCharCount(text: string): number {
  let count = 0
  for (const char of text) {
    const code = char.codePointAt(0) || 0
    if (code >= 0x4e00 && code <= 0x9fff) count += 1
  }
  return count
}

export function isInternalDiagnosticText(text: string): boolean {
  const normalized = String(text || '').trim()
  if (!normalized) return false

  if (TELEMETRY_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return true
  }

  if (DICT_TELEMETRY_INNER.test(normalized)) {
    return true
  }

  if (KEY_VALUE_DICT_LINE.test(normalized)) {
    const inner = normalized.split('=', 2)[1] || ''
    if (INTERNAL_TELEMETRY_KEYS.some((key) => inner.includes(key))) {
      return true
    }
  }

  const lowered = normalized.toLowerCase()
  if (lowered.startsWith('smart committee limited:') && normalized.includes('{')) {
    return true
  }

  if (cjkCharCount(normalized) >= Math.max(4, Math.floor(normalized.length / 3))) {
    if (!/[\{\[]/.test(normalized)) return false
    if (!INTERNAL_TELEMETRY_KEYS.some((key) => normalized.includes(key))) return false
  }

  return false
}

export function filterBusinessLines(lines: string[]): string[] {
  const seen = new Set<string>()
  const filtered: string[] = []
  for (const item of lines) {
    const text = String(item || '').trim()
    if (!text || isInternalDiagnosticText(text) || seen.has(text)) {
      continue
    }
    seen.add(text)
    filtered.push(text)
  }
  return filtered
}

export function sanitizeBusinessMarkdown(markdown: string): string {
  if (!markdown) return ''
  const kept: string[] = []
  for (const line of markdown.split('\n')) {
    const stripped = line.trimStart()
    if (stripped.startsWith('- ')) {
      const content = stripped.slice(2).trim()
      if (isInternalDiagnosticText(content)) continue
    } else if (stripped.startsWith('* ')) {
      const content = stripped.slice(2).trim()
      if (isInternalDiagnosticText(content)) continue
    } else if (isInternalDiagnosticText(stripped)) {
      continue
    }
    kept.push(line)
  }
  return kept.join('\n')
}

export function sanitizeSmartDiagnosticText(text: string): string {
  return sanitizeBusinessMarkdown(text)
}

export function sanitizeBusinessReportText(text: string): string {
  return sanitizeBusinessMarkdown(text)
}

/** @deprecated Use isInternalDiagnosticText */
export const isSmartInternalDiagnostic = isInternalDiagnosticText

/** @deprecated Use filterBusinessLines */
export const filterBusinessFindings = filterBusinessLines
