'use client'

import { useMemo, useState } from 'react'
import {
  formatDurationMs,
  resolveGncStepLabel,
  type GncFlowProjection,
  type GncFlowStepProjection,
} from '@/features/unified-review-workbench/constants/gncWorkflowSteps'
import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import { buildGncFlowStepDetail, canOpenRelatedTab } from '@/features/unified-review-workbench/utils/gncFlowStepDetail'
import {
  aggregateGncFlowStages,
  formatStageDuration,
  resolveGncFlowCurrentStageLabel,
  type GncFlowStageProjection,
} from '@/features/unified-review-workbench/utils/gncFlowStages'
import type { GncCommitteeSubflowInput } from '@/features/unified-review-workbench/utils/gncCommitteeSubFlows'
import { GncCommitteeSubflowLanes } from '@/features/unified-review-workbench/components/GncCommitteeSubflowLanes'
import type { UnifiedReviewWorkbenchDetail, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

const STATUS_STYLES: Record<string, string> = {
  completed: 'border-emerald-500/30 bg-emerald-500/5 text-emerald-700',
  running: 'border-primaryAccent/40 bg-primaryAccent/10 text-primaryAccent',
  failed: 'border-destructive/30 bg-destructive/5 text-destructive',
  pending: 'border-border/15 bg-background text-muted',
}

function StepStatusBadge({ status }: { status: string }) {
  const label = status === 'completed'
    ? '已完成'
    : status === 'running'
      ? '进行中'
      : status === 'failed'
        ? '失败'
        : '待执行'
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_STYLES[status] || STATUS_STYLES.pending}`}>
      {label}
    </span>
  )
}

function GncFlowStepDetailPanel({
  detail,
  visibleTabs,
  onOpenTab,
  onClose,
}: {
  detail: ReturnType<typeof buildGncFlowStepDetail>
  visibleTabs: readonly string[]
  onOpenTab?: (tab: UnifiedWorkbenchTabKey) => void
  onClose: () => void
}) {
  const relatedTabOpenable = canOpenRelatedTab(detail.relatedTab, visibleTabs)

  return (
    <div
      className="rounded-xl border border-primaryAccent/25 bg-primaryAccent/5 p-3 text-[11px] shadow-sm"
      role="region"
      aria-label="步骤详情"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[10px] text-muted">步骤 {detail.stepIndex + 1} · {detail.stepKey}</p>
          <h3 className="mt-0.5 text-[13px] font-semibold text-primary">{detail.label}</h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-border/20 px-2 py-0.5 text-[10px] text-muted hover:text-primary"
        >
          关闭
        </button>
      </div>
      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        <div>
          <dt className="text-[10px] text-muted">状态</dt>
          <dd className="mt-0.5 font-medium text-primary">{detail.statusLabel}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-muted">耗时</dt>
          <dd className="mt-0.5 font-medium text-primary">{detail.durationLabel}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-muted">关联 Tab</dt>
          <dd className="mt-0.5 font-medium text-primary">{detail.relatedTabLabel}</dd>
        </div>
        {detail.isCurrent ? (
          <div>
            <dt className="text-[10px] text-muted">进度</dt>
            <dd className="mt-0.5 font-medium text-primaryAccent">当前步骤</dd>
          </div>
        ) : null}
      </dl>
      {detail.summary ? (
        <p className="mt-2 rounded-lg border border-border/15 bg-background px-2 py-1.5 text-[10px] leading-relaxed text-muted">
          {detail.summary}
        </p>
      ) : null}
      {detail.metricsLines.length ? (
        <ul className="mt-2 space-y-1 text-[10px] text-primary">
          {detail.metricsLines.map((line) => (
            <li key={line}>• {line}</li>
          ))}
        </ul>
      ) : null}
      {detail.error ? (
        <p className="mt-2 rounded border border-destructive/20 bg-destructive/5 px-2 py-1 text-[10px] text-destructive">
          {detail.error}
        </p>
      ) : null}
      {onOpenTab && detail.relatedTab !== 'overview' && detail.relatedTab !== 'flow' ? (
        relatedTabOpenable ? (
          <button
            type="button"
            onClick={() => onOpenTab(detail.relatedTab)}
            className="mt-3 text-[10px] font-medium text-primaryAccent hover:underline"
          >
            打开 {detail.relatedTabLabel}
          </button>
        ) : (
          <p className="mt-3 text-[10px] text-muted">
            关联 Tab「{detail.relatedTabLabel}」在当前阶段不可用
          </p>
        )
      ) : null}
    </div>
  )
}

function FlowStepRow({
  step,
  index,
  selected,
  visibleTabs,
  conditionalNote,
  onSelect,
  onOpenTab,
}: {
  step: GncFlowStepProjection
  index: number
  selected: boolean
  visibleTabs: readonly string[]
  conditionalNote?: string
  onSelect: () => void
  onOpenTab?: (tab: UnifiedWorkbenchTabKey) => void
}) {
  const isCurrent = step.is_current || step.status === 'running'
  const relatedTab = (step.related_tab || 'overview') as UnifiedWorkbenchTabKey
  const relatedTabOpenable = canOpenRelatedTab(relatedTab, visibleTabs)
  const showRelatedTabAction = relatedTab !== 'overview' && relatedTab !== 'flow' && (step.completed || isCurrent)

  return (
    <li
      className={`rounded-lg border px-3 py-2 text-[11px] transition-colors ${
        selected
          ? 'border-primaryAccent/50 bg-primaryAccent/8 ring-1 ring-primaryAccent/20'
          : isCurrent
            ? 'border-primaryAccent/30 bg-primaryAccent/5'
            : step.status === 'failed'
              ? 'border-destructive/25 bg-destructive/5'
              : 'border-border/15 bg-background'
      }`}
    >
      <button
        type="button"
        onClick={onSelect}
        className="w-full text-left"
        aria-expanded={selected}
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] text-muted">底层步骤 {index + 1}</span>
              {isCurrent ? (
                <span className="rounded bg-primaryAccent/15 px-1.5 py-0.5 text-[10px] font-medium text-primaryAccent">
                  当前
                </span>
              ) : null}
              {conditionalNote ? (
                <span className="rounded border border-border/20 bg-surface px-1.5 py-0.5 text-[10px] text-muted">
                  {conditionalNote}
                </span>
              ) : null}
            </div>
            <div className="mt-0.5 font-medium text-primary">{step.label || resolveGncStepLabel(step.step_key)}</div>
            {step.subtitle ? <p className="mt-1 text-[10px] leading-relaxed text-muted">{step.subtitle}</p> : null}
            {step.error ? (
              <p className="mt-1 rounded border border-destructive/20 bg-destructive/5 px-2 py-1 text-[10px] text-destructive">
                {step.error}
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <StepStatusBadge status={String(step.status || 'pending')} />
            <span className="text-[10px] text-muted">耗时 {formatDurationMs(step.duration_ms)}</span>
          </div>
        </div>
      </button>
      {!selected && showRelatedTabAction ? (
        <div className="mt-2 flex justify-end">
          {onOpenTab && relatedTabOpenable ? (
            <button
              type="button"
              onClick={() => onOpenTab(relatedTab)}
              className="text-[10px] text-primaryAccent hover:underline"
            >
              查看关联 Tab
            </button>
          ) : (
            <span className="text-[10px] text-muted">关联 Tab 在当前阶段不可用</span>
          )}
        </div>
      ) : null}
    </li>
  )
}

function FlowStageCard({
  stage,
  expanded,
  selectedStepKey,
  visibleTabs,
  committeeProjection,
  committeeLoading,
  committeeError,
  onToggleExpand,
  onSelectStep,
  onOpenTab,
}: {
  stage: GncFlowStageProjection
  expanded: boolean
  selectedStepKey: string | null
  visibleTabs: readonly string[]
  committeeProjection?: GncCommitteeSubflowInput | null
  committeeLoading?: boolean
  committeeError?: string
  onToggleExpand: () => void
  onSelectStep: (stepKey: string) => void
  onOpenTab?: (tab: UnifiedWorkbenchTabKey) => void
}) {
  const primaryTab = stage.primaryRelatedTab
  const primaryTabOpenable = primaryTab ? canOpenRelatedTab(primaryTab, visibleTabs) : false
  const showStageTabAction = primaryTab
    && primaryTab !== 'overview'
    && primaryTab !== 'flow'
    && (stage.status === 'completed' || stage.status === 'running')

  return (
    <li className="relative pl-8">
      <span
        className={`absolute left-3 top-5 h-2.5 w-2.5 rounded-full border-2 ${
          stage.status === 'completed'
            ? 'border-emerald-500 bg-emerald-500'
            : stage.status === 'running' || stage.isCurrent
              ? 'border-primaryAccent bg-primaryAccent'
              : stage.status === 'failed'
                ? 'border-destructive bg-destructive'
                : 'border-border/30 bg-background'
        }`}
        aria-hidden
      />
      <div
        className={`rounded-xl border px-3 py-2.5 text-[11px] transition-colors ${
          stage.isCurrent || stage.status === 'running'
            ? 'border-primaryAccent/40 bg-primaryAccent/5 shadow-sm'
            : stage.status === 'failed'
              ? 'border-destructive/25 bg-destructive/5'
              : 'border-border/15 bg-surface'
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <button
            type="button"
            onClick={onToggleExpand}
            className="min-w-0 flex-1 text-left"
            aria-expanded={expanded}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] text-muted">阶段 {stage.stageIndex + 1}</span>
              {stage.isCurrent ? (
                <span className="rounded bg-primaryAccent/15 px-1.5 py-0.5 text-[10px] font-medium text-primaryAccent">
                  当前
                </span>
              ) : null}
              {stage.conditionalNote ? (
                <span className="rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-800">
                  {stage.conditionalNote}
                </span>
              ) : null}
            </div>
            <h3 className="mt-0.5 text-[13px] font-semibold text-primary">{stage.label}</h3>
            <p className="mt-1 text-[10px] leading-relaxed text-muted">{stage.description}</p>
            {stage.summary ? (
              <p className="mt-1 text-[10px] leading-relaxed text-primary">{stage.summary}</p>
            ) : null}
            {stage.error ? (
              <p className="mt-1 rounded border border-destructive/20 bg-destructive/5 px-2 py-1 text-[10px] text-destructive">
                {stage.error}
              </p>
            ) : null}
            <p className="mt-1 text-[10px] text-muted">
              包含 {stage.stepKeys.length} 个底层步骤 · 点击{expanded ? '收起' : '展开'}详情
            </p>
          </button>
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <StepStatusBadge status={stage.status} />
            <span className="text-[10px] text-muted">耗时 {formatStageDuration(stage.durationMs)}</span>
          </div>
        </div>

        {showStageTabAction ? (
          <div className="mt-2 flex justify-end">
            {onOpenTab && primaryTabOpenable ? (
              <button
                type="button"
                onClick={() => onOpenTab(primaryTab!)}
                className="text-[10px] text-primaryAccent hover:underline"
              >
                打开阶段关联 Tab
              </button>
            ) : (
              <span className="text-[10px] text-muted">阶段关联 Tab 在当前不可用</span>
            )}
          </div>
        ) : null}

        {expanded ? (
          <>
            {stage.stageKey === 'committee_review' ? (
              <div className="mt-3 border-t border-border/10 pt-3">
                <GncCommitteeSubflowLanes
                  committee={committeeProjection}
                  committeeStepRunning={stage.status === 'running' || stage.isCurrent}
                  onOpenTab={onOpenTab}
                  loading={committeeLoading}
                  error={committeeError}
                />
              </div>
            ) : null}
            <ol className="mt-3 space-y-2 border-t border-border/10 pt-3">
              {stage.steps.map((view) => (
                <FlowStepRow
                  key={view.step.step_key}
                  step={view.step}
                  index={view.stepIndex >= 0 ? view.stepIndex : 0}
                  selected={selectedStepKey === view.step.step_key}
                  visibleTabs={visibleTabs}
                  conditionalNote={view.conditionalNote}
                  onSelect={() => onSelectStep(view.step.step_key)}
                  onOpenTab={onOpenTab}
                />
              ))}
            </ol>
          </>
        ) : null}
      </div>
    </li>
  )
}

export function GncFlowTab({
  reviewId,
  detail,
  enabled,
  onOpenTab,
}: {
  reviewId: string
  detail: UnifiedReviewWorkbenchDetail
  enabled: boolean
  onOpenTab?: (tab: UnifiedWorkbenchTabKey) => void
}) {
  const { data, loading, error } = useGncResource<GncFlowProjection>(reviewId, 'flow', enabled)
  const { data: committeeData, loading: committeeLoading, error: committeeError } = useGncResource<GncCommitteeSubflowInput>(reviewId, 'committee', enabled)
  const [expandedStageKey, setExpandedStageKey] = useState<string | null>(null)
  const [selectedStepKey, setSelectedStepKey] = useState<string | null>(null)

  const flow = data
  const steps = flow?.steps || []

  const stages = useMemo(
    () => aggregateGncFlowStages(steps, { requiresArbitration: flow?.requires_arbitration }),
    [steps, flow?.requires_arbitration],
  )

  const currentStageLabel = useMemo(() => resolveGncFlowCurrentStageLabel(stages), [stages])

  const selectedDetail = useMemo(() => {
    if (!selectedStepKey) return null
    const index = steps.findIndex((step) => step.step_key === selectedStepKey)
    if (index < 0) return null
    return buildGncFlowStepDetail(steps[index], index)
  }, [selectedStepKey, steps])

  if (loading) return <p className="text-[11px] text-muted">加载流程…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>

  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['审查状态', flow?.status || detail.status],
          ['当前阶段', currentStageLabel],
          ['工作台阶段', detail.workbench_phase],
          ['需仲裁', flow?.requires_arbitration || detail.metrics.requires_arbitration ? '是' : '否'],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border border-border/15 bg-surface px-3 py-2">
            <div className="text-[10px] text-muted">{label}</div>
            <div className="mt-1 text-[12px] font-medium text-primary">{value}</div>
          </div>
        ))}
      </div>

      {flow?.current_step ? (
        <p className="text-[10px] text-muted">
          当前底层步骤：{resolveGncStepLabel(flow.current_step)}
        </p>
      ) : null}

      {flow?.error || detail.error ? (
        <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-[11px] text-destructive">
          {flow?.error || detail.error}
        </div>
      ) : null}

      {flow?.failed_step && onOpenTab ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-[11px]">
          <span className="text-destructive">
            失败步骤：
            {resolveGncStepLabel(flow.failed_step)}
          </span>
          {flow.failed_step === 'human_arbitration' ? (
            canOpenRelatedTab('arbitration', detail.visible_tabs) && onOpenTab ? (
              <button type="button" onClick={() => onOpenTab('arbitration')} className="text-primaryAccent hover:underline">
                前往人工仲裁
              </button>
            ) : (
              <span className="text-muted">人工仲裁 Tab 在当前阶段不可用</span>
            )
          ) : null}
        </div>
      ) : null}

      {selectedDetail ? (
        <GncFlowStepDetailPanel
          detail={selectedDetail}
          visibleTabs={detail.visible_tabs}
          onOpenTab={onOpenTab}
          onClose={() => setSelectedStepKey(null)}
        />
      ) : null}

      {stages.length === 0 ? (
        <p className="rounded-xl border border-border/15 bg-surface px-3 py-4 text-center text-[11px] text-muted">
          暂无流程阶段。审查启动后，各阶段进度将在此展示。
        </p>
      ) : (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="text-[12px] font-semibold text-primary">审查主流程</h3>
            <span className="text-[10px] text-muted">6 个用户阶段 · 展开查看底层 10 步</span>
          </div>
          <ol className="relative space-y-3 border-l border-border/20 pl-0">
            {stages.map((stage) => (
              <FlowStageCard
                key={stage.stageKey}
                stage={stage}
                expanded={expandedStageKey === stage.stageKey}
                selectedStepKey={selectedStepKey}
                visibleTabs={detail.visible_tabs}
                committeeProjection={committeeData}
                committeeLoading={committeeLoading}
                committeeError={committeeError}
                onToggleExpand={() => setExpandedStageKey((current) => (
                  current === stage.stageKey ? null : stage.stageKey
                ))}
                onSelectStep={(stepKey) => setSelectedStepKey((current) => (
                  current === stepKey ? null : stepKey
                ))}
                onOpenTab={onOpenTab}
              />
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

export default GncFlowTab
