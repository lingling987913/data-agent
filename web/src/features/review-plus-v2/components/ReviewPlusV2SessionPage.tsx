'use client'

/**
 * 文件组审查 — 流程深度监控页（deep-link 专用）
 * 主进度消费请使用工作台「审查进度」Tab；本页保留完整 DAG + Trace 供排查。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ResponsivePageActions, useIsMobile } from '@aqua/ui-core'
import type { ResponsiveActionItem } from '@aqua/ui-core'
import { continueReviewPlus, getReviewPlusDetail, startReviewPlus } from '@/features/review-plus-v2/api'
import ReviewPlusFlowWorkbenchView from '@/features/review-plus-v2/components/ReviewPlusFlowWorkbenchView'
import { buildReviewPlusV2WorkbenchHref } from '@/features/review-plus-v2/tabNavigation'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { STATUS_LABELS } from '@/features/review-plus-v2/types'
import {
  shouldShowReviewPlusContinueAction,
  type ReviewPlusWorkbenchTabKey,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { buildReviewPlusSessionSnapshot } from '@/features/review-plus-v2/utils/reviewPlusSessionAdapter'
import {
  formatReviewPlusScenarioLabel,
  isReviewPlusPreReview,
  resolveReviewPlusPrimaryProcessAction,
  resolveReviewPlusWorkbenchOpenTab,
} from '@/features/review-plus-v2/utils/reviewPlusUx'

const RUNNING_STATUSES = new Set([
  'parsing', 'classifying', 'structuring', 'rule_extracting', 'mapping',
  'reviewing', 'traceability_building', 'reporting', 'gatekeeping',
])

function extractReviewIdFromHref(href?: string): string {
  if (!href) return ''
  const clean = href.split('?')[0]
  const segments = clean.split('/').filter(Boolean)
  return segments[segments.length - 1] || ''
}

export default function ReviewPlusV2SessionPage({ href }: { href?: string }) {
  const params = useParams()
  const router = useRouter()
  const reviewId = extractReviewIdFromHref(href) || (params?.reviewId as string) || ''

  const isMobile = useIsMobile()

  const [task, setTask] = useState<ReviewPlusTaskDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [refreshError, setRefreshError] = useState('')
  const [actionError, setActionError] = useState('')
  const [processing, setProcessing] = useState(false)

  const loadTask = useCallback(async (silent = false) => {
    if (!reviewId) return
    try {
      if (!silent) setLoading(true)
      const detail = await getReviewPlusDetail(reviewId)
      setTask(detail)
      setLoadError('')
      setRefreshError('')
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载流程监控失败'
      if (silent) {
        setRefreshError(message)
        return
      }
      setLoadError(message)
      setTask(null)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [reviewId])

  useEffect(() => {
    void loadTask()
  }, [loadTask])

  useEffect(() => {
    if (!task || String(task.status) === 'completed') return undefined
    const shouldPoll =
      RUNNING_STATUSES.has(String(task.status)) || shouldShowReviewPlusContinueAction(task)
    if (!shouldPoll) return undefined
    const timer = window.setInterval(() => { void loadTask(true) }, 8000)
    return () => window.clearInterval(timer)
  }, [loadTask, task])

  const snapshot = useMemo(() => (task ? buildReviewPlusSessionSnapshot(task) : null), [task])
  const canContinue = task ? shouldShowReviewPlusContinueAction(task) : false
  const canStart = Boolean(
    task?.materials?.length
    && !canContinue
    && isReviewPlusPreReview(task)
    && !['blocked', 'limited_pass'].includes(String(task?.status || '')),
  )

  const primaryProcessAction = task
    ? resolveReviewPlusPrimaryProcessAction({
      status: String(task.status),
      canStart,
      canContinue,
    })
    : null

  const openWorkbench = useCallback((tab?: ReviewPlusWorkbenchTabKey) => {
    if (!reviewId || !task) return
    const resolvedTab = tab || resolveReviewPlusWorkbenchOpenTab(task)
    router.push(buildReviewPlusV2WorkbenchHref(reviewId, { tab: resolvedTab }))
  }, [reviewId, router, task])

  const handleProcessAction = useCallback(async () => {
    if (!reviewId || !primaryProcessAction) return
    try {
      setProcessing(true)
      setActionError('')
      if (primaryProcessAction.kind === 'start') {
        await startReviewPlus(reviewId)
      } else {
        await continueReviewPlus(reviewId)
      }
      await loadTask(true)
      openWorkbench('overview')
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '处理失败，请稍后重试')
    } finally {
      setProcessing(false)
    }
  }, [loadTask, openWorkbench, primaryProcessAction, reviewId])

  const workbenchTab = task ? resolveReviewPlusWorkbenchOpenTab(task) : 'materials'

  const primaryAction = useMemo<ResponsiveActionItem>(() => {
    if (primaryProcessAction) {
      return {
        key: primaryProcessAction.kind,
        label: processing ? primaryProcessAction.loadingLabel : primaryProcessAction.label,
        onClick: () => void handleProcessAction(),
        tone: 'brand',
        disabled: processing,
      }
    }
    return {
      key: 'workbench',
      label: String(task?.status || '') === 'completed' ? '查看审查结论' : '返回工作台',
      onClick: () => openWorkbench(workbenchTab),
      tone: 'brand',
    }
  }, [handleProcessAction, openWorkbench, primaryProcessAction, processing, task?.status, workbenchTab])

  const secondaryActions = useMemo<ResponsiveActionItem[]>(() => [
    {
      key: 'refresh',
      label: '刷新',
      onClick: () => void loadTask(true),
      tone: 'default',
    },
    {
      key: 'workbench',
      label: String(task?.status || '') === 'completed' ? '审查结论' : '审查进度',
      onClick: () => openWorkbench(workbenchTab),
      tone: 'default',
    },
  ], [loadTask, openWorkbench, task?.status, workbenchTab])

  if (loading && !task) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted">加载流程监控...</p>
      </div>
    )
  }

  if (loadError || !task || !snapshot) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="text-sm font-medium text-primary">{loadError || '流程监控不可用'}</p>
        <p className="max-w-md text-[11px] leading-relaxed text-muted">
          请从工作台进入任务；审查进度以工作台「审查进度」Tab 为准。
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <button
            type="button"
            onClick={() => void loadTask()}
            className="rounded-2xl border border-border/30 px-4 py-2 text-[11px] text-primary hover:border-brand/40"
          >
            重新加载
          </button>
          {reviewId ? (
            <button
              type="button"
              onClick={() => openWorkbench('materials')}
              className="rounded-2xl bg-brand px-4 py-2 text-[11px] text-white motion-safe:active:scale-[0.98]"
            >
              打开工作台
            </button>
          ) : null}
        </div>
      </div>
    )
  }

  const status = String(task.status)
  const completedSteps = snapshot.graph.nodes.filter(
    (node) => node.node_type === 'step' && node.status === 'completed',
  ).length
  const totalSteps = snapshot.graph.nodes.filter((node) => node.node_type === 'step').length
  const scenarioLabel = formatReviewPlusScenarioLabel(task.scenario)

  return (
    <div className={`flex h-full flex-col gap-2.5 ${isMobile ? 'overflow-y-auto p-3' : 'overflow-hidden p-3'}`}>
      <div className="aq-soft-panel shrink-0 rounded-xl border border-border/20 px-4 py-3">
        <div className={`gap-3 ${isMobile ? 'space-y-3' : 'flex items-start justify-between'}`}>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border/30 bg-background px-2.5 py-1 text-[10px] font-medium text-muted">
                深度监控
              </span>
              <span className="rounded-full border border-primaryAccent/20 bg-primaryAccent/8 px-2.5 py-1 text-[10px] font-medium text-primaryAccent">
                主进度在工作台
              </span>
              {scenarioLabel ? (
                <span className="rounded-full border border-border/30 bg-background px-2.5 py-1 text-[10px] text-muted">
                  {scenarioLabel}
                </span>
              ) : null}
            </div>
            <div className="space-y-1">
              <h1 className="min-w-0 break-words text-[17px] font-medium leading-snug text-primary">{task.name}</h1>
              <p className="text-[11px] text-muted">
                {STATUS_LABELS[status] || status}
                <span className="mx-1.5 text-border">·</span>
                步骤 {completedSteps}/{totalSteps || 0}
              </p>
              <p className="text-[10px] leading-relaxed text-muted/80">
                日常跟进请使用工作台「审查进度」Tab；本页通过步骤抽屉或流程图区域的「查看完整执行 Trace」进入，便于排查异常。
              </p>
            </div>
          </div>
          <ResponsivePageActions
            className="shrink-0"
            mobileVariant="compact"
            primaryAction={primaryAction}
            secondaryActions={secondaryActions}
          />
        </div>
      </div>

      {refreshError ? (
        <div className="shrink-0 rounded-lg border border-warning/20 bg-warning/8 px-4 py-2 text-[11px] text-warning">
          刷新失败：{refreshError}
        </div>
      ) : null}

      {actionError ? (
        <div className="shrink-0 rounded-lg border border-destructive/20 bg-destructive/8 px-4 py-2 text-[11px] text-destructive">
          {actionError}
        </div>
      ) : null}

      <ReviewPlusFlowWorkbenchView
        reviewId={reviewId}
        task={task}
        className="min-h-0 flex-1"
        isExecuting={RUNNING_STATUSES.has(status) || canContinue}
        showCurrentStepBanner
        bannerVariant="session"
      />
    </div>
  )
}
