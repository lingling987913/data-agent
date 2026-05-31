'use client'

import { useCallback, useEffect, useState } from 'react'
import { getReviewPlusDetail, getReviewPlusReportMarkdown } from '@/features/review-plus-v2/api'
import ReviewPlusReportExportMenu from '@/features/review-plus-v2/components/ReviewPlusReportExportMenu'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import MarkdownReportExportMenu from '@/features/review-plus-shared/components/MarkdownReportExportMenu'
import { getSuperAgentRun } from '@/features/super-agent/api'
import type { SuperAgentRun } from '@/features/super-agent/types'
import { buildSuperAgentExportMarkdown } from '@/features/super-agent/utils/superAgentProcessingViewModel'
import { resolveBusinessExportMarkdown } from '@/features/review-plus-shared/utils/businessReportMarkdown'
import { mergeWorkbenchOverviewIntoMarkdown } from '@/features/review-plus-shared/utils/workbenchOverviewMarkdown'
import { getUnifiedWorkbenchResource } from '@/features/unified-review-workbench/api'
import { parseGncReportPayload } from '@/features/unified-review-workbench/utils/gncRichPanels'
import type { UnifiedReviewType, UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'
import { downloadBlobFile } from '@/features/review-plus-shared/utils/fileExport'

interface Props {
  reviewType: UnifiedReviewType
  reviewId: string
  detail: UnifiedReviewWorkbenchDetail
}

export default function UnifiedWorkbenchReportExport({
  reviewType,
  reviewId,
  detail,
}: Props) {
  const [reviewPlusTask, setReviewPlusTask] = useState<ReviewPlusTaskDetail | null>(null)
  const [reviewPlusMarkdown, setReviewPlusMarkdown] = useState('')
  const [gncMarkdown, setGncMarkdown] = useState('')
  const [superAgentRun, setSuperAgentRun] = useState<SuperAgentRun | null>(null)
  const [superAgentMarkdown, setSuperAgentMarkdown] = useState('')
  const [loading, setLoading] = useState(false)

  const reportAvailable = Boolean(detail.summary?.report_available)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    const load = async () => {
      try {
        if (reviewType === 'review_plus') {
          const [task, markdown] = await Promise.all([
            getReviewPlusDetail(reviewId),
            getReviewPlusReportMarkdown(reviewId).catch(() => ''),
          ])
          if (!cancelled) {
            setReviewPlusTask(task)
            setReviewPlusMarkdown(
              mergeWorkbenchOverviewIntoMarkdown(
                resolveBusinessExportMarkdown(markdown),
                detail,
              ),
            )
          }
          return
        }

        if (reviewType === 'gnc' && reportAvailable) {
          const payload = await getUnifiedWorkbenchResource<Record<string, unknown> | string | null>(
            'gnc',
            reviewId,
            'report',
          )
          const parsed = parseGncReportPayload(payload)
          if (!cancelled) {
            setGncMarkdown(
              mergeWorkbenchOverviewIntoMarkdown(
                resolveBusinessExportMarkdown(parsed?.markdown || ''),
                detail,
              ),
            )
          }
          return
        }

        if (reviewType === 'super_agent') {
          const [run, reportPayload] = await Promise.all([
            getSuperAgentRun(reviewId),
            getUnifiedWorkbenchResource<Record<string, unknown> | string | null>(
              'super_agent',
              reviewId,
              'report',
            ).catch(() => null),
          ])
          const parsed = parseGncReportPayload(reportPayload)
          const rawMarkdown = resolveBusinessExportMarkdown(parsed?.markdown?.trim() || '')
            || (run ? buildSuperAgentExportMarkdown(run) : '')
          const markdown = mergeWorkbenchOverviewIntoMarkdown(rawMarkdown, detail)
          if (!cancelled) {
            setSuperAgentRun(run)
            setSuperAgentMarkdown(markdown)
          }
        }
      } catch {
        if (!cancelled) {
          setReviewPlusTask(null)
          setReviewPlusMarkdown('')
          setGncMarkdown('')
          setSuperAgentRun(null)
          setSuperAgentMarkdown('')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [detail, reportAvailable, reviewId, reviewType])

  const handleSuperAgentMarkdownDownload = useCallback(() => {
    const markdown = superAgentMarkdown.trim()
      || (superAgentRun ? buildSuperAgentExportMarkdown(superAgentRun) : '')
    if (!markdown) return
    downloadBlobFile(
      `审查报告-${superAgentRun?.name || superAgentRun?.run_id || reviewId || 'draft'}.md`,
      markdown,
      'text/markdown;charset=utf-8',
    )
  }, [reviewId, superAgentMarkdown, superAgentRun])

  if (loading && reviewType === 'review_plus') {
    return (
      <ReviewPlusReportExportMenu
        task={null}
        disabledReason="报告加载中…"
        testIdPrefix="unified-workbench-review-plus-export"
      />
    )
  }

  if (loading && reviewType !== 'review_plus') {
    return (
      <MarkdownReportExportMenu
        title={detail.name || '审查报告'}
        markdown=""
        disabledReason="报告加载中…"
        testIdPrefix="unified-workbench-export-loading"
      />
    )
  }

  if (reviewType === 'review_plus') {
    return (
      <ReviewPlusReportExportMenu
        task={reviewPlusTask}
        reportMarkdown={reviewPlusMarkdown}
        testIdPrefix="unified-workbench-review-plus-export"
      />
    )
  }

  if (reviewType === 'gnc') {
    const filenameBase = `${detail.name || 'gnc'}-审查报告`
    return (
      <MarkdownReportExportMenu
        title={detail.name || 'GNC 审查报告'}
        markdown={gncMarkdown}
        filenameBase={filenameBase}
        disabled={!reportAvailable && !gncMarkdown.trim()}
        testIdPrefix="unified-workbench-gnc-export"
      />
    )
  }

  const superAgentReady = Boolean(
    superAgentMarkdown.trim()
    || reportAvailable
    || superAgentRun?.status === 'completed'
    || superAgentRun?.status === 'limited',
  )

  return (
    <MarkdownReportExportMenu
      title={detail.name || '智能审查报告'}
      markdown={superAgentMarkdown}
      filenameBase={`${detail.name || 'super-agent'}-审查报告`}
      disabled={!superAgentReady}
      disabledReason={superAgentReady ? undefined : '报告尚未生成'}
      showMarkdownDownload
      onDownloadMarkdown={handleSuperAgentMarkdownDownload}
      testIdPrefix="unified-workbench-super-agent-export"
    />
  )
}
