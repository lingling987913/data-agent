'use client'

import { useCallback } from 'react'
import {
  buildReviewPlusExportHtml,
  buildReviewPlusWordExportHtml,
} from '@/features/review-plus-v2/utils/reviewPlusExport'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { downloadBlobFile, openPrintPreview } from '@/features/review-plus-shared/utils/fileExport'

interface Props {
  task: ReviewPlusTaskDetail | null
  reportMarkdown?: string
  disabled?: boolean
  disabledReason?: string
  className?: string
  testIdPrefix?: string
  /** When true, always render the export menu (options disabled until report is ready). */
  alwaysVisible?: boolean
}

function headerActionClass(active: boolean): string {
  return `inline-flex min-h-9 items-center justify-center rounded-2xl border px-3.5 text-[11px] font-medium transition-colors focus-visible:border-primaryAccent focus-visible:outline-none ${
    active
      ? 'border-primaryAccent/40 bg-primaryAccent text-white hover:bg-primaryAccent/90'
      : 'border-border/30 text-muted hover:bg-background'
  }`
}

export default function ReviewPlusReportExportMenu({
  task,
  reportMarkdown = '',
  disabled = false,
  disabledReason,
  className = '',
  testIdPrefix = 'review-plus-export',
  alwaysVisible = true,
}: Props) {
  const resolvedMarkdown = reportMarkdown || task?.report_markdown || task?.report?.markdown || ''
  const hasReportBody = Boolean(resolvedMarkdown.trim() || task?.report)
  const showMenu = alwaysVisible ? !disabled : Boolean(task) && !disabled && hasReportBody
  const exportBodyDisabled = !hasReportBody
  const exportDisabledReason = exportBodyDisabled
    ? (disabledReason || '报告尚未生成')
    : undefined

  const handleExportReviewSheet = useCallback(() => {
    if (!task || exportBodyDisabled) return
    openPrintPreview(buildReviewPlusExportHtml(task, resolvedMarkdown))
  }, [exportBodyDisabled, resolvedMarkdown, task])

  const handleExportHtml = useCallback(() => {
    if (!task || exportBodyDisabled) return
    const filename = `${task.name || 'review-plus'}-文件组审查单.html`
    downloadBlobFile(filename, buildReviewPlusExportHtml(task, resolvedMarkdown), 'text/html;charset=utf-8')
  }, [exportBodyDisabled, resolvedMarkdown, task])

  const handleExportWord = useCallback(() => {
    if (!task || exportBodyDisabled) return
    const filename = `${task.name || 'review-plus'}-文件组审查单.doc`
    downloadBlobFile(filename, buildReviewPlusWordExportHtml(task, resolvedMarkdown), 'application/msword;charset=utf-8')
  }, [exportBodyDisabled, resolvedMarkdown, task])

  if (!showMenu) return null

  return (
    <details className={`relative ${className}`.trim()} data-testid={`${testIdPrefix}-options`}>
      <summary className={`${headerActionClass(false)} cursor-pointer list-none gap-1.5`}>
        导出报告
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </summary>
      <div className="absolute right-0 top-full z-30 mt-2 min-w-[180px] overflow-hidden rounded-2xl border border-border/20 bg-background/95 p-1.5 shadow-warm backdrop-blur-md">
        <button
          type="button"
          onClick={handleExportReviewSheet}
          disabled={exportBodyDisabled}
          title={exportDisabledReason}
          className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[11px] text-primary transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40 focus-visible:border-primaryAccent focus-visible:outline-none"
          data-testid={`${testIdPrefix}-pdf`}
        >
          打印 / PDF
        </button>
        <button
          type="button"
          onClick={handleExportWord}
          disabled={exportBodyDisabled}
          title={exportDisabledReason}
          className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[11px] text-primary transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40 focus-visible:border-primaryAccent focus-visible:outline-none"
          data-testid={`${testIdPrefix}-word`}
        >
          导出 Word
        </button>
        <button
          type="button"
          onClick={handleExportHtml}
          disabled={exportBodyDisabled}
          title={exportDisabledReason}
          className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[11px] text-primary transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40 focus-visible:border-primaryAccent focus-visible:outline-none"
          data-testid={`${testIdPrefix}-html`}
        >
          导出 HTML
        </button>
      </div>
    </details>
  )
}
