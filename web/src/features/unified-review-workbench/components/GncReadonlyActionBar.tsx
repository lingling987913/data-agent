'use client'

interface ActionItem {
  id: string
  label: string
  hint: string
  available?: boolean
  href?: string
}

export function GncReadonlyActionBar({ actions }: { actions: ActionItem[] }) {
  return (
    <section className="rounded-xl border border-border/15 bg-surface p-3 text-[11px]">
      <div className="text-[10px] font-medium text-muted">材料与门禁操作</div>
      <p className="mt-1 text-[10px] leading-relaxed text-muted">
        统一工作台当前为只读聚合视图；下列操作为占位入口，避免误触无效 API。
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {actions.map((action) => {
          const disabled = !action.available
          const className = `rounded-lg border px-3 py-1.5 text-[10px] ${
            disabled
              ? 'cursor-not-allowed border-border/15 bg-background text-muted'
              : 'border-primaryAccent/30 bg-primaryAccent/10 text-primaryAccent hover:underline'
          }`
          if (action.available && action.href) {
            return (
              <a key={action.id} href={action.href} className={className}>
                {action.label}
              </a>
            )
          }
          return (
            <button
              key={action.id}
              type="button"
              disabled={disabled}
              title={action.hint}
              className={className}
            >
              {action.label}
            </button>
          )
        })}
      </div>
      <ul className="mt-2 space-y-0.5 text-[10px] text-muted">
        {actions.map((action) => (
          <li key={`${action.id}-hint`}>• {action.label}：{action.hint}</li>
        ))}
      </ul>
    </section>
  )
}

export default GncReadonlyActionBar
