'use client'

import { Loader2, Trash2 } from 'lucide-react'

export function TaskRowDeleteButton({
  deleting = false,
  disabled = false,
  disabledTitle,
  onDelete,
  className = '',
}: {
  deleting?: boolean
  disabled?: boolean
  disabledTitle?: string
  onDelete: () => void
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        onDelete()
      }}
      disabled={disabled || deleting}
      title={disabled ? disabledTitle : '删除任务'}
      aria-label="删除任务"
      data-testid="task-row-delete"
      className={[
        'flex size-9 items-center justify-center rounded-lg text-muted/55 transition-colors duration-200',
        'hover:bg-destructive/8 hover:text-destructive',
        'focus-visible:outline-none focus-visible:border focus-visible:border-brand/40',
        'disabled:cursor-not-allowed disabled:opacity-40',
        className,
      ].join(' ')}
    >
      {deleting ? (
        <Loader2 className="size-3.5 motion-safe:animate-spin" aria-hidden />
      ) : (
        <Trash2 className="size-3.5" strokeWidth={1.75} aria-hidden />
      )}
    </button>
  )
}
