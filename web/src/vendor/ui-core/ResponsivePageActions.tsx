'use client'

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { cn } from './utils'
import { useIsMobile } from './useIsMobile'

type ActionTone = 'default' | 'brand' | 'success' | 'warning' | 'danger'

export interface ResponsiveActionItem {
  key: string
  label: string
  onClick: () => void
  disabled?: boolean
  tone?: ActionTone
  icon?: ReactNode
}

function toneClass(tone: ActionTone = 'default') {
  switch (tone) {
    case 'brand':
      return 'border-brand/20 bg-brand text-white hover:bg-brand/90'
    case 'success':
      return 'border-emerald-300/40 bg-emerald-50/70 text-emerald-700 hover:bg-emerald-100/80'
    case 'warning':
      return 'border-amber-300/40 bg-amber-50/70 text-amber-700 hover:bg-amber-100/80'
    case 'danger':
      return 'border-destructive/20 bg-destructive/8 text-destructive hover:bg-destructive/12'
    default:
      return 'border-border/30 text-muted hover:bg-muted/10'
  }
}

function ActionButton({
  item,
  primary = false,
  className,
}: {
  item: ResponsiveActionItem
  primary?: boolean
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={item.onClick}
      disabled={item.disabled}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-2xl border px-3 py-2 text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        primary ? toneClass(item.tone || 'brand') : toneClass(item.tone),
        className
      )}
    >
      {item.icon}
      <span className="whitespace-nowrap">{item.label}</span>
    </button>
  )
}

export function ResponsivePageActions({
  primaryAction,
  secondaryActions = [],
  overflowActions = [],
  mobileVariant = 'stacked',
  className,
}: {
  primaryAction?: ResponsiveActionItem
  secondaryActions?: ResponsiveActionItem[]
  overflowActions?: ResponsiveActionItem[]
  mobileVariant?: 'stacked' | 'compact'
  className?: string
}) {
  const isMobile = useIsMobile()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement | null>(null)

  const desktopActions = useMemo(
    () => [primaryAction, ...secondaryActions, ...overflowActions].filter(Boolean) as ResponsiveActionItem[],
    [primaryAction, secondaryActions, overflowActions]
  )

  useEffect(() => {
    if (!menuOpen) return

    const handlePointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [menuOpen])

  if (!isMobile) {
    return (
      <div className={cn('flex flex-wrap items-start justify-end gap-2', className)}>
        {desktopActions.map((item, index) => (
          <ActionButton key={item.key} item={item} primary={index === 0 && item.key === primaryAction?.key} />
        ))}
      </div>
    )
  }

  if (mobileVariant === 'compact') {
    return (
      <div className={cn('flex flex-wrap items-center gap-2', className)}>
        {primaryAction ? <ActionButton item={primaryAction} primary /> : null}
        {secondaryActions.map((item) => (
          <ActionButton key={item.key} item={item} />
        ))}

        {overflowActions.length > 0 ? (
          <div className="relative shrink-0" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((prev) => !prev)}
              className="inline-flex items-center justify-center gap-1.5 rounded-2xl border border-border/30 px-3 py-2 text-[11px] text-muted transition-colors hover:bg-muted/10"
            >
              更多
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={cn('transition-transform duration-200', menuOpen && 'rotate-180')}
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {menuOpen ? (
              <div className="absolute right-0 top-full z-30 mt-2 min-w-[180px] overflow-hidden rounded-2xl border border-border/20 bg-background/95 p-1.5 shadow-warm backdrop-blur-md">
                {overflowActions.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      setMenuOpen(false)
                      item.onClick()
                    }}
                    disabled={item.disabled}
                    className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[11px] text-primary transition-colors hover:bg-muted/10 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className={cn('w-full space-y-2', className)}>
      {primaryAction ? <ActionButton item={primaryAction} primary className="w-full" /> : null}

      {(secondaryActions.length > 0 || overflowActions.length > 0) && (
        <div className="flex items-center gap-2">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            {secondaryActions.map((item) => (
              <ActionButton key={item.key} item={item} className="min-w-[88px] flex-1" />
            ))}
          </div>

          {overflowActions.length > 0 ? (
            <div className="relative shrink-0" ref={menuRef}>
              <button
                type="button"
                onClick={() => setMenuOpen((prev) => !prev)}
                className="inline-flex items-center justify-center gap-1.5 rounded-2xl border border-border/30 px-3 py-2 text-[11px] text-muted transition-colors hover:bg-muted/10"
              >
                更多
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className={cn('transition-transform duration-200', menuOpen && 'rotate-180')}
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>

              {menuOpen ? (
                <div className="absolute right-0 top-full z-30 mt-2 min-w-[180px] overflow-hidden rounded-2xl border border-border/20 bg-background/95 p-1.5 shadow-warm backdrop-blur-md">
                  {overflowActions.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => {
                        setMenuOpen(false)
                        item.onClick()
                      }}
                      disabled={item.disabled}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[11px] text-primary transition-colors hover:bg-muted/10 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {item.icon}
                      <span>{item.label}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
