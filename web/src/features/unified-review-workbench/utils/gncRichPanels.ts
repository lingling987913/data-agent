export type GncArbitrationDisplayStatus = 'pending' | 'resolved' | 'not_required'

export type GncDisplayListItem = Record<string, unknown> | string

export interface GncParsedDecision {
  verdict: string
  releaseDecision: string
  rationale: string
  requiresArbitration: boolean
  arbitrationItems: GncDisplayListItem[]
  expertConflicts: GncDisplayListItem[]
  conflictResolutions: GncDisplayListItem[]
  keyRisks: string[]
  conflictAnalysis: GncDisplayListItem[]
}

export function resolveGncArbitrationDisplayStatus(input: {
  arbitrationStatus?: string
  requiresArbitration?: boolean
  workbenchPhase?: string
}): GncArbitrationDisplayStatus {
  const status = String(input.arbitrationStatus || '').toLowerCase()
  if (status === 'resolved' || status === 'completed') return 'resolved'
  if (status === 'not_required' || status === 'none' || status === 'skipped') return 'not_required'
  if (input.requiresArbitration === false) return 'not_required'
  if (!input.requiresArbitration && input.workbenchPhase === 'completed') return 'not_required'
  if (!input.requiresArbitration && status && status !== 'pending') return 'not_required'
  if (input.requiresArbitration || status === 'pending' || input.workbenchPhase === 'arbitration') {
    return 'pending'
  }
  return 'not_required'
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

function asDisplayList(value: unknown): GncDisplayListItem[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item) => item != null)
    .map((item) => {
      if (typeof item === 'string') return item.trim()
      if (typeof item === 'object') return item as Record<string, unknown>
      return String(item)
    })
    .filter((item) => (typeof item === 'string' ? item.length > 0 : Object.keys(item).length > 0))
}

function asConflictList(value: unknown): GncDisplayListItem[] {
  return asDisplayList(value)
}

export function hasGncDecisionContent(decision: GncParsedDecision): boolean {
  if (decision.verdict.trim()) return true
  if (decision.rationale.trim()) return true
  if (decision.requiresArbitration) return true
  if (decision.arbitrationItems.length > 0) return true
  if (decision.expertConflicts.length > 0) return true
  if (decision.conflictResolutions.length > 0) return true
  if (decision.keyRisks.length > 0) return true
  if (decision.conflictAnalysis.length > 0) return true
  return false
}

export function extractGncArbitrationConflictIds(items: unknown[]): string[] {
  return items
    .map((item) => {
      if (typeof item === 'string') return item.trim()
      if (item && typeof item === 'object') {
        const record = item as Record<string, unknown>
        return String(record.conflict_id || record.conflict_key || '').trim()
      }
      return ''
    })
    .filter(Boolean)
}

export function parseGncDecision(data: Record<string, unknown> | null | undefined): GncParsedDecision {
  const payload = data || {}
  const verdict = String(payload.verdict || payload.release_decision || '')
  return {
    verdict,
    releaseDecision: String(payload.release_decision || payload.verdict || ''),
    rationale: String(payload.rationale || ''),
    requiresArbitration: Boolean(payload.requires_arbitration),
    arbitrationItems: asDisplayList(payload.arbitration_items),
    expertConflicts: asConflictList(payload.expert_conflicts),
    conflictResolutions: asDisplayList(payload.conflict_resolutions),
    keyRisks: asStringList(payload.key_risks || payload.risk_categories || payload.residual_risks),
    conflictAnalysis: asConflictList(payload.conflict_analysis),
  }
}

export function formatGncVerdictLabel(verdict: string): string {
  const normalized = verdict.trim().toLowerCase()
  if (!normalized) return '待定'
  const labels: Record<string, string> = {
    approved: '通过',
    conditionally_approved: '有条件通过',
    needs_review: '需复审',
    rejected: '不通过',
    pass: '通过',
    fail: '不通过',
  }
  return labels[normalized] || verdict
}

export function arbitrationStatusLabel(status: GncArbitrationDisplayStatus): string {
  if (status === 'pending') return '待人工仲裁'
  if (status === 'resolved') return '已仲裁结案'
  return '无需仲裁'
}

export function arbitrationStatusTone(status: GncArbitrationDisplayStatus): string {
  if (status === 'pending') return 'border-amber-500/30 bg-amber-500/5 text-amber-800'
  if (status === 'resolved') return 'border-emerald-500/30 bg-emerald-500/5 text-emerald-800'
  return 'border-border/20 bg-background text-muted'
}

export function hasRichMinutesStruct(data: Record<string, unknown> | null | undefined): boolean {
  if (!data || typeof data !== 'object') return false
  if (typeof data.text === 'string' && data.text.trim()) return true
  const keys = [
    'section_rid_map',
    'rule_coverage_summary',
    'traceability_matrix_summary',
    'unit_review_summary',
    'prior_cycle_summary',
    'committee_members',
    'conclusion_draft',
    'follow_up_items',
  ]
  return keys.some((key) => data[key] != null && (
    typeof data[key] === 'string'
      ? String(data[key]).trim().length > 0
      : (Array.isArray(data[key]) ? (data[key] as unknown[]).length > 0 : Object.keys(data[key] as object).length > 0)
  ))
}

export function parseGncReportPayload(data: unknown): { markdown: string; summary: string } | null {
  if (!data) return null
  if (typeof data === 'string' && data.trim()) {
    return { markdown: data.trim(), summary: '' }
  }
  if (typeof data !== 'object' || data === null) return null
  const record = data as Record<string, unknown>
  const markdown = String(record.markdown || record.content || record.report_markdown || '').trim()
  const summary = String(record.summary || record.title || '').trim()
  if (!markdown && !summary) return null
  return { markdown, summary }
}

export function summarizeRecordMap(value: unknown): Array<{ key: string; detail: string }> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>).map(([key, raw]) => {
    if (typeof raw === 'string') return { key, detail: raw }
    if (typeof raw === 'number' || typeof raw === 'boolean') {
      return { key, detail: String(raw) }
    }
    if (Array.isArray(raw)) return { key, detail: `${raw.length} 项` }
    if (raw && typeof raw === 'object') {
      const obj = raw as Record<string, unknown>
      const ridCount = obj.rid_count
      if (ridCount != null) return { key, detail: `RID ${ridCount} 条` }
      const passed = obj.passed
      const failed = obj.failed
      if (passed != null || failed != null) {
        return { key, detail: `通过 ${passed ?? 0} · 未通过 ${failed ?? 0}` }
      }
      return { key, detail: `${Object.keys(obj).length} 字段` }
    }
    return { key, detail: '—' }
  })
}

export function hasGncMinutesVisibleSections(data: Record<string, unknown>): boolean {
  if (typeof data.text === 'string' && data.text.trim()) return true
  if (typeof data.conclusion_draft === 'string' && data.conclusion_draft.trim()) return true
  if (Array.isArray(data.committee_members) && data.committee_members.length > 0) return true
  if (summarizeRecordMap(data.section_rid_map).length > 0) return true
  if (summarizeRecordMap(data.rule_coverage_summary).length > 0) return true
  if (data.traceability_matrix_summary != null && (
    Array.isArray(data.traceability_matrix_summary)
      ? data.traceability_matrix_summary.length > 0
      : typeof data.traceability_matrix_summary === 'object'
        ? Object.keys(data.traceability_matrix_summary as object).length > 0
        : String(data.traceability_matrix_summary).trim().length > 0
  )) return true
  if (data.unit_review_summary != null && (
    Array.isArray(data.unit_review_summary)
      ? data.unit_review_summary.length > 0
      : typeof data.unit_review_summary === 'object'
        ? Object.keys(data.unit_review_summary as object).length > 0
        : String(data.unit_review_summary).trim().length > 0
  )) return true
  if (data.prior_cycle_summary != null && (
    Array.isArray(data.prior_cycle_summary)
      ? data.prior_cycle_summary.length > 0
      : typeof data.prior_cycle_summary === 'object'
        ? Object.keys(data.prior_cycle_summary as object).length > 0
        : String(data.prior_cycle_summary).trim().length > 0
  )) return true
  if (Array.isArray(data.follow_up_items) && data.follow_up_items.some((item) => String(item || '').trim())) {
    return true
  }
  return false
}

export function formatGncDisplayListItem(item: GncDisplayListItem): { title: string; detail: string } {
  if (typeof item === 'string') {
    const colon = item.indexOf(':')
    if (colon > 0) {
      return {
        title: item.slice(0, colon).trim(),
        detail: item.slice(colon + 1).trim(),
      }
    }
    return { title: item, detail: '' }
  }
  const title = String(
    item.conflict_id
    || item.conflict_key
    || item.title
    || item.summary
    || item.agent_key
    || '项',
  )
  const parts = [
    item.title && item.conflict_id ? String(item.title) : '',
    item.summary && String(item.summary) !== title ? String(item.summary) : '',
    item.reason ? `原因：${String(item.reason)}` : '',
    item.source ? `来源：${String(item.source)}` : '',
    item.resolution ? `裁决：${String(item.resolution)}` : '',
    item.conflict_key ? `键：${String(item.conflict_key)}` : '',
    item.requires_arbitration != null ? `需仲裁：${item.requires_arbitration ? '是' : '否'}` : '',
  ].filter(Boolean)
  return { title, detail: parts.join(' · ') }
}

export function formatConflictItem(item: GncDisplayListItem): { title: string; detail: string } {
  return formatGncDisplayListItem(item)
}
