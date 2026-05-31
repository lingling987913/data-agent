import type { AdaptiveRouterPayload, MaterialClassification } from '@/features/super-agent/types'

export const ADAPTIVE_DOMAIN_LABELS: Record<string, string> = {
  generic_document_review: '通用文档审查',
  aerospace_review: '航天审查',
}

export const ADAPTIVE_ROUTE_LABELS: Record<string, string> = {
  smart: '通用审查',
  review_plus: '文件组审查',
  gnc_review: 'GNC 专项',
  structure_only: '仅结构解析',
}

export const ADAPTIVE_PRIMARY_PATH_LABELS: Record<string, string> = {
  smart_committee: '智能审查委员会',
  review_plus: '文件组审查',
  gnc: 'GNC 专项',
  structure_only: '仅结构解析',
}

export const ADAPTIVE_SOURCE_LABELS: Record<string, string> = {
  llm: 'LLM 提议',
  baseline: '规则基线',
  error: '错误回退',
}

export type AdaptiveRouterDiagnostics = {
  visible: boolean
  payload: AdaptiveRouterPayload | null
  sourceLabel: string
  domainLabel: string
  routeLabel: string
  primaryPathLabel: string
  confidencePercent: number | null
  reasoningSummary: string
  guardrailCorrections: string[]
  riskFlags: string[]
  specialistCount: number
  taskSpecCount: number
  hasGuardrailCorrections: boolean
  userOverrides: {
    domain_id?: string
    route?: string
    recommended_route?: string
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

export function labelAdaptiveDomain(domainId: string): string {
  return ADAPTIVE_DOMAIN_LABELS[domainId] || domainId || '—'
}

export function labelAdaptiveRoute(route: string): string {
  return ADAPTIVE_ROUTE_LABELS[route] || route || '—'
}

export function labelAdaptiveSource(source: string): string {
  return ADAPTIVE_SOURCE_LABELS[source] || source || '—'
}

export function resolveAdaptiveRouterDiagnostics(
  classification?: MaterialClassification | null,
): AdaptiveRouterDiagnostics {
  const payload = classification?.adaptive_router
  const empty: AdaptiveRouterDiagnostics = {
    visible: false,
    payload: null,
    sourceLabel: '',
    domainLabel: '',
    routeLabel: '',
    primaryPathLabel: '',
    confidencePercent: null,
    reasoningSummary: '',
    guardrailCorrections: [],
    riskFlags: [],
    specialistCount: 0,
    taskSpecCount: 0,
    hasGuardrailCorrections: false,
    userOverrides: {},
  }
  if (!payload?.source) return empty

  const caps = asRecord(payload.selected_capabilities)
  const specialistIds = Array.isArray(caps?.specialist_ids)
    ? caps.specialist_ids.filter((item): item is string => typeof item === 'string')
    : []
  const taskSpecs = Array.isArray(payload.task_specs) ? payload.task_specs : []
  const corrections = Array.isArray(payload.guardrail_corrections)
    ? payload.guardrail_corrections.filter((item): item is string => typeof item === 'string')
    : []
  const riskFlags = Array.isArray(payload.risk_flags)
    ? payload.risk_flags.filter((item): item is string => typeof item === 'string')
    : []

  const primaryPath = String(payload.primary_path || caps?.primary_path || '')
  const confidence =
    typeof payload.confidence === 'number' && Number.isFinite(payload.confidence) ? payload.confidence : null

  return {
    visible: true,
    payload,
    sourceLabel: labelAdaptiveSource(payload.source),
    domainLabel: labelAdaptiveDomain(payload.domain_id),
    routeLabel: labelAdaptiveRoute(payload.route),
    primaryPathLabel: ADAPTIVE_PRIMARY_PATH_LABELS[primaryPath] || primaryPath || '—',
    confidencePercent: confidence != null ? Math.round(confidence * 100) : null,
    reasoningSummary: String(payload.reasoning_summary || '').trim(),
    guardrailCorrections: corrections,
    riskFlags,
    specialistCount: specialistIds.length,
    taskSpecCount: taskSpecs.length,
    hasGuardrailCorrections: corrections.length > 0,
    userOverrides: classification?.user_overrides || {},
  }
}

/** Map adaptive router route to wizard requested_route. */
export function adaptiveRouteToRequestedRoute(route: string): 'auto' | 'smart' | 'review_plus' | 'gnc_review_only' | 'structure_only' {
  const normalized = route.trim().toLowerCase()
  if (normalized === 'review_plus') return 'review_plus'
  if (normalized === 'gnc_review') return 'gnc_review_only'
  if (normalized === 'structure_only') return 'structure_only'
  if (normalized === 'smart') return 'smart'
  return 'auto'
}
