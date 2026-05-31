'use client'

import { useMemo, useState } from 'react'
import { ChevronRight, Route } from 'lucide-react'
import { STEP_STATUS_LABELS } from '@aqua/workflow-core'
import type { WorkflowGraphNode, WorkflowStepStatus } from '@aqua/workflow-core'
import ReviewPlusCurrentStepBanner from '@/features/review-plus-v2/components/ReviewPlusCurrentStepBanner'
import ReviewPlusFlowWorkbenchView from '@/features/review-plus-v2/components/ReviewPlusFlowWorkbenchView'
import ReviewPlusStepDrawer from '@/features/review-plus-v2/components/ReviewPlusStepDrawer'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { buildReviewPlusV2SessionDeepLink } from '@/features/review-plus-v2/tabNavigation'
import {
  REVIEW_PLUS_PIPELINE_STEPS,
  type ReviewPlusWorkbenchTabKey,
  workflowStepToWorkbenchTab,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { buildReviewPlusSessionSnapshot } from '@/features/review-plus-v2/utils/reviewPlusSessionAdapter'
import { buildReviewPlusStepDetail } from '@/features/review-plus-v2/utils/reviewPlusStepDetail'

type Props = {
  task: ReviewPlusTaskDetail
  reviewId: string
  isExecuting?: boolean
  visibleTabs?: Set<ReviewPlusWorkbenchTabKey>
  onOpenTab: (tab: ReviewPlusWorkbenchTabKey, options?: { judgmentFilter?: 'not_satisfied' }) => void
  onContinueReview?: () => void
  onRestartReview?: () => void
  continuing?: boolean
  restarting?: boolean
}

function stepStripTone(status: WorkflowStepStatus, isCurrent: boolean): string {
  if (isCurrent) return 'border-primaryAccent/40 bg-primaryAccent/10 text-primaryAccent'
  switch (status) {
    case 'completed':
      return 'border-positive/30 bg-positive/8 text-positive'
    case 'running':
      return 'border-primaryAccent/35 bg-primaryAccent/8 text-primaryAccent'
    case 'failed':
    case 'blocked':
      return 'border-destructive/30 bg-destructive/8 text-destructive'
    case 'awaiting_confirm':
      return 'border-warning/30 bg-warning/8 text-warning'
    default:
      return 'border-border/25 bg-background text-muted'
  }
}

function countStepIssues(node: WorkflowGraphNode, task: ReviewPlusTaskDetail): number {
  const detail = buildReviewPlusStepDetail(
    node.step_key as Parameters<typeof buildReviewPlusStepDetail>[0],
    task,
    node.status,
    {
      started_at: node.started_at,
      completed_at: node.completed_at,
      blocked_reason: node.blocked_reason,
      output_summary: node.output_summary,
    },
  )
  return detail.findingPreviews.length
}

export default function ReviewPlusProgressHome({
  task,
  reviewId,
  isExecuting = false,
  visibleTabs,
  onOpenTab,
  onContinueReview,
  onRestartReview,
  continuing = false,
  restarting = false,
}: Props) {
  const snapshot = useMemo(() => buildReviewPlusSessionSnapshot(task), [task])
  const [selectedStepNode, setSelectedStepNode] = useState<WorkflowGraphNode | null>(null)
  const [stepDrawerOpen, setStepDrawerOpen] = useState(false)

  const stepNodes = useMemo(
    () => snapshot.graph.nodes.filter((node) => node.node_type === 'step'),
    [snapshot.graph.nodes],
  )
  const nodeByKey = useMemo(
    () => new Map(stepNodes.map((node) => [node.step_key, node])),
    [stepNodes],
  )

  const currentStepKey = snapshot.current_step_key || ''
  const currentStepDef = REVIEW_PLUS_PIPELINE_STEPS.find((step) => step.step_key === currentStepKey)
  const currentStepNode = nodeByKey.get(currentStepKey)
  const completedCount = stepNodes.filter((node) => node.status === 'completed').length
  const failedCount = stepNodes.filter((node) => node.status === 'failed' || node.status === 'blocked').length

  const notSatisfiedCount = (task.findings || []).filter((f) => f.judgment === 'not_satisfied').length
  const criticalCount = (task.findings || []).filter((f) => String(f.severity) === 'critical').length
  const crossDocOpenCount = (task.cross_document_review_items || [])
    .filter((item) => !['closed', 'resolved'].includes(String(item.status || 'open'))).length

  const tabsForGating = visibleTabs || new Set<ReviewPlusWorkbenchTabKey>(['overview'])
  const sessionDeepLink = buildReviewPlusV2SessionDeepLink(reviewId)

  const openStepDrawer = (stepKey: string) => {
    const node = nodeByKey.get(stepKey) ?? null
    setSelectedStepNode(node)
    setStepDrawerOpen(Boolean(node))
  }

  const selectedStepCanOpenTab = selectedStepNode
    ? tabsForGating.has(workflowStepToWorkbenchTab(selectedStepNode.step_key))
    : false

  return (
    <div className="mx-auto max-w-7xl space-y-3 p-1" data-testid="review-plus-progress-home">
      <section className="aq-soft-panel overflow-hidden rounded-xl">
        <div className="border-b border-border/15 px-4 py-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <div className="flex items-center gap-2">
                <Route size={16} className="shrink-0 text-primaryAccent" aria-hidden />
                <h2 className="text-[14px] font-medium text-primary">审查进度</h2>
              </div>
              <p className="text-[11px] leading-relaxed text-muted">
                {currentStepDef
                  ? `当前正在执行「${currentStepDef.label}」；已完成 ${completedCount}/${REVIEW_PLUS_PIPELINE_STEPS.length} 步。`
                  : '审查已启动，等待首个步骤产出。若长时间无变化，请使用右上角「继续处理」。'}
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 text-[10px]">
              <span className="rounded-full border border-border/25 bg-background px-2.5 py-1 text-muted">
                步骤 {completedCount}/{REVIEW_PLUS_PIPELINE_STEPS.length}
              </span>
              {failedCount > 0 ? (
                <span className="rounded-full border border-destructive/25 bg-destructive/10 px-2.5 py-1 font-medium text-destructive">
                  异常 {failedCount}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {currentStepKey ? (
          <div className="border-b border-border/15 px-3 py-2">
            <ReviewPlusCurrentStepBanner
              currentStepKey={currentStepKey}
              currentStepLabel={currentStepDef?.label || currentStepNode?.label || currentStepKey}
              stepStatus={currentStepNode?.status}
              notSatisfiedCount={notSatisfiedCount}
              criticalCount={criticalCount}
              crossDocOpenCount={crossDocOpenCount}
              visibleTabs={tabsForGating}
              isExecuting={isExecuting}
              variant="workbench"
              showIssueChips={false}
              onOpenTab={(tab: ReviewPlusWorkbenchTabKey, options) => {
                if (tab === 'flow' || tab === 'report' || tab === 'materials') return
                onOpenTab(tab, options)
              }}
            />
          </div>
        ) : null}

        <div className="overflow-x-auto px-4 py-3">
          <ol className="flex min-w-max items-stretch gap-1.5" aria-label="审查步骤概览">
            {REVIEW_PLUS_PIPELINE_STEPS.map((step, index) => {
              const node = nodeByKey.get(step.step_key)
              const status = node?.status || 'pending'
              const isCurrent = step.step_key === currentStepKey
              const issueCount = node ? countStepIssues(node, task) : 0
              const statusLabel = STEP_STATUS_LABELS[status] || status

              return (
                <li key={step.step_key} className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => openStepDrawer(step.step_key)}
                    className={`flex min-w-[108px] flex-col gap-1 rounded-xl border px-2.5 py-2 text-left transition-colors hover:opacity-95 ${stepStripTone(status, isCurrent)}`}
                    aria-current={isCurrent ? 'step' : undefined}
                    data-testid={`review-plus-step-strip-${step.step_key}`}
                  >
                    <span className="text-[9px] font-medium opacity-80">第 {index + 1} 步</span>
                    <span className="line-clamp-2 text-[10px] font-medium leading-snug">{step.label}</span>
                    <span className="text-[9px] opacity-80">{statusLabel}</span>
                    {issueCount > 0 ? (
                      <span className="inline-flex w-fit rounded-full border border-destructive/25 bg-destructive/10 px-1.5 py-0.5 text-[8px] font-medium text-destructive">
                        问题 {issueCount}
                      </span>
                    ) : null}
                  </button>
                  {index < REVIEW_PLUS_PIPELINE_STEPS.length - 1 ? (
                    <ChevronRight size={14} className="shrink-0 text-muted/40" aria-hidden />
                  ) : null}
                </li>
              )
            })}
          </ol>
        </div>
      </section>

      <details className="aq-soft-panel overflow-hidden rounded-xl group">
        <summary className="cursor-pointer list-none border-b border-border/15 px-4 py-3 text-[11px] font-medium text-primary transition-colors hover:bg-surface/50">
          <span className="group-open:hidden">展开流程图</span>
          <span className="hidden group-open:inline">收起流程图</span>
          <span className="ml-2 text-[10px] font-normal text-muted">点击节点查看步骤详情</span>
        </summary>
        <div className="border-t border-border/15">
          <ReviewPlusFlowWorkbenchView
            reviewId={reviewId}
            task={task}
            visibleTabs={tabsForGating}
            isExecuting={isExecuting}
            showCurrentStepBanner={false}
            bannerVariant="workbench"
            showHeaderMetrics={false}
            layoutMode="workbench"
            hideTraceView
            onOpenRelatedTab={(tab, options) => {
              if (tab === 'flow' || tab === 'report' || tab === 'materials') return
              onOpenTab(tab, options)
            }}
            onContinueReview={onContinueReview}
            onRestartReview={onRestartReview}
            continuing={continuing}
            restarting={restarting}
          />
        </div>
        <div className="border-t border-border/15 px-4 py-2.5">
          <a
            href={sessionDeepLink}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-8 items-center text-[10px] font-medium text-primaryAccent hover:underline"
            data-testid="review-plus-open-full-trace"
          >
            查看完整执行 Trace
          </a>
        </div>
      </details>

      <ReviewPlusStepDrawer
        open={stepDrawerOpen}
        onClose={() => setStepDrawerOpen(false)}
        task={task}
        reviewId={reviewId}
        stepNode={selectedStepNode}
        canOpenRelatedTab={selectedStepCanOpenTab}
        onOpenWorkbenchTab={(tab) => {
          if (tab === 'flow' || tab === 'report' || tab === 'materials') return
          onOpenTab(tab)
          setStepDrawerOpen(false)
        }}
        portalToBody
        overlay
        onContinueReview={onContinueReview}
        onRestartReview={onRestartReview}
        continuing={continuing}
        restarting={restarting}
      />
    </div>
  )
}
