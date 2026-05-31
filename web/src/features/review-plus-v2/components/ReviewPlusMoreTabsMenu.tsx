'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'
import type { ReviewPlusWorkbenchTabKey } from '@/features/review-plus-v2/utils/reviewPlusPipeline'

type TabItem = [ReviewPlusWorkbenchTabKey, string, boolean?]

interface Props {
  items: TabItem[]
  activeTab: ReviewPlusWorkbenchTabKey
  onSelect: (tab: ReviewPlusWorkbenchTabKey) => void
}

export default function ReviewPlusMoreTabsMenu({ items, activeTab, onSelect }: Props) {
  const [open, setOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0, minWidth: 160 })
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const hasActiveSecondary = items.some(([key]) => key === activeTab)

  useEffect(() => { setMounted(true) }, [])

  const updateMenuPosition = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const minWidth = Math.max(rect.width, 168)
    let left = rect.left
    if (left + minWidth > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - minWidth - 8)
    }
    setMenuPosition({
      top: rect.bottom + 4,
      left,
      minWidth,
    })
  }, [])

  useEffect(() => {
    if (!open) return
    updateMenuPosition()

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return
      setOpen(false)
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }

    const handleLayout = () => updateMenuPosition()

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    window.addEventListener('resize', handleLayout)
    window.addEventListener('scroll', handleLayout, true)

    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('resize', handleLayout)
      window.removeEventListener('scroll', handleLayout, true)
    }
  }, [open, updateMenuPosition])

  const handleSelect = (tab: ReviewPlusWorkbenchTabKey) => {
    setOpen(false)
    onSelect(tab)
  }

  const menu = open && mounted ? createPortal(
    <div
      ref={menuRef}
      className="fixed z-[120] overflow-hidden rounded-2xl border border-border/20 bg-background/95 p-1.5 shadow-warm backdrop-blur-md"
      style={{
        top: menuPosition.top,
        left: menuPosition.left,
        minWidth: menuPosition.minWidth,
      }}
      role="menu"
      data-testid="review-plus-v2-tab-more-menu"
    >
      {items.map(([key, label]) => (
        <button
          key={key}
          type="button"
          role="menuitem"
          onClick={() => handleSelect(key)}
          className={cn(
            'flex w-full rounded-xl px-3 py-2 text-left text-[11px] transition-colors hover:bg-surface',
            activeTab === key ? 'font-medium text-primaryAccent' : 'text-primary',
          )}
          data-testid={`review-plus-v2-tab-${key}`}
        >
          {label}
        </button>
      ))}
    </div>,
    document.body,
  ) : null

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          setOpen((prev) => !prev)
        }}
        className={cn(
          'relative inline-flex shrink-0 items-center gap-1 px-3.5 py-2 text-[11px] font-medium transition-colors',
          hasActiveSecondary || open
            ? 'border-b-2 border-primaryAccent text-primaryAccent'
            : 'text-muted/60 hover:text-primary',
        )}
        data-testid="review-plus-v2-tab-more"
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
          aria-hidden
          className={cn('transition-transform duration-200 motion-safe:transition-transform', open && 'rotate-180')}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {menu}
    </>
  )
}
