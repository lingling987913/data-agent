'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { WorkflowGraphNode, WorkflowStepStatus } from '@aqua/workflow-core'
import { STEP_STATUS_COLORS, STEP_STATUS_LABELS } from '@aqua/workflow-core'
import ReviewPlusHarnessTeamPanel from '@/features/review-plus-shared/components/harness/ReviewPlusHarnessTeamPanel'
import ReviewPlusStepDetailPanel from '@/features/review-plus-v2/components/ReviewPlusStepDetailPanel'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import {
  REVIEW_PLUS_PIPELINE_STEPS,
  type ReviewPlusPipelineStepKey,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { buildReviewPlusStepDetail } from '@/features/review-plus-v2/utils/reviewPlusStepDetail'

type ReviewPlusRunTraceViewProps = {
  task: ReviewPlusTaskDetail
  nodes: WorkflowGraphNode[]
  currentStepKey?: string
  activeStepKey?: string
  useStepDrawer?: boolean
  onSelectStep?: (stepKey: string) => void
}

function stepBlockClasses(status: WorkflowStepStatus, isActive: boolean): string {
  if (isActive) {
    return 'border-l-brand border-brand/35 bg-brand/[0.06]'
  }
  switch (status) {
    case 'completed':
      return 'border-l-positive border-positive/30 bg-positive/5'
    case 'running':
      return 'border-l-primaryAccent border-primaryAccent/40 bg-primaryAccent/8'
    case 'awaiting_confirm':
      return 'border-l-warning border-warning/30 bg-warning/8'
    case 'blocked':
    case 'failed':
      return 'border-l-destructive border-destructive/30 bg-destructive/8'
    case 'skipped':
      return 'border-l-border/40 border-border/15 bg-surface/40 opacity-60'
    default:
      return 'border-l-border/40 border-border/20 bg-surface'
  }
}

export default function ReviewPlusRunTraceView({
  task,
  nodes,
  currentStepKey,
  activeStepKey,
  useStepDrawer = false,
  onSelectStep,
}: ReviewPlusRunTraceViewProps) {
  const [expandedSteps, setExpandedSteps] = useState<Record<string, boolean>>({})

  const orderedNodes = useMemo(() => {
    const byKey = new Map(nodes.map((n) => [n.step_key, n]))
    return REVIEW_PLUS_PIPELINE_STEPS
      .map((step) => byKey.get(step.step_key))
      .filter((n): n is WorkflowGraphNode => Boolean(n))
  }, [nodes])

  useEffect(() => {
    setExpandedSteps((prev) => {
      const next = { ...prev }
      orderedNodes.forEach((node) => {
        if (typeof next[node.step_key] === 'undefined') {
          next[node.step_key] = node.step_key === currentStepKey && node.status === 'running'
        }
      })
      return next
    })
  }, [currentStepKey, orderedNodes])

  const handleStepClick = useCallback((stepKey: string) => {
    onSelectStep?.(stepKey)
    setExpandedSteps((prev) => ({ ...prev, [stepKey]: !prev[stepKey] }))
  }, [onSelectStep])

  if (!orderedNodes.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted">
        当前没有可展示的运行链路
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto p-4 space-y-2" data-testid="review-plus-run-trace">
      <p className="text-[10px] leading-relaxed text-muted/80 px-1">
        点击步骤展开本环节详情；{useStepDrawer ? '同时可在右侧流程图或抽屉查看完整步骤面板。' : '再次点击可收起。'}
      </p>
      {orderedNodes.map((node) => {
        const stepKey = node.step_key as ReviewPlusPipelineStepKey
        const isActive = activeStepKey === stepKey || currentStepKey === stepKey
        const isExpanded = Boolean(expandedSteps[stepKey])
        const detail = buildReviewPlusStepDetail(stepKey, task, node.status, {
          started_at: node.started_at,
          completed_at: node.completed_at,
          blocked_reason: node.blocked_reason,
          output_summary: node.output_summary,
        })
        const collapsedSummary = detail.summaryLines[0] || node.output_summary || detail.description
        const statusBadgeCls = STEP_STATUS_COLORS[node.status] || 'bg-surface text-muted'

        return (
          <div
            key={node.node_id}
            className={`rounded-xl border-l-[3px] border transition-all ${stepBlockClasses(node.status, isActive)}`}
            data-testid={`review-plus-trace-step-${stepKey}`}
          >
            <button
              type="button"
              onClick={() => handleStepClick(stepKey)}
              className="w-full px-4 py-3 text-left"
              aria-expanded={isExpanded}
              aria-current={isActive ? 'step' : undefined}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[12px] font-medium text-primary">{node.label}</span>
                    <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-medium ${statusBadgeCls}`}>
                      {node.status === 'running' ? '● ' : ''}
                      {STEP_STATUS_LABELS[node.status]}
                    </span>
                    {isActive ? (
                      <span className="rounded-full border border-primaryAccent/25 bg-primaryAccent/10 px-1.5 py-0.5 text-[9px] text-primaryAccent">
                        当前步骤
                      </span>
                    ) : null}
                  </div>
                  {!isExpanded && collapsedSummary ? (
                    <p className="text-[10px] leading-relaxed text-muted line-clamp-2">{collapsedSummary}</p>
                  ) : null}
                  {!isExpanded && detail.findingPreviews.length > 0 ? (
                    <div className="flex flex-wrap gap-1 pt-0.5">
                      {detail.findingPreviews.slice(0, 3).map((finding) => (
                        <span
                          key={finding.id}
                          className={`rounded-full border px-1.5 py-0.5 text-[8px] font-medium ${
                            finding.tone === 'danger'
                              ? 'border-destructive/25 bg-destructive/8 text-destructive'
                              : 'border-warning/25 bg-warning/8 text-warning'
                          }`}
                        >
                          {finding.title}
                        </span>
                      ))}
                      {detail.findingPreviews.length > 3 ? (
                        <span className="text-[8px] text-muted">+{detail.findingPreviews.length - 3}</span>
                      ) : null}
                    </div>
                  ) : null}
                  {!isExpanded && detail.metrics.filter((m) => m.tone === 'danger' || m.tone === 'warning').length > 0 ? (
                    <div className="flex flex-wrap gap-1 pt-0.5">
                      {detail.metrics
                        .filter((m) => m.tone === 'danger' || m.tone === 'warning')
                        .slice(0, 4)
                        .map((metric) => (
                          <span
                            key={`${metric.label}-${metric.value}`}
                            className={`rounded-full border px-1.5 py-0.5 text-[8px] font-medium ${
                              metric.tone === 'danger'
                                ? 'border-destructive/25 bg-destructive/8 text-destructive'
                                : 'border-warning/25 bg-warning/8 text-warning'
                            }`}
                          >
                            {metric.label} {metric.value}
                          </span>
                        ))}
                    </div>
                  ) : null}
                </div>
                <span className="shrink-0 text-[10px] text-primaryAccent">
                  {isExpanded ? '收起' : '展开'}
                </span>
              </div>
            </button>

            {isExpanded ? (
              <div className="border-t border-border/15 px-4 pb-4 pt-2 space-y-3">
                <ReviewPlusStepDetailPanel detail={detail} />

                {detail.showHarnessPanel ? (
                  <ReviewPlusHarnessTeamPanel task={task} compact />
                ) : null}

                {detail.recentEvents.length > 0 ? (
                  <div className="rounded-lg border border-border/20 bg-background p-3">
                    <p className="text-[9px] font-medium text-muted">本步骤事件</p>
                    <ul className="mt-2 space-y-1.5">
                      {detail.recentEvents.map((ev, index) => (
                        <li key={`${ev.type}-${index}`} className="text-[10px] leading-relaxed text-primary/80">
                          <span className="text-muted">{ev.at ? `${ev.at} · ` : ''}</span>
                          <span className="font-medium">{ev.label}</span>
                          {ev.summary ? <span className="text-muted"> — {ev.summary}</span> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {useStepDrawer ? (
                  <button
                    type="button"
                    onClick={() => onSelectStep?.(stepKey)}
                    className="text-[10px] font-medium text-primaryAccent hover:underline"
                  >
                    在步骤详情抽屉中查看完整面板
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
