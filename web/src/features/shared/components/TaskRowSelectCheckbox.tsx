'use client'

export function TaskRowSelectCheckbox({
  checked,
  onToggle,
  label,
}: {
  checked: boolean
  onToggle: () => void
  label: string
}) {
  return (
    <label
      className="flex shrink-0 items-center px-2"
      onClick={(e) => e.stopPropagation()}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => {
          e.stopPropagation()
          onToggle()
        }}
        aria-label={label}
        data-testid="task-row-select"
        className="size-3.5 rounded border-border/40 accent-brand"
      />
    </label>
  )
}
