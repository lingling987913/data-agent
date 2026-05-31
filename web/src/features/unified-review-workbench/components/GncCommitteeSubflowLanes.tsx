'use client'

import {
  buildGncCommitteeSubflowLanes,
  subflowStageStatusLabel,
  summarizeSubflowLane,
  type GncCommitteeSubflowInput,
  type GncSubflowLaneProjection,
  type GncSubflowStageProjection,
  type GncSubflowStageStatus,
} from '@/features/unified-review-workbench/utils/gncCommitteeSubFlows'
import { resolveVerdictLabel } from '@/features/unified-review-workbench/utils/zhWorkbenchText'
import { useOptionalGncWorkbenchLink } from '@/features/unified-review-workbench/components/GncWorkbenchLinkContext'
import type { UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

const STAGE_STATUS_STYLES: Record<GncSubflowStageStatus, string> = {
  completed: 'border-emerald-500/30 bg-emerald-500/5 text-emerald-700',
  running: 'border-primaryAccent/40 bg-primaryAccent/10 text-primaryAccent',
  failed: 'border-destructive/30 bg-destructive/5 text-destructive',
  blocked: 'border-amber-500/30 bg-amber-500/10 text-amber-800',
  not_checked: 'border-border/20 bg-surface text-muted',
  skipped: 'border-border/15 bg-background text-muted',
  pending: 'border-border/15 bg-background text-muted',
}

function SubflowStageChip({
  lane,
  stage,
  highlighted,
  onOpenCommittee,
}: {
  lane: GncSubflowLaneProjection
  stage: GncSubflowStageProjection
  highlighted?: boolean
  onOpenCommittee?: (lane: GncSubflowLaneProjection, stage: GncSubflowStageProjection) => void
}) {
  const clickable = Boolean(onOpenCommittee) && stage.status !== 'skipped'
  const highlightClass = highlighted ? 'ring-1 ring-primaryAccent/40 border-primaryAccent/40' : ''

  const content = (
    <>
      <div className="flex flex-wrap items-center justify-between gap-1">
        <span className="font-medium text-primary">{stage.stageLabel}</span>
        <span className={`rounded-full border px-1.5 py-0.5 text-[9px] ${STAGE_STATUS_STYLES[stage.status]}`}>
          {subflowStageStatusLabel(stage.status)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-2 text-[9px] text-muted">
        <span>规则 {stage.ruleJudgmentCount}</span>
        <span>发现 {stage.findingCount}</span>
        {stage.blockingFlags.length ? <span className="text-destructive">阻塞 {stage.blockingFlags.length}</span> : null}
      </div>
      {stage.skipReason ? (
        <p className="mt-1 text-[9px] text-muted">{stage.skipReason}</p>
      ) : stage.summary ? (
        <p className="mt-1 line-clamp-2 text-[9px] leading-relaxed text-muted">{stage.summary}</p>
      ) : null}
    </>
  )

  if (!clickable) {
    return (
      <div className={`rounded-lg border px-2 py-1.5 text-[10px] ${STAGE_STATUS_STYLES[stage.status]} ${highlightClass}`}>
        {content}
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={() => onOpenCommittee?.(lane, stage)}
      className={`w-full rounded-lg border px-2 py-1.5 text-left text-[10px] transition-colors hover:border-primaryAccent/40 hover:bg-primaryAccent/5 ${STAGE_STATUS_STYLES[stage.status]} ${highlightClass}`}
    >
      {content}
    </button>
  )
}

function SubflowLaneCard({
  lane,
  committeeStepRunning,
  onOpenTab,
  stayOnCurrentTab,
}: {
  lane: GncSubflowLaneProjection
  committeeStepRunning?: boolean
  onOpenTab?: (tab: UnifiedWorkbenchTabKey) => void
  stayOnCurrentTab?: boolean
}) {
  const link = useOptionalGncWorkbenchLink()
  const selectedGroupKey = link?.selectedCommitteeGroupKey || ''
  const selectedStageKey = link?.selectedCommitteeStageKey || ''
  const selectedUnitKey = link?.selectedCommitteeUnitKey || ''
  const laneHighlighted = selectedGroupKey === lane.groupKey && !selectedStageKey && !selectedUnitKey

  const handleOpenCommittee = (_lane: GncSubflowLaneProjection, stage: GncSubflowStageProjection) => {
    link?.setSelectedCommitteeGroupKey(lane.groupKey)
    link?.setSelectedCommitteeStageKey(stage.stageKey)
    link?.setSelectedCommitteeUnitKey(stage.unitKey)
    if (onOpenTab) {
      onOpenTab('committee')
    } else {
      link?.openLinkedTab('committee')
    }
  }

  return (
    <section
      className={`rounded-xl border p-3 ${
        laneHighlighted
          ? 'border-primaryAccent/40 bg-primaryAccent/5 ring-1 ring-primaryAccent/20'
          : lane.enabled
            ? committeeStepRunning
              ? 'border-primaryAccent/25 bg-primaryAccent/5'
              : 'border-border/15 bg-background'
            : 'border-border/10 bg-surface/50 opacity-90'
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="text-[11px] font-semibold text-primary">{lane.groupLabel}</h4>
          <p className="mt-0.5 text-[10px] text-muted">{summarizeSubflowLane(lane)}</p>
          {!lane.enabled && lane.skipReason ? (
            <p className="mt-1 text-[10px] text-muted">{lane.skipReason}</p>
          ) : null}
          {lane.verdict ? (
            <p className="mt-1 text-[10px] text-primary">结论：{resolveVerdictLabel(lane.verdict)}</p>
          ) : null}
        </div>
        {lane.blockingFlags.length ? (
          <span className="rounded-full border border-destructive/25 px-2 py-0.5 text-[10px] text-destructive">
            {lane.blockingFlags.length} 阻塞标记
          </span>
        ) : null}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {lane.stages.map((stage) => (
          <SubflowStageChip
            key={`${lane.groupKey}-${stage.stageKey}`}
            lane={lane}
            stage={stage}
            highlighted={
              selectedGroupKey === lane.groupKey
              && (selectedStageKey === stage.stageKey || selectedUnitKey === stage.unitKey)
            }
            onOpenCommittee={lane.enabled ? handleOpenCommittee : undefined}
          />
        ))}
      </div>

      {lane.enabled && onOpenTab && !stayOnCurrentTab ? (
        <button
          type="button"
          onClick={() => {
            link?.setSelectedCommitteeGroupKey(lane.groupKey)
            link?.setSelectedCommitteeStageKey('')
            link?.setSelectedCommitteeUnitKey('')
            onOpenTab('committee')
          }}
          className="mt-2 text-[10px] font-medium text-primaryAccent hover:underline"
        >
          在 Committee Tab 查看 {lane.groupLabel}
        </button>
      ) : null}
    </section>
  )
}

function SubflowLanesHeader({ reviewScope }: { reviewScope?: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="text-[11px] font-semibold text-primary">AD / AC 嵌套子流程</h4>
      {reviewScope ? (
        <span className="text-[10px] text-muted">scope={reviewScope}</span>
      ) : null}
    </div>
  )
}

export function GncCommitteeSubflowLanes({
  committee,
  committeeStepRunning,
  onOpenTab,
  loading,
  error,
  stayOnCurrentTab,
}: {
  committee: GncCommitteeSubflowInput | null | undefined
  committeeStepRunning?: boolean
  onOpenTab?: (tab: UnifiedWorkbenchTabKey) => void
  loading?: boolean
  error?: string
  stayOnCurrentTab?: boolean
}) {
  const lanes = buildGncCommitteeSubflowLanes(committee)

  if (loading) {
    return (
      <div className="space-y-3">
        <SubflowLanesHeader reviewScope={committee?.review_scope} />
        <p className="text-[10px] text-muted">加载专家组子流程…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-3">
        <SubflowLanesHeader reviewScope={committee?.review_scope} />
        <p className="text-[10px] text-destructive">{error}</p>
      </div>
    )
  }

  if (!lanes.length) {
    return (
      <div className="space-y-3">
        <SubflowLanesHeader reviewScope={committee?.review_scope} />
        <p className="text-[10px] text-muted">暂无专家组子流程数据</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <SubflowLanesHeader reviewScope={committee?.review_scope} />
      <div className="grid gap-3 xl:grid-cols-2">
        {lanes.map((lane) => (
          <SubflowLaneCard
            key={lane.groupKey}
            lane={lane}
            committeeStepRunning={committeeStepRunning}
            onOpenTab={onOpenTab}
            stayOnCurrentTab={stayOnCurrentTab}
          />
        ))}
      </div>
    </div>
  )
}

export default GncCommitteeSubflowLanes
