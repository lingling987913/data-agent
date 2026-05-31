'use client'

import {
  arbitrationStatusLabel,
  arbitrationStatusTone,
  formatConflictItem,
  formatGncDisplayListItem,
  formatGncVerdictLabel,
  type GncArbitrationDisplayStatus,
  type GncDisplayListItem,
  type GncParsedDecision,
} from '@/features/unified-review-workbench/utils/gncRichPanels'

function StringListSection({
  title,
  items,
  emptyHint,
}: {
  title: string
  items: string[]
  emptyHint?: string
}) {
  if (!items.length) {
    return emptyHint ? (
      <section className="rounded-xl border border-border/15 bg-background p-3">
        <div className="text-[10px] font-medium text-muted">{title}</div>
        <p className="mt-1 text-[10px] text-muted">{emptyHint}</p>
      </section>
    ) : null
  }
  return (
    <section className="rounded-xl border border-border/15 bg-background p-3">
      <div className="text-[10px] font-medium text-muted">{title}</div>
      <ul className="mt-2 space-y-1">
        {items.map((item) => (
          <li key={item} className="text-[10px] leading-relaxed text-primary">• {item}</li>
        ))}
      </ul>
    </section>
  )
}

function ObjectListSection({
  title,
  items,
  emptyHint,
}: {
  title: string
  items: GncDisplayListItem[]
  emptyHint?: string
}) {
  if (!items.length) {
    return emptyHint ? (
      <section className="rounded-xl border border-border/15 bg-background p-3">
        <div className="text-[10px] font-medium text-muted">{title}</div>
        <p className="mt-1 text-[10px] text-muted">{emptyHint}</p>
      </section>
    ) : null
  }
  return (
    <section className="rounded-xl border border-border/15 bg-background p-3">
      <div className="text-[10px] font-medium text-muted">{title}</div>
      <ul className="mt-2 space-y-2">
        {items.map((item, index) => {
          const formatted = formatGncDisplayListItem(item)
          return (
            <li key={`${formatted.title}-${index}`} className="rounded-lg border border-border/10 px-2 py-1.5">
              <div className="font-medium text-primary">{formatted.title}</div>
              {formatted.detail ? (
                <p className="mt-0.5 text-[10px] text-muted">{formatted.detail}</p>
              ) : null}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function ConflictSection({
  title,
  items,
}: {
  title: string
  items: Array<Record<string, unknown> | string>
}) {
  if (!items.length) return null
  return (
    <section className="rounded-xl border border-border/15 bg-background p-3">
      <div className="text-[10px] font-medium text-muted">{title}</div>
      <ul className="mt-2 space-y-2">
        {items.map((item, index) => {
          const formatted = formatConflictItem(item)
          return (
            <li key={`${formatted.title}-${index}`} className="rounded-lg border border-border/10 px-2 py-1.5">
              <div className="font-medium text-primary">{formatted.title}</div>
              {formatted.detail ? (
                <p className="mt-0.5 text-[10px] text-muted">{formatted.detail}</p>
              ) : null}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export function GncDecisionPanel({
  decision,
  arbitrationStatus,
  showArbitrationBadge = true,
}: {
  decision: GncParsedDecision
  arbitrationStatus: GncArbitrationDisplayStatus
  showArbitrationBadge?: boolean
}) {
  const expertItems = decision.expertConflicts.length
    ? decision.expertConflicts
    : decision.conflictAnalysis

  return (
    <div className="space-y-3 text-[11px]">
      {showArbitrationBadge ? (
        <div className={`inline-flex rounded-full border px-2.5 py-0.5 text-[10px] font-medium ${arbitrationStatusTone(arbitrationStatus)}`}>
          {arbitrationStatusLabel(arbitrationStatus)}
          {decision.requiresArbitration && arbitrationStatus === 'pending' ? ' · 需人工确认' : ''}
        </div>
      ) : null}

      <section className="rounded-xl border border-primaryAccent/20 bg-primaryAccent/5 px-4 py-3">
        <div className="text-[10px] font-medium text-muted">总师结论</div>
        <div className="mt-1 text-[14px] font-semibold text-primary">
          {formatGncVerdictLabel(decision.verdict)}
        </div>
        {decision.rationale ? (
          <p className="mt-2 leading-relaxed text-muted">{decision.rationale}</p>
        ) : (
          <p className="mt-2 text-[10px] text-muted">暂无裁定说明</p>
        )}
      </section>

      <div className="grid gap-3 sm:grid-cols-2">
        <section className="rounded-xl border border-border/15 bg-background p-3">
          <div className="text-[10px] font-medium text-muted">release_decision</div>
          <div className="mt-1 font-medium text-primary">
            {formatGncVerdictLabel(decision.releaseDecision)}
          </div>
        </section>
        <section className="rounded-xl border border-border/15 bg-background p-3">
          <div className="text-[10px] font-medium text-muted">requires_arbitration</div>
          <div className="mt-1 font-medium text-primary">
            {decision.requiresArbitration ? '是' : '否'}
          </div>
        </section>
      </div>

      <ObjectListSection
        title="arbitration_items"
        items={decision.arbitrationItems}
        emptyHint="暂无待仲裁项"
      />
      <ConflictSection title="expert_conflicts / conflict_analysis" items={expertItems} />
      <ObjectListSection
        title="conflict_resolutions"
        items={decision.conflictResolutions}
        emptyHint="暂无冲突裁决建议"
      />
      <StringListSection
        title="风险类别 (key_risks)"
        items={decision.keyRisks}
        emptyHint="未标注关键风险类别"
      />
    </div>
  )
}

export default GncDecisionPanel
