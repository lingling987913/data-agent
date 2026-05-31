import type { MaterialClassification, SuperAgentRoute } from '@/features/super-agent/types'
import { ROUTE_LABELS } from '@/lib/aeroTerminology'

export type PostParseRouteViewModel = {
  visible: boolean
  finalRouteLabel: string
  initialRouteLabel: string
  changed: boolean
  confidencePercent: number | null
  reasons: string[]
  showUserOverrideWarning: boolean
  userOverrideMessage: string
}

function labelRoute(route: string | undefined): string {
  if (!route) return '—'
  return ROUTE_LABELS[route as SuperAgentRoute] || route
}

export function resolvePostParseRouteViewModel(
  classification: MaterialClassification | null | undefined,
  requestedRoute?: SuperAgentRoute,
  options?: { parseComplete?: boolean },
): PostParseRouteViewModel {
  const empty: PostParseRouteViewModel = {
    visible: false,
    finalRouteLabel: '',
    initialRouteLabel: '',
    changed: false,
    confidencePercent: null,
    reasons: [],
    showUserOverrideWarning: false,
    userOverrideMessage: '',
  }
  if (!classification) return empty

  const postParse = classification.post_parse_route
  const finalRoute =
    classification.final_recommended_route
    || postParse?.effective_route
    || postParse?.suggested_route
    || classification.recommended_route
  const initialRoute = classification.initial_recommended_route || postParse?.initial_route
  const hasPostParseSignal = Boolean(
    postParse
    || classification.route_decision_source === 'post_parse'
    || classification.final_recommended_route
    || classification.post_parse_reason,
  )
  const visible = options?.parseComplete === true
    ? Boolean(classification.doc_type && finalRoute)
    : hasPostParseSignal
  if (!visible) return empty

  const changed = postParse?.changed_from_initial === true
    || (Boolean(initialRoute && finalRoute) && initialRoute !== finalRoute)
  const confidence = postParse?.confidence ?? classification.confidence
  const reasons = postParse?.reasons?.length
    ? postParse.reasons
    : classification.post_parse_reason
      ? [classification.post_parse_reason]
      : []

  const showUserOverrideWarning = Boolean(
    postParse?.user_override_active && requestedRoute && requestedRoute !== 'auto',
  )
  const userOverrideMessage = showUserOverrideWarning
    ? `已采用人工指定模式 ${labelRoute(requestedRoute)}，解析后建议为 ${labelRoute(postParse?.suggested_route || finalRoute)}。`
    : ''

  return {
    visible: true,
    finalRouteLabel: labelRoute(finalRoute),
    initialRouteLabel: labelRoute(initialRoute),
    changed,
    confidencePercent: typeof confidence === 'number' ? Math.round(confidence * 100) : null,
    reasons,
    showUserOverrideWarning,
    userOverrideMessage,
  }
}
