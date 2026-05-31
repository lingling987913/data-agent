'use client'

/**
 * 文件组审查流程工作台 — 对齐 GNC 审查会话页布局
 * 左侧：运行链路（步骤执行轨迹）
 * 右侧：工作流 DAG 全景图 + 步骤详情 Drawer
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { WorkflowGraphNode } from '@aqua/workflow-core'
import { useIsMobile } from '@aqua/ui-core'
import ReviewPlusFlowTimeline from '@/features/review-plus-v2/components/ReviewPlusFlowTimeline'
import ReviewPlusCurrentStepBanner from '@/features/review-plus-v2/components/ReviewPlusCurrentStepBanner'
import ReviewPlusRunTraceView from '@/features/review-plus-v2/components/ReviewPlusRunTraceView'
import ReviewPlusStepDrawer from '@/features/review-plus-v2/components/ReviewPlusStepDrawer'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import {
  REVIEW_PLUS_PIPELINE_STEPS,
  type ReviewPlusWorkbenchTabKey,
  workflowStepToWorkbenchTab,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { buildReviewPlusSessionSnapshot } from '@/features/review-plus-v2/utils/reviewPlusSessionAdapter'
import { resolveActiveWorkflowStepKey } from '@/features/review-plus-v2/utils/reviewPlusWorkflowGraph'

const NARROW_LAYOUT_MEDIA_QUERY = '(max-width: 1279px)'

interface Props {
  reviewId: string
  task: ReviewPlusTaskDetail
  className?: string
  visibleTabs?: Set<ReviewPlusWorkbenchTabKey>
  isExecuting?: boolean
  showCurrentStepBanner?: boolean
  bannerVariant?: 'session' | 'workbench'
  onOpenRelatedTab?: (tab: ReviewPlusWorkbenchTabKey, options?: { judgmentFilter?: 'not_satisfied' }) => void
  showHeaderMetrics?: boolean
  layoutMode?: 'full' | 'workbench'
  hideTraceView?: boolean
  onContinueReview?: () => void
  onRestartReview?: () => void
  continuing?: boolean
  restarting?: boolean
}

export default function ReviewPlusFlowWorkbenchView({
  reviewId,
  task,
  className = '',
  visibleTabs,
  isExecuting = false,
  showCurrentStepBanner = false,
  bannerVariant = 'session',
  onOpenRelatedTab,
  showHeaderMetrics = true,
  layoutMode = 'full',
  hideTraceView = false,
  onContinueReview,
  onRestartReview,
  continuing = false,
  restarting = false,
}: Props) {
  const snapshot = useMemo(() => buildReviewPlusSessionSnapshot(task), [task])

  const [activeStepKey, setActiveStepKey] = useState('')
  const [selectedStepNode, setSelectedStepNode] = useState<WorkflowGraphNode | null>(null)
  const [stepDrawerOpen, setStepDrawerOpen] = useState(false)
  const [splitRatio, setSplitRatio] = useState(0.42)
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [isCompactLayout, setIsCompactLayout] = useState(false)

  const resolvedLeftCollapsed = leftCollapsed || hideTraceView

  const isDraggingRef = useRef(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const lastAutoStepKeyRef = useRef('')
  const isMobile = useIsMobile()

  const currentStepKey = snapshot.current_step_key || resolveActiveWorkflowStepKey(task) || ''
  const currentStepDef = REVIEW_PLUS_PIPELINE_STEPS.find((step) => step.step_key === currentStepKey)
  const currentStepNode = snapshot.graph.nodes.find(
    (node) => node.node_type === 'step' && node.step_key === currentStepKey,
  )

  const notSatisfiedCount = (task.findings || []).filter((f) => f.judgment === 'not_satisfied').length
  const criticalCount = (task.findings || []).filter((f) => String(f.severity) === 'critical').length
  const crossDocOpenCount = (task.cross_document_review_items || [])
    .filter((item) => !['closed', 'resolved'].includes(String(item.status || 'open'))).length

  useEffect(() => {
    if (!currentStepKey) return

    setActiveStepKey((prev) => {
      const lastAutoStepKey = lastAutoStepKeyRef.current
      if (!prev || prev === lastAutoStepKey) return currentStepKey
      return prev
    })
    lastAutoStepKeyRef.current = currentStepKey
  }, [currentStepKey])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mediaQuery = window.matchMedia(NARROW_LAYOUT_MEDIA_QUERY)
    const update = () => setIsCompactLayout(mediaQuery.matches)
    update()
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', update)
      return () => mediaQuery.removeEventListener('change', update)
    }
    mediaQuery.addListener(update)
    return () => mediaQuery.removeListener(update)
  }, [])

  useEffect(() => {
    if (!isMobile && !isCompactLayout) return
    setLeftCollapsed(false)
    setRightCollapsed(false)
    setSplitRatio(0.5)
  }, [isCompactLayout, isMobile])

  const tabsForGating = visibleTabs || new Set<ReviewPlusWorkbenchTabKey>(['flow'])

  const canOpenTab = useCallback((tab: ReviewPlusWorkbenchTabKey) => tabsForGating.has(tab), [tabsForGating])

  const openStepDrawer = useCallback((stepKey: string) => {
    const node = snapshot.graph.nodes.find(
      (item) => item.node_type === 'step' && item.step_key === stepKey,
    ) ?? null
    setActiveStepKey(stepKey)
    setSelectedStepNode(node)
    setStepDrawerOpen(Boolean(node))
  }, [snapshot.graph.nodes])

  const handleSelectStep = useCallback((stepKey: string) => {
    openStepDrawer(stepKey)
  }, [openStepDrawer])

  const handleOpenRelatedTab = useCallback((tab: ReviewPlusWorkbenchTabKey) => {
    if (!canOpenTab(tab)) return
    onOpenRelatedTab?.(tab)
    setStepDrawerOpen(false)
  }, [canOpenTab, onOpenRelatedTab])

  const selectedStepCanOpenTab = selectedStepNode
    ? canOpenTab(workflowStepToWorkbenchTab(selectedStepNode.step_key))
    : false

  const handleDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDraggingRef.current = true
    const startX = e.clientX
    const startRatio = splitRatio
    const container = containerRef.current
    if (!container) return
    const containerWidth = container.offsetWidth

    const onMouseMove = (ev: MouseEvent) => {
      if (!isDraggingRef.current) return
      const delta = ev.clientX - startX
      const newRatio = Math.min(0.72, Math.max(0.28, startRatio + delta / containerWidth))
      setSplitRatio(newRatio)
    }
    const onMouseUp = () => {
      isDraggingRef.current = false
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [splitRatio])

  const stepCount = snapshot.graph.nodes.filter((node) => node.node_type === 'step').length
  const isWorkbenchLayout = layoutMode === 'workbench'
  const usePortalDrawer = isWorkbenchLayout || isCompactLayout || isMobile

  const rootClassName = isWorkbenchLayout
    ? 'min-h-[360px] h-[min(480px,52vh)] border-0 shadow-none'
    : 'min-h-[min(720px,72vh)]'

  const stepDrawer = (
    <ReviewPlusStepDrawer
      open={stepDrawerOpen}
      onClose={() => setStepDrawerOpen(false)}
      task={task}
      reviewId={reviewId}
      stepNode={selectedStepNode}
      canOpenRelatedTab={selectedStepCanOpenTab}
      onOpenWorkbenchTab={handleOpenRelatedTab}
      portalToBody={usePortalDrawer}
      overlay={!usePortalDrawer}
      onContinueReview={onContinueReview}
      onRestartReview={onRestartReview}
      continuing={continuing}
      restarting={restarting}
    />
  )

  return (
    <div
      className={`flex flex-col overflow-hidden rounded-xl border border-border/25 bg-surface shadow-soft ${rootClassName} ${className}`}
      data-testid="review-plus-v2-flow-workbench"
      data-layout-mode={layoutMode}
    >
      {layoutMode === 'full' ? (
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border/20 px-4 py-2.5">
          <div>
            <h3 className="text-[12px] font-medium text-primary">审查进度与步骤详情</h3>
            <p className="mt-0.5 text-[10px] text-muted">
              {hideTraceView
                ? '点击流程图节点查看各步骤的执行轨迹与详细指标。'
                : '左侧展开每一步的指标、事件与问题摘要；点击流程图节点可打开步骤详情抽屉（对齐 GNC 审查会话）。'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted">
            <span className="rounded-full border border-border/30 bg-background px-2.5 py-1">
              步骤 {stepCount}
            </span>
            {showHeaderMetrics ? (
              <>
                <span className="rounded-full border border-border/30 bg-background px-2.5 py-1">
                  检查项 {snapshot.metrics.rule_count}
                </span>
                <span className="rounded-full border border-border/30 bg-background px-2.5 py-1">
                  审查记录 {snapshot.metrics.finding_count}
                </span>
              </>
            ) : null}
          </div>
        </div>
      ) : null}

      {isWorkbenchLayout ? (
        <div className="shrink-0 border-b border-border/15 px-4 py-2">
          <p className="text-[10px] text-muted">
            {hideTraceView ? '点击流程图节点查看步骤详情' : '点击运行链路或流程图节点查看步骤详情'}
            <span className="mx-1.5 text-border">·</span>
            步骤 {stepCount}
          </p>
        </div>
      ) : null}

      {showCurrentStepBanner && currentStepKey ? (
        <div className="shrink-0 border-b border-border/15 px-3 py-2">
          <ReviewPlusCurrentStepBanner
            currentStepKey={currentStepKey}
            currentStepLabel={currentStepDef?.label || currentStepNode?.label || currentStepKey}
            stepStatus={currentStepNode?.status}
            notSatisfiedCount={notSatisfiedCount}
            criticalCount={criticalCount}
            crossDocOpenCount={crossDocOpenCount}
            visibleTabs={tabsForGating}
            isExecuting={isExecuting}
            variant={bannerVariant}
            onOpenTab={onOpenRelatedTab}
          />
        </div>
      ) : null}

      <div
        ref={containerRef}
        className={`min-h-0 flex-1 ${isCompactLayout || isMobile ? 'flex flex-col gap-3 p-3' : 'flex gap-0 p-2'}`}
      >
        {!resolvedLeftCollapsed && (
          <div
            className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-border/20 bg-background"
            style={
              isCompactLayout || isMobile
                ? { minHeight: isWorkbenchLayout ? 220 : 280 }
                : { width: rightCollapsed ? '100%' : `${splitRatio * 100}%`, minWidth: 280 }
            }
          >
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/20 px-4 py-2.5">
              <span className="text-[12px] font-medium text-primary">运行链路</span>
              {!isCompactLayout && !isMobile ? (
                <button
                  type="button"
                  onClick={() => setLeftCollapsed(true)}
                  className="flex size-5 items-center justify-center rounded text-muted/50 transition-colors hover:bg-muted/10 hover:text-muted"
                  title="收起运行链路"
                  aria-label="收起运行链路"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                    <line x1="9" y1="3" x2="9" y2="21" />
                  </svg>
                </button>
              ) : null}
            </div>
            <div className="min-h-0 flex-1">
              <ReviewPlusRunTraceView
                task={task}
                nodes={snapshot.graph.nodes.filter((node) => node.node_type === 'step')}
                currentStepKey={currentStepKey}
                activeStepKey={activeStepKey}
                useStepDrawer
                onSelectStep={handleSelectStep}
              />
            </div>
          </div>
        )}

        {!isCompactLayout && !isMobile && (
          <div
            onMouseDown={!resolvedLeftCollapsed && !rightCollapsed ? handleDividerMouseDown : undefined}
            onDoubleClick={() => {
              if (!resolvedLeftCollapsed && !rightCollapsed) setSplitRatio(0.42)
            }}
            className={`relative flex shrink-0 items-center justify-center self-stretch ${
              !resolvedLeftCollapsed && !rightCollapsed ? 'w-2 cursor-col-resize group' : 'w-1'
            }`}
          >
            {!resolvedLeftCollapsed && !rightCollapsed ? (
              <div className="h-8 w-[3px] rounded-full bg-border/25 transition-colors group-hover:bg-primaryAccent/40 group-active:bg-primaryAccent/60" />
            ) : null}
            {resolvedLeftCollapsed && !hideTraceView ? (
              <button
                type="button"
                onClick={() => setLeftCollapsed(false)}
                className="absolute top-1/2 -left-px z-10 flex h-12 w-5 -translate-y-1/2 items-center justify-center rounded-r-md border border-l-0 border-border/25 bg-surface text-muted/50 shadow-sm transition-colors hover:border-brand/25 hover:bg-brand/5 hover:text-brand"
                title="展开运行链路"
                aria-label="展开运行链路"
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
            ) : null}
            {rightCollapsed ? (
              <button
                type="button"
                onClick={() => setRightCollapsed(false)}
                className="absolute top-1/2 -right-px z-10 flex h-12 w-5 -translate-y-1/2 items-center justify-center rounded-l-md border border-r-0 border-border/25 bg-surface text-muted/50 shadow-sm transition-colors hover:border-brand/25 hover:bg-brand/5 hover:text-brand"
                title="展开流程图"
                aria-label="展开流程图"
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
            ) : null}
          </div>
        )}

        {!rightCollapsed && (
          <div
            className={`relative flex min-h-0 overflow-hidden rounded-xl border border-border/20 bg-background shadow-soft ${
              isCompactLayout || isMobile ? (isWorkbenchLayout ? 'min-h-[240px]' : 'min-h-[320px]') : 'flex-1'
            }`}
            style={isCompactLayout || isMobile ? undefined : { minWidth: resolvedLeftCollapsed ? undefined : 360 }}
          >
            <div className="group relative h-full w-full flex-1">
              <ReviewPlusFlowTimeline
                task={task}
                onSelectStep={handleSelectStep}
              />
              {!isCompactLayout && !isMobile ? (
                <button
                  type="button"
                  onClick={() => setRightCollapsed(true)}
                  className="absolute right-4 top-2.5 z-[15] flex size-7 items-center justify-center rounded-md border border-border/20 bg-background/80 text-muted opacity-0 shadow-sm backdrop-blur transition-all hover:text-primary group-hover:opacity-100"
                  title="收起流程图"
                  aria-label="收起流程图"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                    <line x1="15" y1="3" x2="15" y2="21" />
                  </svg>
                </button>
              ) : null}

              {!usePortalDrawer ? stepDrawer : null}
            </div>
          </div>
        )}
      </div>

      {usePortalDrawer ? stepDrawer : null}
    </div>
  )
}
