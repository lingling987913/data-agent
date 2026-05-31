'use client'

import { useState } from 'react'
import { submitGncArbitration } from '@/features/unified-review-workbench/api'
import { GncDecisionPanel } from '@/features/unified-review-workbench/components/tabs/GncDecisionPanel'
import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import {
  extractGncArbitrationConflictIds,
  hasGncDecisionContent,
  parseGncDecision,
  resolveGncArbitrationDisplayStatus,
} from '@/features/unified-review-workbench/utils/gncRichPanels'
import ConclusionOverviewPanel from '@/features/unified-review-workbench/components/ConclusionOverviewPanel'
import { buildConclusionOverviewFromDetail } from '@/features/unified-review-workbench/utils/conclusionOverviewModel'
import type { UnifiedReviewWorkbenchDetail, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export function GncOverviewTab({
  detail,
  onOpenTab,
}: {
  detail: UnifiedReviewWorkbenchDetail
  onOpenTab?: (tab: UnifiedWorkbenchTabKey) => void
}) {
  const model = buildConclusionOverviewFromDetail(detail, 'gnc')
  return (
    <div className="space-y-4 text-[12px]">
      <ConclusionOverviewPanel model={model} onOpenTab={onOpenTab} />
      {detail.error ? (
        <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-[11px] text-destructive">
          {detail.error}
        </div>
      ) : null}
    </div>
  )
}

export function GncListTab({
  reviewId,
  resource,
  enabled,
  idKey = 'finding_id',
}: {
  reviewId: string
  resource: string
  enabled: boolean
  idKey?: string
}) {
  const { data, loading, error } = useGncResource<Array<Record<string, unknown>>>(reviewId, resource, enabled)
  if (loading) return <p className="text-[11px] text-muted">加载中…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>
  const items = Array.isArray(data) ? data : []
  if (!items.length) return <p className="text-[11px] text-muted">暂无数据</p>
  return (
    <ul className="space-y-2">
      {items.map((item, index) => (
        <li key={String(item[idKey] || index)} className="rounded-lg border border-border/15 px-3 py-2 text-[11px]">
          <div className="font-medium text-primary">{String(item.title || item.description || item[idKey] || '项')}</div>
          {item.severity ? <div className="mt-1 text-muted">严重度：{String(item.severity)}</div> : null}
          {item.status ? <div className="mt-0.5 text-muted">状态：{String(item.status)}</div> : null}
        </li>
      ))}
    </ul>
  )
}

export function GncArbitrationTab({
  reviewId,
  detail,
  enabled,
  onDetailRefresh,
}: {
  reviewId: string
  detail: UnifiedReviewWorkbenchDetail
  enabled: boolean
  onDetailRefresh: () => void
}) {
  const { data, loading, error, reload } = useGncResource<Record<string, unknown>>(reviewId, 'decision', enabled)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async () => {
    setSubmitting(true)
    try {
      const rawItems = Array.isArray((data as { arbitration_items?: unknown })?.arbitration_items)
        ? (data as { arbitration_items: Array<unknown> }).arbitration_items
        : []
      const conflictIds = extractGncArbitrationConflictIds(rawItems)
      if (!conflictIds.length) {
        alert('暂无有效仲裁项（需 conflict_id / conflict_key），无法提交')
        return
      }
      await submitGncArbitration(reviewId, {
        status: 'resolved',
        decisions: conflictIds.map((conflictId) => ({
          conflict_id: conflictId,
          resolution: 'confirmed',
        })),
        notes,
      })
      await reload()
      onDetailRefresh()
    } catch (err) {
      alert(err instanceof Error ? err.message : '提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <p className="text-[11px] text-muted">加载仲裁信息…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>

  const parsed = parseGncDecision(data)
  const arbitrationStatus = resolveGncArbitrationDisplayStatus({
    arbitrationStatus: detail.summary.arbitration_status,
    requiresArbitration: detail.metrics.requires_arbitration || parsed.requiresArbitration,
    workbenchPhase: detail.workbench_phase,
  })
  const canSubmit = detail.workbench_phase === 'arbitration' && arbitrationStatus === 'pending'
  const rawArbitrationItems = Array.isArray((data as { arbitration_items?: unknown })?.arbitration_items)
    ? (data as { arbitration_items: Array<unknown> }).arbitration_items
    : []
  const arbitrationConflictIds = extractGncArbitrationConflictIds(rawArbitrationItems)

  if (!hasGncDecisionContent(parsed)) {
    return (
      <div className="rounded-xl border border-dashed border-border/20 px-4 py-8 text-center text-[11px]">
        <p className="font-medium text-primary">总师裁定尚未产出</p>
        <p className="mt-2 text-muted">chief_adjudication 步骤完成后将展示结构化结论与仲裁项。</p>
      </div>
    )
  }

  return (
    <div className="space-y-3 text-[11px]">
      <GncDecisionPanel decision={parsed} arbitrationStatus={arbitrationStatus} />
      {canSubmit ? (
        <div className="space-y-2 rounded-xl border border-border/15 p-3">
          <label className="block text-[10px] font-medium text-muted">仲裁说明</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="min-h-[72px] w-full rounded-lg border border-border/20 bg-background px-2 py-1.5 text-[11px]"
          />
          <button
            type="button"
            disabled={submitting || !arbitrationConflictIds.length}
            onClick={() => void submit()}
            className="rounded-lg bg-brand px-3 py-1.5 text-[11px] text-white disabled:opacity-50"
          >
            提交仲裁结论
          </button>
          {!arbitrationConflictIds.length ? (
            <p className="text-[10px] text-muted">暂无有效仲裁项（需 conflict_id / conflict_key），无法提交。</p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function GncEventsTab({ reviewId, enabled }: { reviewId: string; enabled: boolean }) {
  const { data, loading, error } = useGncResource<Array<Record<string, unknown>>>(reviewId, 'events', enabled)
  if (loading) return <p className="text-[11px] text-muted">加载事件…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>
  const events = Array.isArray(data) ? data : []
  return (
    <ul className="max-h-[480px] space-y-1 overflow-auto">
      {events.map((event, index) => (
        <li key={String(event.sequence || index)} className="rounded border border-border/10 px-2 py-1 text-[10px]">
          <span className="font-medium text-primary">{String(event.type || 'event')}</span>
          <span className="ml-2 text-muted">#{String(event.sequence || '')}</span>
        </li>
      ))}
    </ul>
  )
}

export { GncFlowTab } from '@/features/unified-review-workbench/components/tabs/GncFlowTab'
export { GncMaterialsTab } from '@/features/unified-review-workbench/components/tabs/GncMaterialsTab'
export { GncCommitteeTab } from '@/features/unified-review-workbench/components/tabs/GncCommitteeTab'
export { GncEvidencesTab } from '@/features/unified-review-workbench/components/tabs/GncEvidencesTab'
export { GncRidTab } from '@/features/unified-review-workbench/components/tabs/GncRidTab'
export { GncFindingsTab } from '@/features/unified-review-workbench/components/tabs/GncFindingsTab'
export { GncMinutesTab } from '@/features/unified-review-workbench/components/tabs/GncMinutesTab'
export { GncDecisionTab } from '@/features/unified-review-workbench/components/tabs/GncDecisionTab'
export { GncReportTab } from '@/features/unified-review-workbench/components/tabs/GncReportTab'
