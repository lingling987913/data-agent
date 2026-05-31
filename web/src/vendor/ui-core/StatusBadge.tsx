import * as React from 'react'
import { cn } from './utils'

export type StatusBadgeTone = 'neutral' | 'positive' | 'warning' | 'destructive' | 'brand'

export type StatusBadgeProps = {
  children: React.ReactNode
  tone?: StatusBadgeTone
  className?: string
}

const toneClassName: Record<StatusBadgeTone, string> = {
  neutral: 'border-border/20 bg-background-secondary text-muted',
  positive: 'border-positive/20 bg-positive/10 text-positive',
  warning: 'border-domain-brand/20 bg-domain-brand/10 text-domain-brand',
  destructive: 'border-destructive/20 bg-destructive/10 text-destructive',
  brand: 'border-brand/20 bg-brand/10 text-brand',
}

export function StatusBadge({
  children,
  tone = 'neutral',
  className,
}: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex w-fit items-center rounded-full border px-2.5 py-1 text-xs font-medium leading-none',
        toneClassName[tone],
        className
      )}
    >
      {children}
    </span>
  )
}
