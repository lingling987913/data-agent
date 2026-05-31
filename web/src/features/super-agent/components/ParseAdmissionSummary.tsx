'use client'

import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react'
import type { ParseAdmissionSummaryModel } from '@/features/super-agent/utils/parseAdmissionSummary'

function statusTone(status: ParseAdmissionSummaryModel['status']): {
  badge: string
  icon: typeof CheckCircle2
} {
  if (status === 'ready') {
    return {
      badge: 'border-positive/25 bg-positive/10 text-positive',
      icon: CheckCircle2,
    }
  }
  if (status === 'review_required') {
    return {
      badge: 'border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]',
      icon: AlertTriangle,
    }
  }
  return {
    badge: 'border-border/20 bg-background/80 text-muted',
    icon: Loader2,
  }
}

export default function ParseAdmissionSummary({
  summary,
  inProgress = false,
}: {
  summary: ParseAdmissionSummaryModel
  inProgress?: boolean
}) {
  const tone = statusTone(summary.status)
  const Icon = tone.icon

  return (
    <section
      className="mb-4 rounded-lg border border-border/15 bg-background/40 px-3 py-2.5"
      data-testid="super-agent-parse-admission-summary"
      data-admission-status={summary.status}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${tone.badge}`}
          data-testid="super-agent-parse-status-badge"
        >
          <Icon
            className={`h-3.5 w-3.5 shrink-0 ${inProgress ? 'animate-spin' : ''}`}
            aria-hidden
          />
          {summary.headline}
        </div>

        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
          <Metric label="材料" value={`${summary.parsedOk}/${summary.materialCount}`} />
          <Metric
            label="降级"
            value={String(summary.degradedCount)}
            highlight={summary.degradedCount > 0}
          />
          <Metric
            label="结构化"
            value={
              summary.structureReady == null
                ? '—'
                : summary.structureReady
                  ? '就绪'
                  : '未完成'
            }
            highlight={summary.structureReady === false}
          />
          <Metric
            label="章节"
            value={summary.sectionCount == null ? '—' : String(summary.sectionCount)}
          />
          <Metric
            label="证据"
            value={summary.evidenceCount == null ? '—' : String(summary.evidenceCount)}
          />
        </div>
      </div>

      <p className="mt-2 text-[11px] text-muted/90" data-testid="super-agent-parse-status-hint">
        {summary.nextAction}
      </p>

      {summary.risks.length ? (
        <ul
          className="mt-2 space-y-1"
          data-testid="super-agent-parse-risk-list"
        >
          {summary.risks.map((risk) => (
            <li
              key={risk}
              className="truncate text-[11px] text-[rgb(var(--color-sa-gold))]"
              title={risk}
            >
              · {risk}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

function Metric({
  label,
  value,
  highlight = false,
}: {
  label: string
  value: string
  highlight?: boolean
}) {
  return (
    <span className="inline-flex items-baseline gap-1 tabular-nums">
      <span className="text-muted/70">{label}</span>
      <span className={highlight ? 'font-medium text-[rgb(var(--color-sa-gold))]' : 'font-medium text-primary'}>
        {value}
      </span>
    </span>
  )
}
