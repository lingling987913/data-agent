'use client'

import { AlertTriangle, Loader2 } from 'lucide-react'
import type { ReviewBusinessStatusModel } from '@/features/super-agent/utils/superAgentProcessingViewModel'

export default function ReviewBusinessStatusCard({
  status,
  isRunning = false,
}: {
  status: ReviewBusinessStatusModel
  isRunning?: boolean
}) {
  return (
    <section
      className="rounded-xl border border-primaryAccent/20 bg-primaryAccent/5 px-4 py-3"
      data-testid="super-agent-review-business-status"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {isRunning ? (
              <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primaryAccent" aria-hidden />
            ) : null}
            <div className="text-[14px] font-semibold text-primary">{status.headline}</div>
          </div>
          {status.waitingHint ? (
            <p className="mt-1 text-[11px] leading-relaxed text-muted">{status.waitingHint}</p>
          ) : null}
        </div>
        <span className="rounded-full border border-primaryAccent/25 bg-background px-2.5 py-1 text-[10px] font-medium tabular-nums text-primaryAccent">
          {status.progress}%
        </span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border/10 bg-background/80 px-3 py-2">
          <div className="text-[10px] text-muted">当前阶段</div>
          <div className="mt-1 text-[12px] font-medium text-primary">{status.currentStage}</div>
        </div>
        <div className="rounded-lg border border-border/10 bg-background/80 px-3 py-2">
          <div className="text-[10px] text-muted">专项回传</div>
          <div className="mt-1 text-[12px] font-medium text-primary">{status.delegateSummary}</div>
        </div>
      </div>

      {status.latestFindings.length ? (
        <ul className="mt-3 space-y-1.5">
          {status.latestFindings.map((finding) => (
            <li
              key={finding}
              className="flex items-start gap-2 rounded-lg border border-[rgb(var(--color-sa-gold))]/20 bg-background/80 px-3 py-2 text-[10px] leading-relaxed text-primary"
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[rgb(var(--color-sa-gold))]" aria-hidden />
              <span>{finding}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
