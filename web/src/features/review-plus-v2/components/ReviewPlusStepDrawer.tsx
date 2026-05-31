'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useIsMobile } from '@aqua/ui-core'
import { STEP_STATUS_COLORS, STEP_STATUS_LABELS } from '@aqua/workflow-core'
import type { WorkflowGraphNode, WorkflowStepStatus } from '@aqua/workflow-core'
import ReviewPlusHarnessTeamPanel from '@/features/review-plus-shared/components/harness/ReviewPlusHarnessTeamPanel'
import ReviewPlusStepDetailPanel from '@/features/review-plus-v2/components/ReviewPlusStepDetailPanel'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import {
  REVIEW_PLUS_TAB_LABELS,
  type ReviewPlusPipelineStepKey,
  type ReviewPlusWorkbenchTabKey,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { buildReviewPlusStepDetail } from '@/features/review-plus-v2/utils/reviewPlusStepDetail'
import { buildReviewPlusV2SessionDeepLink } from '@/features/review-plus-v2/tabNavigation'
import { cn } from '@/lib/utils'

const COMPACT_LAYOUT_MEDIA_QUERY = '(max-width: 1279px)'

interface Props {
  open: boolean
  onClose: () => void
  task: ReviewPlusTaskDetail
  reviewId?: string
  stepNode: WorkflowGraphNode | null
  overlay?: boolean
  portalToBody?: boolean
  canOpenRelatedTab?: boolean
  onOpenWorkbenchTab?: (tab: ReviewPlusWorkbenchTabKey) => void
  onContinueReview?: () => void
  onRestartReview?: () => void
  continuing?: boolean
  restarting?: boolean
}

export default function ReviewPlusStepDrawer({
  open,
  onClose,
  task,
  reviewId,
  stepNode,
  overlay = false,
  portalToBody = false,
  canOpenRelatedTab = true,
  onOpenWorkbenchTab,
  onContinueReview,
  onRestartReview,
  continuing = false,
  restarting = false,
}: Props) {
  const [mounted, setMounted] = useState(false)
  const isMobile = useIsMobile()
  const [isCompactLayout, setIsCompactLayout] = useState(false)

  useEffect(() => { setMounted(true) }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mediaQuery = window.matchMedia(COMPACT_LAYOUT_MEDIA_QUERY)
    const update = () => setIsCompactLayout(mediaQuery.matches)
    update()
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', update)
      return () => mediaQuery.removeEventListener('change', update)
    }
    mediaQuery.addListener(update)
    return () => mediaQuery.removeListener(update)
  }, [])

  const shouldUseBottomDrawer = isMobile || isCompactLayout
  const shouldPortalToBody = portalToBody || shouldUseBottomDrawer

  if (!mounted || !stepNode) return null

  const stepKey = stepNode.step_key as ReviewPlusPipelineStepKey
  const detail = buildReviewPlusStepDetail(stepKey, task, stepNode.status, {
    started_at: stepNode.started_at,
    completed_at: stepNode.completed_at,
    blocked_reason: stepNode.blocked_reason,
  })

  const handleOpenTab = (tab: ReviewPlusWorkbenchTabKey) => {
    if (!canOpenRelatedTab) return
    onOpenWorkbenchTab?.(tab)
    onClose()
  }

  const showFooterCta =
    canOpenRelatedTab
    && onOpenWorkbenchTab
    && detail.relatedTab !== 'flow'
    && detail.status === 'completed'
  const showFailureControls = detail.status === 'failed' && (onContinueReview || onRestartReview)

  const drawerPanel = (
    <div
      className={cn(
        'flex flex-col bg-surface/95 shadow-2xl backdrop-blur-xl transition-transform duration-300',
        shouldUseBottomDrawer
          ? cn(
            'fixed inset-x-0 bottom-0 top-[max(5rem,env(safe-area-inset-top)+3.5rem)] rounded-t-3xl border-t border-border/15',
            open ? 'translate-y-0' : 'translate-y-full pointer-events-none',
          )
          : overlay
            ? cn(
              'absolute top-0 right-0 z-30 h-full w-[380px] border-l border-border/15',
              open ? 'translate-x-0' : 'translate-x-full pointer-events-none',
            )
            : cn(
              'fixed top-0 right-0 h-full w-[380px] border-l border-border/15',
              open ? 'translate-x-0' : 'translate-x-full pointer-events-none',
            ),
      )}
      style={shouldUseBottomDrawer ? undefined : { zIndex: 10001 }}
      data-testid="review-plus-step-drawer"
      aria-hidden={!open}
    >
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-border/15 px-5">
        <span className="text-[13px] font-medium text-primary">步骤详情</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭步骤详情"
          className="flex size-7 items-center justify-center rounded-lg text-muted transition-colors hover:bg-muted/10 hover:text-primary"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-[16px] font-medium text-primary">{stepNode.label}</h2>
          <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${STEP_STATUS_COLORS[stepNode.status as WorkflowStepStatus] || 'bg-surface text-muted'}`}>
            {STEP_STATUS_LABELS[stepNode.status as WorkflowStepStatus]}
          </span>
        </div>

        <p className="text-[10px] leading-relaxed text-muted">{detail.description}</p>

        <ReviewPlusStepDetailPanel
          detail={detail}
          canOpenRelatedTab={canOpenRelatedTab}
          onOpenRelatedTab={onOpenWorkbenchTab ? handleOpenTab : undefined}
        />

        {detail.recentEvents.length > 0 ? (
          <section className="space-y-2">
            <p className="text-[9px] font-medium text-muted">执行日志</p>
            <ul className="space-y-1.5">
              {detail.recentEvents.map((event, index) => (
                <li
                  key={`${event.type}-${event.at || index}`}
                  className="rounded-lg border border-border/20 bg-background px-3 py-2 text-[10px] leading-relaxed"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-primary">{event.label || event.type}</span>
                    {event.at ? <span className="text-[9px] tabular-nums text-muted">{event.at}</span> : null}
                  </div>
                  {event.summary ? <p className="mt-1 text-muted">{event.summary}</p> : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {showFailureControls ? (
          <section className="space-y-2 rounded-2xl border border-destructive/20 bg-destructive/5 p-3">
            <div>
              <p className="text-[10px] font-medium text-destructive">处理决策</p>
              <p className="mt-1 text-[10px] leading-relaxed text-muted">
                请先确认本节点的失败原因。若属于可恢复的中间状态或证据映射修正，选择继续处理；若需要清空派生结果并从送审包重新执行，选择重新开始处理。
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {onContinueReview ? (
                <button
                  type="button"
                  onClick={onContinueReview}
                  disabled={continuing || restarting}
                  className="rounded-2xl bg-brand px-3 py-2 text-[10px] font-medium text-white disabled:opacity-50"
                  data-testid="review-plus-step-continue-review"
                >
                  {continuing ? '继续中...' : '继续处理'}
                </button>
              ) : null}
              {onRestartReview ? (
                <button
                  type="button"
                  onClick={onRestartReview}
                  disabled={continuing || restarting}
                  className="rounded-2xl border border-border/30 bg-background px-3 py-2 text-[10px] font-medium text-primary hover:border-brand/40 disabled:opacity-50"
                  data-testid="review-plus-step-restart-review"
                >
                  {restarting ? '重启中...' : '重新开始处理'}
                </button>
              ) : null}
            </div>
          </section>
        ) : null}

        {detail.showHarnessPanel ? (
          <ReviewPlusHarnessTeamPanel
            task={task}
            onViewFindings={onOpenWorkbenchTab ? () => handleOpenTab('findings') : undefined}
            onOpenCoverage={onOpenWorkbenchTab ? () => handleOpenTab('coverage') : undefined}
          />
        ) : null}

        {showFooterCta ? (
          <button
            type="button"
            onClick={() => handleOpenTab(detail.relatedTab)}
            className="w-full rounded-2xl border border-border/30 bg-background px-4 py-2.5 text-[11px] font-medium text-primary transition-colors hover:border-primaryAccent/40 hover:bg-primaryAccent/5"
          >
            查看完整{REVIEW_PLUS_TAB_LABELS[detail.relatedTab]}
          </button>
        ) : null}

        {reviewId ? (
          <a
            href={buildReviewPlusV2SessionDeepLink(reviewId)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-9 w-full items-center justify-center rounded-2xl border border-border/30 px-4 text-[10px] font-medium text-primaryAccent transition-colors hover:border-primaryAccent/40 hover:bg-primaryAccent/5"
            data-testid="review-plus-step-drawer-full-trace"
          >
            查看完整执行 Trace
          </a>
        ) : null}
      </div>
    </div>
  )

  if (shouldPortalToBody) {
    if (!open) return null
    return createPortal(
      <>
        <button
          type="button"
          aria-label="关闭步骤详情"
          onClick={onClose}
          className="fixed inset-0 bg-black/20 backdrop-blur-[1px]"
          style={{ zIndex: 10000 }}
        />
        {drawerPanel}
      </>,
      document.body,
    )
  }

  if (overlay) {
    return drawerPanel
  }

  if (!open) return null
  return createPortal(drawerPanel, document.body)
}
