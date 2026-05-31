'use client'

import type { ReactNode } from 'react'

export type ResultSummaryItem = {
  label: string
  value: number | string
  tone?: 'default' | 'danger' | 'warning' | 'success' | 'brand'
}

const toneClass: Record<NonNullable<ResultSummaryItem['tone']>, string> = {
  default: 'border-border/30 bg-background text-primary',
  danger: 'border-destructive/20 bg-destructive/5 text-destructive',
  warning: 'border-warning/20 bg-warning/8 text-warning',
  success: 'border-positive/20 bg-positive/8 text-positive',
  brand: 'border-primaryAccent/20 bg-primaryAccent/8 text-primaryAccent',
}

export default function ResultSummaryBar({
  items,
  hint,
  actions,
}: {
  items: ResultSummaryItem[]
  hint?: string
  actions?: ReactNode
}) {
  return (
    <div className="rounded-2xl border border-border/25 bg-surface px-3 py-2 shadow-soft">
      <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          {items.map((item) => (
            <span
              key={`${item.label}-${String(item.value)}`}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] ${toneClass[item.tone || 'default']}`}
            >
              <span className="text-muted">{item.label}</span>
              <span className="font-medium tabular-nums">{item.value}</span>
            </span>
          ))}
          {hint ? (
            <span className="min-w-[220px] flex-1 text-[10px] leading-relaxed text-muted">{hint}</span>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  )
}
