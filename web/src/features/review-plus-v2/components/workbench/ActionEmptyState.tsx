'use client'

import { FileSearch } from 'lucide-react'

export default function ActionEmptyState({
  title,
  description,
  hint,
}: {
  title: string
  description: string
  hint?: string
}) {
  return (
    <div className="aq-soft-panel rounded-xl p-8 text-center space-y-3">
      <div className="mx-auto flex size-12 items-center justify-center rounded-2xl border border-border/70 bg-muted/5 text-primaryAccent">
        <FileSearch size={20} aria-hidden />
      </div>
      <div className="space-y-1.5">
        <p className="text-[13px] font-medium text-primary">{title}</p>
        <p className="text-[11px] leading-6 text-primary/70">{description}</p>
        {hint ? <p className="text-[10px] text-muted/70">{hint}</p> : null}
      </div>
    </div>
  )
}
