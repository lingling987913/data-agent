'use client'

import { useState } from 'react'
import { patchGncRidItem } from '@/features/unified-review-workbench/api'
import { useOptionalGncWorkbenchLink } from '@/features/unified-review-workbench/components/GncWorkbenchLinkContext'
import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import {
  collectRelatedEvidenceIds,
  extractRidContext,
} from '@/features/unified-review-workbench/utils/gncWorkbenchLinks'

const PRIOR_CYCLE_LABELS: Record<string, string> = {
  new: '本轮新增',
  continued: '延续项',
  claimed_resolved_still_open: '声称已闭环但仍开放',
}

function RidContextBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-border/15 bg-surface px-1.5 py-0.5 text-[10px]">
      <span className="text-muted">{label}</span>
      <span className="font-medium text-primary">{value}</span>
    </span>
  )
}

export function GncRidTab({ reviewId, enabled }: { reviewId: string; enabled: boolean }) {
  const link = useOptionalGncWorkbenchLink()
  const { data, loading, error, reload } = useGncResource<Array<Record<string, unknown>>>(reviewId, 'rid_items', enabled)
  const [busyId, setBusyId] = useState('')

  const patchStatus = async (ridId: string, status: string) => {
    setBusyId(ridId)
    try {
      await patchGncRidItem(reviewId, ridId, { status })
      await reload()
    } finally {
      setBusyId('')
    }
  }

  if (loading) return <p className="text-[11px] text-muted">加载 RID…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>
  const items = Array.isArray(data) ? data : []
  if (!items.length) return <p className="text-[11px] text-muted">暂无 RID</p>

  return (
    <ul className="space-y-2">
      {items.map((item) => {
        const ridId = String(item.rid_id || '')
        const isSelected = link?.selectedRidId === ridId
        const relatedFindings = Array.isArray(item.related_finding_ids) ? item.related_finding_ids : []
        const relatedEvidences = collectRelatedEvidenceIds(item)
        const priorStatus = String(item.prior_cycle_status || '')
        const context = extractRidContext(item)
        const hasContext = Boolean(context.ruleId || context.unitKey || context.sectionId || context.reviewItemId)

        return (
          <li
            key={ridId}
            className={`rounded-lg border px-3 py-2 text-[11px] ${
              isSelected ? 'border-primaryAccent/40 bg-primaryAccent/5' : 'border-border/15'
            }`}
          >
            <button
              type="button"
              className="w-full text-left"
              onClick={() => link?.setSelectedRidId(ridId)}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-primary">{ridId}</span>
                {item.severity ? (
                  <span className="rounded border border-border/20 px-1.5 py-0.5 text-[10px] text-muted">
                    {String(item.severity)}
                  </span>
                ) : null}
                {priorStatus ? (
                  <span className="rounded border border-amber-500/25 px-1.5 py-0.5 text-[10px] text-amber-700">
                    {PRIOR_CYCLE_LABELS[priorStatus] || priorStatus}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-muted">{String(item.description || '')}</p>
            </button>

            {hasContext ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {context.ruleId ? (
                  <button
                    type="button"
                    onClick={() => link?.openLinkedTab('committee')}
                  >
                    <RidContextBadge label="规则" value={context.ruleId} />
                  </button>
                ) : null}
                {context.unitKey ? <RidContextBadge label="单元" value={context.unitKey} /> : null}
                {context.sectionId ? <RidContextBadge label="章节" value={context.sectionId} /> : null}
                {context.reviewItemId ? <RidContextBadge label="审查项" value={context.reviewItemId} /> : null}
              </div>
            ) : null}

            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-muted">状态：{String(item.status || 'open')}</span>
              {relatedFindings.length ? (
                <button
                  type="button"
                  onClick={() => {
                    link?.setSelectedRidId(ridId)
                    link?.setSelectedFindingId(String(relatedFindings[0]))
                    link?.openLinkedTab('findings')
                  }}
                  className="text-[10px] text-primaryAccent hover:underline"
                >
                  关联发现 {relatedFindings.length}
                </button>
              ) : null}
              {relatedEvidences.length ? (
                <button
                  type="button"
                  onClick={() => {
                    link?.setSelectedRidId(ridId)
                    link?.setSelectedEvidenceId(String(relatedEvidences[0]))
                    link?.openLinkedTab('evidences')
                  }}
                  className="text-[10px] text-primaryAccent hover:underline"
                >
                  关联证据 {relatedEvidences.length}
                </button>
              ) : null}
              {item.status !== 'closed' ? (
                <button
                  type="button"
                  disabled={busyId === ridId}
                  onClick={() => void patchStatus(ridId, 'closed')}
                  className="rounded-lg border border-border/20 px-2 py-0.5 text-[10px] hover:border-brand/40 disabled:opacity-50"
                >
                  标记闭环
                </button>
              ) : null}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export default GncRidTab
