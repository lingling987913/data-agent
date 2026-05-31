'use client'

import type { WorkbenchStatAction } from '@/features/unified-review-workbench/utils/workbenchStatAction'
import { resolveStatActionAriaLabel } from '@/features/unified-review-workbench/utils/workbenchStatAction'

interface Props {
  label: string
  value: string | number
  action?: WorkbenchStatAction | null
  onAction?: (action: WorkbenchStatAction) => void
  className?: string
  detailHint?: string
}

export default function WorkbenchStatCard({
  label,
  value,
  action,
  onAction,
  className = '',
  detailHint,
}: Props) {
  const interactive = Boolean(action && !action.disabled && onAction)
  const ariaLabel = resolveStatActionAriaLabel(label, action)

  const body = (
    <>
      <div className="flex items-center justify-between gap-1">
        <span className="text-[10px] text-muted">{label}</span>
        {interactive ? (
          <span className="text-[9px] text-primaryAccent/80 opacity-0 transition-opacity group-hover:opacity-100">
            查看详情
          </span>
        ) : null}
      </div>
      <div className="mt-1 text-[12px] font-medium tabular-nums text-primary">{value}</div>
      {detailHint ? (
        <p className="mt-1 text-[10px] leading-snug text-muted/80">{detailHint}</p>
      ) : null}
    </>
  )

  if (!interactive) {
    return (
      <div
        className={`rounded-xl border border-border/15 bg-surface px-3 py-2 ${className}`}
        title={action?.disabled ? '暂无关联明细' : undefined}
      >
        {body}
      </div>
    )
  }

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={() => onAction!(action!)}
      className={`group w-full rounded-xl border border-border/15 bg-surface px-3 py-2 text-left transition-colors hover:border-primaryAccent/35 hover:bg-primaryAccent/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primaryAccent ${className}`}
    >
      {body}
    </button>
  )
}
