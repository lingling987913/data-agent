'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  confirmReviewPlusTraceLink,
  getReviewPlusDetail,
  getReviewPlusReportMarkdown,
  rejectReviewPlusTraceLink,
} from '@/features/review-plus-v2/api'
import DocumentPreviewModal from '@/features/review-plus-v2/components/DocumentPreviewModal'
import ReviewPlusDocumentPackagePanel from '@/features/review-plus-v2/components/ReviewPlusDocumentPackagePanel'
import ReviewPlusFlowWorkbenchView from '@/features/review-plus-v2/components/ReviewPlusFlowWorkbenchView'
import ReviewPlusCheckItemsTab from '@/features/review-plus-v2/components/workbench/ReviewPlusCheckItemsTab'
import ReviewPlusCoverageTab from '@/features/review-plus-v2/components/workbench/ReviewPlusCoverageTab'
import ReviewPlusCrossDocTab from '@/features/review-plus-v2/components/workbench/ReviewPlusCrossDocTab'
import ReviewPlusEventsTab from '@/features/review-plus-v2/components/workbench/ReviewPlusEventsTab'
import ReviewPlusFindingsTab from '@/features/review-plus-v2/components/workbench/ReviewPlusFindingsTab'
import ReviewPlusOverviewTab from '@/features/review-plus-v2/components/workbench/ReviewPlusOverviewTab'
import ReviewPlusTraceabilityTab from '@/features/review-plus-v2/components/workbench/ReviewPlusTraceabilityTab'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import type { ReviewPlusWorkbenchTabKey } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import ReviewPlusReportExportMenu from '@/features/review-plus-v2/components/ReviewPlusReportExportMenu'
import ConclusionOverviewPanel from '@/features/unified-review-workbench/components/ConclusionOverviewPanel'
import { LightMarkdownView } from '@/features/unified-review-workbench/components/LightMarkdownView'
import { ReviewPlusReadonlyEmbedBanner } from '@/features/unified-review-workbench/components/ReviewPlusReadonlyEmbedBanner'
import { getUnifiedWorkbenchDetail } from '@/features/unified-review-workbench/api'
import { buildConclusionOverviewFromDetail } from '@/features/unified-review-workbench/utils/conclusionOverviewModel'
import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'
import { buildReviewPlusLegacyWorkbenchHref } from '@/features/unified-review-workbench/tabNavigation'
import { resolveTabLabel } from '@/features/unified-review-workbench/tabRegistry'
import type { UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

interface Props {
  reviewId: string
  activeTab: UnifiedWorkbenchTabKey
  visibleTabs: string[]
  onOpenTab: (tab: UnifiedWorkbenchTabKey) => void
}

export default function UnifiedReviewPlusEmbed({
  reviewId,
  activeTab,
  visibleTabs,
  onOpenTab,
}: Props) {
  const [task, setTask] = useState<ReviewPlusTaskDetail | null>(null)
  const [workbenchDetail, setWorkbenchDetail] = useState<UnifiedReviewWorkbenchDetail | null>(null)
  const [reportMarkdown, setReportMarkdown] = useState('')
  const [materialPreview, setMaterialPreview] = useState<{ title: string; content: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [detail, markdown, wbDetail] = await Promise.all([
        getReviewPlusDetail(reviewId),
        getReviewPlusReportMarkdown(reviewId).catch(() => ''),
        getUnifiedWorkbenchDetail('review_plus', reviewId).catch(() => null),
      ])
      setTask(detail)
      setReportMarkdown(markdown)
      setWorkbenchDetail(wbDetail)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [reviewId])

  useEffect(() => {
    void reload()
  }, [reload])

  const visibleTabSet = useMemo(
    () => new Set(visibleTabs as ReviewPlusWorkbenchTabKey[]),
    [visibleTabs],
  )

  const handleConfirmTrace = useCallback(
    async (linkId: string, rationale?: string) => {
      await confirmReviewPlusTraceLink(reviewId, linkId, { rationale })
      await reload()
    },
    [reviewId, reload],
  )

  const handleRejectTrace = useCallback(
    async (linkId: string, rationale: string) => {
      await rejectReviewPlusTraceLink(reviewId, linkId, { rationale })
      await reload()
    },
    [reviewId, reload],
  )

  if (loading) return <p className="py-8 text-center text-[11px] text-muted">加载 Review-Plus 工作台…</p>
  if (error || !task) {
    return (
      <p className="py-8 text-center text-[11px] text-destructive">
        {error || '任务不存在'}
      </p>
    )
  }

  if (activeTab === 'overview') {
    const showConclusion = String(task.status || '').toLowerCase() === 'completed'
    const conclusionModel = workbenchDetail
      ? buildConclusionOverviewFromDetail(workbenchDetail, 'review_plus')
      : null
    return (
      <div className="space-y-4">
        {showConclusion && conclusionModel ? (
          <ConclusionOverviewPanel
            model={conclusionModel}
            onOpenTab={(tab) => onOpenTab(tab)}
          />
        ) : null}
        <ReviewPlusOverviewTab
          task={task}
          reviewId={reviewId}
          visibleTabs={visibleTabSet}
          reportMarkdown={reportMarkdown}
          showConclusionPanel={!conclusionModel}
          onOpenTab={(tab) => onOpenTab(tab as UnifiedWorkbenchTabKey)}
        />
      </div>
    )
  }
  if (activeTab === 'findings') {
    return (
      <ReviewPlusFindingsTab
        checkItems={task.check_items || []}
        findings={task.findings || []}
        coverageRows={task.coverage_matrix?.rows || []}
        variant="focus"
      />
    )
  }
  if (activeTab === 'coverage') {
    return <ReviewPlusCoverageTab task={task} />
  }
  if (activeTab === 'traceability') {
    return (
      <ReviewPlusTraceabilityTab
        result={task.traceability_result}
        defaultViewMode="matrix"
        onConfirmTraceLink={handleConfirmTrace}
        onRejectTraceLink={handleRejectTrace}
      />
    )
  }
  if (activeTab === 'cross_doc') {
    return <ReviewPlusCrossDocTab items={task.cross_document_review_items || []} />
  }
  if (activeTab === 'check_items') {
    return (
      <ReviewPlusCheckItemsTab
        checkItems={task.check_items || []}
        sectionMappings={task.section_mappings}
      />
    )
  }
  if (activeTab === 'events') {
    return <ReviewPlusEventsTab events={task.events || []} />
  }
  if (activeTab === 'materials') {
    return (
      <>
        <div className="space-y-3">
          <ReviewPlusReadonlyEmbedBanner
            reviewId={reviewId}
            tab="materials"
            title="送审材料（只读）"
            description="可查看解析状态、门禁结果与材料清单；上传、角色确认、重解析与重检门禁需在 V2 材料 Tab 操作。"
          />
          <ReviewPlusDocumentPackagePanel
            materials={task.materials || []}
            gatekeeping={task.gatekeeping_result || null}
            parserType="auto"
            uploading={false}
            parseComplete={Boolean(task.parse_artifact)}
            parsing={String(task.status || '') === 'parsing'}
            taskStatus={String(task.status || '')}
            readOnly
            onParserTypeChange={() => undefined}
            onFilesSelected={() => undefined}
            onRoleChange={() => undefined}
            onConfirmRole={() => undefined}
            onReclassify={() => undefined}
            onReparseMaterial={() => undefined}
            onReparseAll={() => undefined}
            onPreview={setMaterialPreview}
            onRecheckGate={() => undefined}
          />
        </div>
        {materialPreview ? (
          <DocumentPreviewModal
            title={materialPreview.title}
            content={materialPreview.content}
            onClose={() => setMaterialPreview(null)}
          />
        ) : null}
      </>
    )
  }
  if (activeTab === 'report') {
    return (
      <article className="space-y-3 rounded-xl border border-border/15 bg-background p-4 text-[12px]">
        <div className="flex flex-wrap items-center justify-end gap-2">
          <ReviewPlusReportExportMenu
            task={task}
            reportMarkdown={reportMarkdown}
            testIdPrefix="unified-review-plus-report-export"
          />
        </div>
        {reportMarkdown ? (
          <div className="prose prose-sm max-w-none">
            <LightMarkdownView markdown={reportMarkdown} />
          </div>
        ) : (
          <p className="text-muted">报告尚未生成</p>
        )}
      </article>
    )
  }
  if (activeTab === 'flow') {
    return (
      <div className="space-y-3">
        <ReviewPlusReadonlyEmbedBanner
          reviewId={reviewId}
          tab="flow"
          title="审查流程（只读）"
          description="可查看当前步骤、指标与关联 Tab；启动/重试步骤、Drawer 详情与写操作需在 V2 流程 Tab。"
        />
        <ReviewPlusFlowWorkbenchView
          reviewId={reviewId}
          task={task}
          visibleTabs={visibleTabSet}
          bannerVariant="workbench"
          showHeaderMetrics={false}
          layoutMode="workbench"
          showCurrentStepBanner
          onOpenRelatedTab={(tab) => {
            if (tab === 'flow' || tab === 'report') return
            onOpenTab(tab as UnifiedWorkbenchTabKey)
          }}
        />
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-border/15 bg-surface px-4 py-8 text-center text-[12px]">
      <p className="font-medium text-primary">
        「{resolveTabLabel(activeTab)}」暂未在此嵌入
      </p>
      <p className="mt-2 text-[11px] leading-relaxed text-muted">
        当前阶段下该 Tab 无可用内容，或需使用完整工作台查看。
      </p>
      <Link
        href={buildReviewPlusLegacyWorkbenchHref(reviewId, { tab: activeTab })}
        className="mt-4 inline-block text-[11px] text-primaryAccent hover:underline"
      >
        打开 Review-Plus V2 完整工作台
      </Link>
    </div>
  )
}
