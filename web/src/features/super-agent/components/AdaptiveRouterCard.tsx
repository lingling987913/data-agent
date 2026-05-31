'use client'

import { AlertTriangle, Route } from 'lucide-react'
import type { MaterialClassification, SuperAgentRoute } from '@/features/super-agent/types'
import {
  ADAPTIVE_DOMAIN_LABELS,
  ADAPTIVE_ROUTE_LABELS,
  adaptiveRouteToRequestedRoute,
  resolveAdaptiveRouterDiagnostics,
} from '@/features/super-agent/utils/adaptiveRouterDiagnostics'

const DOMAIN_OVERRIDE_OPTIONS = Object.entries(ADAPTIVE_DOMAIN_LABELS)
const ROUTE_OVERRIDE_OPTIONS = Object.entries(ADAPTIVE_ROUTE_LABELS)

export default function AdaptiveRouterCard({
  classification,
  requestedRoute,
  onApplyOverride,
  className = '',
  testId = 'super-agent-adaptive-router-card',
}: {
  classification: MaterialClassification
  requestedRoute: SuperAgentRoute
  onApplyOverride?: (patch: {
    domain_id?: string
    route?: string
    requested_route: SuperAgentRoute
    classification: MaterialClassification
  }) => void
  className?: string
  testId?: string
}) {
  const diagnostics = resolveAdaptiveRouterDiagnostics(classification)
  if (!diagnostics.visible || !diagnostics.payload) return null

  const overrideDomain = diagnostics.userOverrides.domain_id || diagnostics.payload.domain_id
  const overrideRoute =
    diagnostics.userOverrides.route
    || diagnostics.userOverrides.recommended_route
    || diagnostics.payload.route
  const hasUserOverride = Boolean(
    diagnostics.userOverrides.domain_id
    || diagnostics.userOverrides.route
    || diagnostics.userOverrides.recommended_route,
  )
  const taskSpecPreview = Array.isArray(diagnostics.payload.task_specs)
    ? diagnostics.payload.task_specs.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    : []

  return (
    <section
      className={`mt-4 rounded-xl border border-border/10 bg-background/70 p-4 text-[12px] ${className}`.trim()}
      data-testid={testId}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[11px] font-medium text-primary">
          <Route className="h-4 w-4 text-primaryAccent" aria-hidden />
          智能路由建议
        </div>
        {diagnostics.confidencePercent != null ? (
          <span className="rounded-full bg-background/80 px-2 py-0.5 text-[10px] text-muted">
            置信度 {diagnostics.confidencePercent}%
          </span>
        ) : null}
      </div>

      <p className="text-[10px] text-muted">
        {diagnostics.sourceLabel}
        {' · '}
        已根据槽位/强弱信号/领域边界进行安全校验
      </p>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border/10 px-3 py-2">
          <div className="text-[10px] text-muted/70">领域</div>
          <div className="mt-1 text-[12px] font-medium text-primary">{diagnostics.domainLabel}</div>
          <div className="mt-0.5 font-mono text-[10px] text-muted">{diagnostics.payload.domain_id}</div>
        </div>
        <div className="rounded-lg border border-border/10 px-3 py-2">
          <div className="text-[10px] text-muted/70">路由 / 主路径</div>
          <div className="mt-1 text-[12px] font-medium text-primary">
            {diagnostics.routeLabel}
            {diagnostics.primaryPathLabel !== diagnostics.routeLabel
              ? ` · ${diagnostics.primaryPathLabel}`
              : ''}
          </div>
        </div>
        <div className="rounded-lg border border-border/10 px-3 py-2">
          <div className="text-[10px] text-muted/70">专家 / TaskSpec</div>
          <div className="mt-1 text-[12px] font-medium text-primary">
            专家 {diagnostics.specialistCount} · TaskSpec {diagnostics.taskSpecCount}
          </div>
        </div>
        <div className="rounded-lg border border-border/10 px-3 py-2">
          <div className="text-[10px] text-muted/70">决策来源</div>
          <div className="mt-1 text-[12px] font-medium text-primary">{diagnostics.sourceLabel}</div>
          <div className="mt-0.5 text-[10px] text-muted">LLM 提议 / 规则基线 / Guardrail 修正</div>
        </div>
      </div>

      {diagnostics.reasoningSummary ? (
        <p className="mt-3 text-[11px] text-muted">{diagnostics.reasoningSummary}</p>
      ) : null}

      {taskSpecPreview.length ? (
        <div className="mt-3 rounded-lg border border-border/10 px-3 py-2">
          <div className="text-[10px] text-muted/70">TaskSpec 预览</div>
          <ul className="mt-1 space-y-1 text-[11px] text-primary">
            {taskSpecPreview.slice(0, 6).map((spec, index) => (
              <li key={String(spec.task_id || index)}>
                {String(spec.title || spec.task_id || `任务 ${index + 1}`)}
                {spec.specialist_id ? ` · ${String(spec.specialist_id)}` : ''}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {hasUserOverride ? (
        <p className="mt-3 rounded-lg border border-primaryAccent/25 bg-primaryAccent/5 px-3 py-2 text-[11px] text-primary">
          已采用人工覆盖，智能路由将作为参考。
        </p>
      ) : null}

      {diagnostics.hasGuardrailCorrections ? (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <div>
            <div className="font-medium">Guardrail 修正了 LLM 提议</div>
            <ul className="mt-1 list-inside list-disc space-y-0.5">
              {diagnostics.guardrailCorrections.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      {diagnostics.riskFlags.length ? (
        <p className="mt-2 text-[10px] text-muted">
          风险标记：{diagnostics.riskFlags.join(' · ')}
        </p>
      ) : null}

      {onApplyOverride ? (
        <div className="mt-4 space-y-3 rounded-lg border border-dashed border-border/20 bg-background/50 p-3">
          <div className="text-[10px] font-medium text-muted">高级覆盖（可选）</div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-[10px] text-muted">领域 domain</span>
              <select
                value={overrideDomain}
                onChange={(event) => {
                  const domain_id = event.target.value
                  onApplyOverride({
                    domain_id,
                    route: overrideRoute,
                    requested_route: requestedRoute,
                    classification: {
                      ...classification,
                      user_overrides: {
                        ...(classification.user_overrides || {}),
                        domain_id,
                        route: overrideRoute,
                      },
                    },
                  })
                }}
                className="mt-1 w-full rounded-lg border border-border/25 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
              >
                {DOMAIN_OVERRIDE_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-[10px] text-muted">路由 route</span>
              <select
                value={overrideRoute}
                onChange={(event) => {
                  const route = event.target.value
                  const requested_route = adaptiveRouteToRequestedRoute(route)
                  onApplyOverride({
                    domain_id: overrideDomain,
                    route,
                    requested_route,
                    classification: {
                      ...classification,
                      user_overrides: {
                        ...(classification.user_overrides || {}),
                        domain_id: overrideDomain,
                        route,
                        recommended_route: route,
                      },
                    },
                  })
                }}
                className="mt-1 w-full rounded-lg border border-border/25 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
              >
                {ROUTE_OVERRIDE_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="text-[10px] text-muted/80">
            覆盖将写入检查点；下次识别时作为 user_overrides 参与 Guardrail，并与上方「高级选项」路由选择同步。
          </p>
        </div>
      ) : null}
    </section>
  )
}
