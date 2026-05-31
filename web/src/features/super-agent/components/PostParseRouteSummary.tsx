'use client'

import { Route } from 'lucide-react'
import type { MaterialClassification, SuperAgentRoute } from '@/features/super-agent/types'
import { resolvePostParseRouteViewModel } from '@/features/super-agent/utils/postParseRouteViewModel'

function buildRouteNote(model: ReturnType<typeof resolvePostParseRouteViewModel>): string | null {
  if (model.showUserOverrideWarning && model.userOverrideMessage) {
    return model.userOverrideMessage
  }
  if (model.changed && model.initialRouteLabel !== '—') {
    return `与步骤 2 不同：${model.initialRouteLabel} → ${model.finalRouteLabel}`
  }
  return null
}

export default function PostParseRouteSummary({
  classification,
  requestedRoute,
}: {
  classification: MaterialClassification
  requestedRoute?: SuperAgentRoute
}) {
  const model = resolvePostParseRouteViewModel(classification, requestedRoute, { parseComplete: true })
  if (!model.visible) return null

  const routeNote = buildRouteNote(model)

  return (
    <div
      className="rounded-lg border border-border/15 bg-background/60 px-3 py-3 text-[12px]"
      data-testid="super-agent-post-parse-route-summary"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted">
            <Route className="h-3.5 w-3.5 text-primaryAccent" aria-hidden />
            智能路由
          </div>
          <p className="mt-1 text-[14px] font-semibold text-primary">
            {model.finalRouteLabel}
            {model.confidencePercent != null ? (
              <span className="ml-1.5 text-[12px] font-normal text-muted">
                {model.confidencePercent}%
              </span>
            ) : null}
          </p>
        </div>
        {routeNote ? (
          <p
            className="max-w-full text-[10px] text-[rgb(var(--color-sa-gold))] sm:max-w-[240px] sm:text-right"
            data-testid="super-agent-post-parse-route-changed-banner"
          >
            {routeNote}
          </p>
        ) : null}
      </div>

      {model.reasons.length ? (
        <p className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-muted">
          {model.reasons.slice(0, 2).join(' · ')}
        </p>
      ) : null}
    </div>
  )
}
