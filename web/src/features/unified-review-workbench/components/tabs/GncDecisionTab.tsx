'use client'

import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import { GncDecisionPanel } from '@/features/unified-review-workbench/components/tabs/GncDecisionPanel'
import {
  hasGncDecisionContent,
  parseGncDecision,
  resolveGncArbitrationDisplayStatus,
} from '@/features/unified-review-workbench/utils/gncRichPanels'
import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'

export function GncDecisionTab({
  reviewId,
  enabled,
  detail,
}: {
  reviewId: string
  enabled: boolean
  detail: UnifiedReviewWorkbenchDetail
}) {
  const { data, loading, error } = useGncResource<Record<string, unknown>>(reviewId, 'decision', enabled)

  if (loading) return <p className="text-[11px] text-muted">加载总师裁定…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>

  const parsed = parseGncDecision(data)
  const arbitrationStatus = resolveGncArbitrationDisplayStatus({
    arbitrationStatus: detail.summary.arbitration_status,
    requiresArbitration: detail.metrics.requires_arbitration || parsed.requiresArbitration,
    workbenchPhase: detail.workbench_phase,
  })

  if (!hasGncDecisionContent(parsed)) {
    return (
      <div className="rounded-xl border border-dashed border-border/20 px-4 py-8 text-center text-[11px]">
        <p className="font-medium text-primary">总师裁定尚未产出</p>
        <p className="mt-2 text-muted">chief_adjudication 步骤完成后将展示结构化结论。</p>
      </div>
    )
  }

  return (
    <GncDecisionPanel
      decision={parsed}
      arbitrationStatus={arbitrationStatus}
    />
  )
}

export default GncDecisionTab
