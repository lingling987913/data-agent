'use client'

import Link from 'next/link'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getUnifiedWorkbenchDetail } from '@/features/unified-review-workbench/api'
import { GncWorkbenchLinkProvider } from '@/features/unified-review-workbench/components/GncWorkbenchLinkContext'
import UnifiedReviewPlusEmbed from '@/features/unified-review-workbench/components/UnifiedReviewPlusEmbed'
import UnifiedSuperAgentEmbed from '@/features/unified-review-workbench/components/UnifiedSuperAgentEmbed'
import {
  GncArbitrationTab,
  GncCommitteeTab,
  GncDecisionTab,
  GncEvidencesTab,
  GncEventsTab,
  GncFindingsTab,
  GncFlowTab,
  GncMaterialsTab,
  GncMinutesTab,
  GncOverviewTab,
  GncReportTab,
  GncRidTab,
} from '@/features/unified-review-workbench/components/tabs/GncWorkbenchTabs'
import { resolvePhaseLabel } from '@/features/unified-review-workbench/phaseResolver'
import {
  buildWorkbenchNavigateHref,
  readWorkbenchBucketParam,
  readWorkbenchHintParam,
  shouldClearBucketOnTab,
} from '@/features/unified-review-workbench/utils/workbenchFilterQuery'
import type { WorkbenchNavigateOptions } from '@/features/unified-review-workbench/utils/workbenchStatAction'
import {
  buildWorkbenchTabHref,
  guardWorkbenchOpenTab,
  InvalidUrlTabHintTracker,
  resolveInvalidUrlTabSanitizeHint,
  shouldSanitizeWorkbenchUrlTab,
} from '@/features/unified-review-workbench/utils/workbenchTabGuard'
import { normalizeSuperAgentTabKey } from '@/features/unified-review-workbench/utils/superAgentTabAlias'
import { resolveActiveWorkbenchTab } from '@/features/unified-review-workbench/utils/workbenchTabResolver'
import { filterTabsForReviewType, resolveTabLabel } from '@/features/unified-review-workbench/tabRegistry'
import UnifiedWorkbenchReportExport from '@/features/unified-review-workbench/components/UnifiedWorkbenchReportExport'
import { buildReviewPlusLegacyWorkbenchHref } from '@/features/unified-review-workbench/tabNavigation'
import type {
  UnifiedReviewType,
  UnifiedReviewWorkbenchDetail,
  UnifiedWorkbenchTabKey,
} from '@/features/unified-review-workbench/types'

interface Props {
  reviewType: UnifiedReviewType
  reviewId: string
}

export default function UnifiedReviewWorkbenchShell({
  reviewType,
  reviewId,
}: Props) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const urlTab = searchParams.get('tab')
  const urlBucket = readWorkbenchBucketParam(searchParams)
  const urlHint = readWorkbenchHintParam(searchParams)
  const [detail, setDetail] = useState<UnifiedReviewWorkbenchDetail | null>(null)
  const [activeTab, setActiveTab] = useState<UnifiedWorkbenchTabKey>('overview')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tabGuardHint, setTabGuardHint] = useState('')
  const hasResolvedInitialTabRef = useRef(false)
  const invalidTabHintTrackerRef = useRef(new InvalidUrlTabHintTracker())
  const urlTabRef = useRef(urlTab)
  urlTabRef.current = urlTab

  useEffect(() => {
    hasResolvedInitialTabRef.current = false
    invalidTabHintTrackerRef.current.reset()
    setActiveTab('overview')
  }, [reviewType, reviewId])

  const openTab = useCallback((
    tab: UnifiedWorkbenchTabKey,
    options?: WorkbenchNavigateOptions,
  ) => {
    const resolvedTab = reviewType === 'super_agent'
      ? (normalizeSuperAgentTabKey(tab) || tab)
      : tab
    const guard = guardWorkbenchOpenTab(detail?.visible_tabs, reviewType, resolvedTab)
    if (!guard.allowed) {
      if (guard.reason === 'not_visible') {
        setTabGuardHint('该 Tab 当前不可见，已忽略跳转')
      }
      return
    }
    const nextHint = options?.hint?.trim() || ''
    setTabGuardHint(nextHint)
    setActiveTab(resolvedTab)
    let nextBucket: string | null | undefined = options?.bucket
    if (nextBucket === undefined) {
      nextBucket = shouldClearBucketOnTab(resolvedTab) ? null : urlBucket
    }
    const href = reviewType === 'super_agent'
      ? buildWorkbenchNavigateHref({
          pathname,
          searchParams,
          tab: resolvedTab,
          bucket: nextBucket,
          hint: options !== undefined ? (options.hint ?? null) : null,
        })
      : buildWorkbenchTabHref(pathname, searchParams, resolvedTab)
    router.replace(href, { scroll: false })
  }, [detail?.visible_tabs, pathname, reviewType, router, searchParams, urlBucket])

  const reloadDetail = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await getUnifiedWorkbenchDetail(reviewType, reviewId)
      setDetail(payload)
      setActiveTab((current) => {
        const mode = hasResolvedInitialTabRef.current ? 'reload' : 'initial'
        const nextTab = resolveActiveWorkbenchTab({
          visibleTabs: payload.visible_tabs,
          detail: payload,
          urlTab: urlTabRef.current,
          currentTab: current,
          mode,
        })
        hasResolvedInitialTabRef.current = true
        return nextTab
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [reviewType, reviewId])

  useEffect(() => {
    void reloadDetail()
  }, [reloadDetail])

  useEffect(() => {
    if (!detail || !hasResolvedInitialTabRef.current) return

    setActiveTab((current) => {
      const nextTab = resolveActiveWorkbenchTab({
        visibleTabs: detail.visible_tabs,
        detail,
        urlTab,
        currentTab: current,
        mode: 'url_sync',
      })
      return nextTab !== current ? nextTab : current
    })
  }, [urlTab, detail])

  useEffect(() => {
    if (!detail || !hasResolvedInitialTabRef.current) return
    if (!shouldSanitizeWorkbenchUrlTab(urlTab, activeTab, detail.visible_tabs, reviewType)) return

    const hint = resolveInvalidUrlTabSanitizeHint(urlTab, activeTab, detail.visible_tabs, reviewType)
    if (hint && invalidTabHintTrackerRef.current.shouldNotify(urlTab)) {
      setTabGuardHint(hint)
    }
    router.replace(buildWorkbenchTabHref(pathname, searchParams, activeTab), { scroll: false })
  }, [activeTab, detail, pathname, reviewType, router, searchParams, urlTab])

  useEffect(() => {
    if (!tabGuardHint) return
    const timer = window.setTimeout(() => setTabGuardHint(''), 2800)
    return () => window.clearTimeout(timer)
  }, [tabGuardHint])

  const tabItems = useMemo(() => {
    if (!detail) return []
    return filterTabsForReviewType(detail.visible_tabs, reviewType).map((key) => ({
      key,
      label: resolveTabLabel(key, reviewType),
    }))
  }, [detail, reviewType])

  if (loading && !detail) {
    return <div className="flex min-h-[320px] items-center justify-center text-[12px] text-muted">加载统一审查工作台…</div>
  }

  if (error || !detail) {
    return (
      <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-6 text-center text-[12px] text-destructive">
        {error || '无法加载工作台'}
        <button
          type="button"
          onClick={() => void reloadDetail()}
          className="mt-3 block w-full text-primaryAccent hover:underline"
        >
          重试
        </button>
      </div>
    )
  }

  const renderGncTab = () => {
    const tabEnabled = (tab: UnifiedWorkbenchTabKey) => activeTab === tab
    switch (activeTab) {
      case 'overview':
        return <GncOverviewTab detail={detail} onOpenTab={openTab} />
      case 'flow':
        return <GncFlowTab reviewId={reviewId} detail={detail} enabled={tabEnabled('flow')} onOpenTab={openTab} />
      case 'materials':
        return <GncMaterialsTab reviewId={reviewId} enabled={tabEnabled('materials')} />
      case 'findings':
        return <GncFindingsTab reviewId={reviewId} enabled={tabEnabled('findings')} />
      case 'rid':
        return <GncRidTab reviewId={reviewId} enabled={tabEnabled('rid')} />
      case 'evidences':
        return <GncEvidencesTab reviewId={reviewId} enabled={tabEnabled('evidences')} />
      case 'committee':
        return <GncCommitteeTab reviewId={reviewId} enabled={tabEnabled('committee')} />
      case 'minutes':
        return <GncMinutesTab reviewId={reviewId} enabled={tabEnabled('minutes')} />
      case 'decision':
        return <GncDecisionTab reviewId={reviewId} detail={detail} enabled={tabEnabled('decision')} />
      case 'arbitration':
        return (
          <GncArbitrationTab
            reviewId={reviewId}
            detail={detail}
            enabled={tabEnabled('arbitration')}
            onDetailRefresh={() => void reloadDetail()}
          />
        )
      case 'events':
        return <GncEventsTab reviewId={reviewId} enabled={tabEnabled('events')} />
      case 'report':
        return <GncReportTab reviewId={reviewId} detail={detail} enabled={tabEnabled('report')} />
      default:
        return <p className="text-[11px] text-muted">该 Tab 暂无内容</p>
    }
  }

  const mainContent = reviewType === 'gnc' ? (
    <GncWorkbenchLinkProvider onOpenTab={openTab}>
      {renderGncTab()}
    </GncWorkbenchLinkProvider>
  ) : reviewType === 'super_agent' ? (
    <UnifiedSuperAgentEmbed
      runId={reviewId}
      activeTab={activeTab}
      detail={detail}
      onOpenTab={openTab}
      urlBucket={urlBucket}
      landingHint={urlHint}
    />
  ) : (
    <UnifiedReviewPlusEmbed
      reviewId={reviewId}
      activeTab={activeTab}
      visibleTabs={detail.visible_tabs}
      onOpenTab={openTab}
    />
  )

  return (
    <div className="flex min-h-[calc(100vh-57px)] flex-col">
      <header className="shrink-0 border-b border-border/15 bg-surface px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-base font-semibold text-primary">{detail.name || detail.review_id}</h1>
          <span className="rounded-full border border-border/15 px-2 py-0.5 text-[10px] text-muted">
            {reviewType === 'gnc' ? 'GNC 审查' : reviewType === 'super_agent' ? 'Super Agent' : 'Review-Plus'}
          </span>
          <span className="rounded-full border border-primaryAccent/25 bg-primaryAccent/10 px-2 py-0.5 text-[10px] text-primaryAccent">
            {resolvePhaseLabel(detail.workbench_phase)}
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <UnifiedWorkbenchReportExport
              reviewType={reviewType}
              reviewId={reviewId}
              detail={detail}
            />
            {reviewType === 'review_plus' ? (
              <Link
                href={buildReviewPlusLegacyWorkbenchHref(reviewId)}
                className="text-[10px] text-primaryAccent hover:underline"
              >
                V2 完整工作台
              </Link>
            ) : null}
          </div>
        </div>
        {detail.current_step ? (
          <p className="mt-1 text-[10px] text-muted">当前步骤：{detail.current_step}</p>
        ) : null}
        {tabGuardHint ? (
          <p className="mt-1 text-[10px] text-amber-700">{tabGuardHint}</p>
        ) : null}
        <div className="-mx-1 mt-3 flex gap-0.5 overflow-x-auto border-t border-border/10 pt-2 scrollbar-none">
          {tabItems.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => openTab(tab.key)}
              className={`shrink-0 px-3 py-1.5 text-[11px] font-medium transition-colors ${
                activeTab === tab.key
                  ? 'border-b-2 border-primaryAccent text-primaryAccent'
                  : 'text-muted/70 hover:text-primary'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-auto p-4">
        {mainContent}
      </main>
    </div>
  )
}
