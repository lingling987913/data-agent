'use client'

import type { ReactNode } from 'react'
import { bucketBadgeClass, bucketListItemClass, bucketToneClass } from '@/features/unified-review-workbench/utils/bucketTone'
import WorkbenchStatCard from '@/features/unified-review-workbench/components/WorkbenchStatCard'
import type { ConclusionOverviewViewModel } from '@/features/unified-review-workbench/utils/conclusionOverviewModel'
import type { UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'
import type { WorkbenchStatAction } from '@/features/unified-review-workbench/utils/workbenchStatAction'
import {
  resolveSuperAgentStatAction,
  statKeyForBucket,
} from '@/features/unified-review-workbench/utils/workbenchStatAction'

interface Props {
  model: ConclusionOverviewViewModel
  onOpenTab?: (tab: UnifiedWorkbenchTabKey) => void
  onStatAction?: (action: WorkbenchStatAction) => void
  compact?: boolean
  /** 仅展示问题分桶卡片（发现与证据页） */
  bucketsOnly?: boolean
  /** 当前选中的分桶；null 表示全部 */
  activeBucket?: string | null
  /** 点击分桶卡片；传入 null 表示查看全部 */
  onBucketClick?: (bucketKey: string | null) => void
  /** 筛选状态下展示「当前筛选 / 清除筛选」条 */
  showFilterBar?: boolean
  /** 筛选条中的条目数量（默认用分桶统计数） */
  filterCount?: number
}

function ContextSection({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div>
      <div className="text-[10px] font-medium text-muted">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  )
}

function bucketCardActiveClass(isActive: boolean): string {
  return isActive ? 'ring-2 ring-primaryAccent/60 ring-offset-1' : ''
}

export default function ConclusionOverviewPanel({
  model,
  onOpenTab,
  onStatAction,
  compact = false,
  bucketsOnly = false,
  activeBucket = null,
  onBucketClick,
  showFilterBar = false,
  filterCount,
}: Props) {
  const interactiveBuckets = Boolean(onBucketClick) || Boolean(onStatAction)
  const handleStat = onStatAction
    ? (key: Parameters<typeof resolveSuperAgentStatAction>[0]) => {
        const action = resolveSuperAgentStatAction(key)
        if (action && !action.disabled) onStatAction(action)
      }
    : undefined
  const activeCard = activeBucket || null
  const activeCardMeta = activeCard
    ? model.bucketCards.find((card) => card.key === activeCard)
    : null
  const filterDisplayCount = filterCount ?? activeCardMeta?.count ?? 0

  const bucketSection = model.bucketCards.length ? (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[11px] font-medium text-muted">问题分桶</h3>
        {onBucketClick ? (
          <button
            type="button"
            onClick={() => onBucketClick(null)}
            className={`text-[10px] ${
              activeCard ? 'text-primaryAccent hover:underline' : 'text-muted'
            }`}
          >
            全部
          </button>
        ) : null}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {model.bucketCards.map((card) => {
          const isActive = activeCard === card.key
          const className = `rounded-xl border px-3 py-2 text-left transition-shadow ${bucketToneClass(card.key)} ${bucketCardActiveClass(isActive)}`
          if (interactiveBuckets) {
            return (
              <button
                key={card.key}
                type="button"
                aria-pressed={isActive}
                aria-label={`${card.label}：${isActive ? '清除筛选' : '查看明细'}`}
                onClick={() => {
                  if (onBucketClick) {
                    onBucketClick(isActive ? null : card.key)
                    return
                  }
                  const action = resolveSuperAgentStatAction(statKeyForBucket(card.key))
                  if (action) onStatAction?.(action)
                }}
                className={`group ${className} cursor-pointer transition-colors hover:brightness-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primaryAccent`}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="text-[10px] leading-snug">{card.label}</span>
                  <span className="text-[9px] text-primaryAccent/80 opacity-0 transition-opacity group-hover:opacity-100">
                    {isActive ? '清除' : '查看'}
                  </span>
                </div>
                <div className="mt-1 text-lg font-semibold tabular-nums">{card.count}</div>
              </button>
            )
          }
          return (
            <div key={card.key} className={className}>
              <div className="text-[10px] leading-snug">{card.label}</div>
              <div className="mt-1 text-lg font-semibold tabular-nums">{card.count}</div>
            </div>
          )
        })}
      </div>
      {showFilterBar && activeCard && activeCardMeta ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-primaryAccent/25 bg-primaryAccent/5 px-3 py-2 text-[11px]">
          <span className="text-primary">
            当前筛选：{activeCardMeta.label}（{filterDisplayCount}）
          </span>
          <button
            type="button"
            onClick={() => onBucketClick!(null)}
            className="text-primaryAccent hover:underline"
          >
            查看全部 / 清除筛选
          </button>
        </div>
      ) : null}
    </section>
  ) : null

  if (bucketsOnly) {
    return bucketSection ? (
      <div className={`space-y-4 text-[12px] ${compact ? '' : 'max-w-7xl'}`}>
        {bucketSection}
      </div>
    ) : null
  }

  return (
    <div className={`space-y-4 text-[12px] ${compact ? '' : 'max-w-7xl'}`}>
      <section className="rounded-xl border border-border/15 bg-surface px-4 py-3">
        <div className="space-y-3">
          <ContextSection label="审查任务">
            <div className="text-[13px] font-medium text-primary">{model.taskDisplayName}</div>
          </ContextSection>

          {model.reviewSubjectLines.length ? (
            <ContextSection label="审查对象">
              <ul className="space-y-1 text-[11px] leading-relaxed text-primary/90">
                {model.reviewSubjectLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </ContextSection>
          ) : null}

          {model.reviewPlanLines.length ? (
            <ContextSection label="审查方案">
              <ul className="space-y-1 text-[11px] leading-relaxed text-muted">
                {model.reviewPlanLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              {model.documentTypePending ? (
                <p className="mt-2 text-[11px] text-amber-800">文档类型待确认：请勿将未识别类型大量归为证据不足。</p>
              ) : null}
            </ContextSection>
          ) : null}
        </div>

        <div className="mt-4 border-t border-border/10 pt-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-[10px] font-medium text-muted">裁定结论</div>
              {model.verdict ? (
                <div className="mt-1 text-[13px] font-semibold text-primary">
                  {model.verdictLabel || model.verdict}
                </div>
              ) : (
                <div className="mt-1 text-[13px] font-semibold text-primary">待形成结论</div>
              )}
              {model.rationaleDisplay ? (
                <p className="mt-2 text-[11px] leading-relaxed text-muted">{model.rationaleDisplay}</p>
              ) : null}
            </div>
            <div className="shrink-0 rounded-lg border border-primaryAccent/25 bg-primaryAccent/8 px-3 py-2 text-center">
              <div className="text-[10px] text-muted">一句话结论</div>
              <div className="mt-1 max-w-[220px] text-[12px] font-medium text-primary">
                {model.oneLineConclusion || model.headlineVerdict || '待形成结论'}
              </div>
            </div>
          </div>
        </div>
      </section>

      {bucketSection}

      <div className={`grid gap-3 ${compact ? '' : 'lg:grid-cols-2'}`}>
        <section className="rounded-xl border border-border/15 bg-background px-4 py-3">
          <h3 className="text-[11px] font-medium text-muted">优先整改</h3>
          {model.priorityItems.length ? (
            <ul className="mt-2 space-y-2">
              {model.priorityItems.slice(0, 6).map((item) => (
                <li key={item.id} className={`rounded-lg border border-l-4 px-3 py-2 ${bucketListItemClass(item.business_bucket)}`}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <span className="font-medium text-primary">{item.title}</span>
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] ${bucketBadgeClass(item.business_bucket)}`}>
                      {item.business_bucket_label}
                    </span>
                  </div>
                  {item.reason ? <p className="mt-1 text-[11px] text-muted">{item.reason}</p> : null}
                  {item.missing_reason ? (
                    <p className="mt-1 text-[11px] text-sky-800">缺口：{item.missing_reason}</p>
                  ) : null}
                  {item.tab_hint && onOpenTab ? (
                    <button
                      type="button"
                      onClick={() => onOpenTab(item.tab_hint!)}
                      className="mt-2 text-[10px] text-primaryAccent hover:underline"
                    >
                      查看详情
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[11px] text-muted">暂无需要优先整改的项。</p>
          )}
        </section>

        <section className="rounded-xl border border-border/15 bg-background px-4 py-3">
          <h3 className="text-[11px] font-medium text-muted">证据覆盖摘要</h3>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <WorkbenchStatCard
              label="检查项"
              value={model.coverageSummary.totalCheckItems}
              action={handleStat ? resolveSuperAgentStatAction('coverage_check_items') : null}
              onAction={handleStat ? () => handleStat('coverage_check_items') : undefined}
            />
            <WorkbenchStatCard
              label="已印证"
              value={model.coverageSummary.verifiedCount}
              action={handleStat ? resolveSuperAgentStatAction('coverage_verified') : null}
              onAction={handleStat ? () => handleStat('coverage_verified') : undefined}
            />
            <WorkbenchStatCard
              label="证据条数"
              value={model.coverageSummary.evidenceCount}
              action={handleStat ? resolveSuperAgentStatAction('coverage_evidence') : null}
              onAction={handleStat ? () => handleStat('coverage_evidence') : undefined}
            />
            <WorkbenchStatCard
              label="覆盖率"
              value={model.coverageSummary.coverageRateLabel}
              action={handleStat ? resolveSuperAgentStatAction('coverage_rate') : null}
              onAction={handleStat ? () => handleStat('coverage_rate') : undefined}
            />
          </div>
          {model.coverageSummary.documentTypeLabel ? (
            <p className="mt-2 text-[11px] text-amber-800">{model.coverageSummary.documentTypeLabel}</p>
          ) : null}
          {model.coverageSummary.notes.map((note) => (
            <p key={note} className="mt-1 text-[11px] text-muted">{note}</p>
          ))}
        </section>
      </div>

      {onOpenTab && model.drillDownTabs.length ? (
        <section className="flex flex-wrap gap-2">
          {model.drillDownTabs.map((entry) => (
            <button
              key={entry.tab}
              type="button"
              onClick={() => onOpenTab(entry.tab)}
              className="rounded-full border border-border/20 px-3 py-1 text-[10px] text-primaryAccent hover:bg-primaryAccent/5"
            >
              {entry.label}
            </button>
          ))}
        </section>
      ) : null}
    </div>
  )
}
