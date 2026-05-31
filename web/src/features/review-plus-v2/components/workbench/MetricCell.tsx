'use client'

import { formatMetricValue } from '@/features/review-plus-v2/components/workbench/format'

export default function MetricCell({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-xl border border-border/20 bg-background px-3 py-2">
      <p className="text-[10px] text-muted">{label}</p>
      <p className="text-sm font-medium text-primary mt-0.5 tabular-nums">{formatMetricValue(value)}</p>
    </div>
  )
}
