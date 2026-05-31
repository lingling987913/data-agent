'use client'

export function TaskListBatchBar({
  allSelected,
  selectionSummary,
  batchActionLabel,
  batchDeleting,
  hasSelection,
  includeProtectedDelete,
  onToggleSelectAll,
  onIncludeProtectedChange,
  onBatchDelete,
  forceDeleteLabel = '含执行中任务也彻底删除',
}: {
  allSelected: boolean
  selectionSummary: string
  batchActionLabel: string
  batchDeleting: boolean
  hasSelection: boolean
  includeProtectedDelete: boolean
  onToggleSelectAll: () => void
  onIncludeProtectedChange: (checked: boolean) => void
  onBatchDelete: () => void
  forceDeleteLabel?: string
}) {
  return (
    <div
      className="mb-3 flex flex-col gap-2 rounded-xl border border-border/15 bg-surface/80 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"
      data-testid="task-list-batch-bar"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[11px] text-muted">
        <label className="inline-flex min-h-9 items-center gap-2 text-primary">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={onToggleSelectAll}
            className="size-3.5 rounded border-border/40 accent-brand"
            aria-label="全选任务"
            data-testid="task-batch-select-all"
          />
          <span>全选</span>
        </label>
        <span className="text-muted/70">{selectionSummary}</span>
        {hasSelection ? (
          <label className="inline-flex min-h-9 items-center gap-2 text-muted/80">
            <input
              type="checkbox"
              checked={includeProtectedDelete}
              onChange={(e) => onIncludeProtectedChange(e.target.checked)}
              className="size-3.5 rounded border-border/40 accent-brand"
              aria-label={forceDeleteLabel}
              data-testid="task-batch-include-protected"
            />
            <span>{forceDeleteLabel}</span>
          </label>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onBatchDelete}
        disabled={!hasSelection || batchDeleting}
        className="inline-flex min-h-9 shrink-0 items-center justify-center rounded-xl border border-destructive/20 px-3 text-[11px] font-medium text-destructive transition-colors hover:bg-destructive/8 disabled:cursor-not-allowed disabled:opacity-40"
        data-testid="task-batch-delete"
      >
        {batchActionLabel}
      </button>
    </div>
  )
}
