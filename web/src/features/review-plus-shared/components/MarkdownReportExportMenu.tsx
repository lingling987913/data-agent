'use client'

import { useCallback } from 'react'
import {
  buildMarkdownReportExportHtml,
  buildMarkdownReportWordExportHtml,
} from '@/features/review-plus-shared/utils/markdownReportExport'
import { resolveBusinessExportMarkdown } from '@/features/review-plus-shared/utils/businessReportMarkdown'
import { downloadBlobFile, openPrintPreview } from '@/features/review-plus-shared/utils/fileExport'

interface Props {
  title: string
  markdown: string
  filenameBase?: string
  subtitle?: string
  metaRows?: Array<{ label: string; value: string }>
  disabled?: boolean
  disabledReason?: string
  className?: string
  testIdPrefix?: string
  showMarkdownDownload?: boolean
  onDownloadMarkdown?: () => void
  /** When true, always render the export menu (options disabled until markdown is ready). */
  alwaysVisible?: boolean
}

function headerActionClass(): string {
  return 'inline-flex min-h-9 items-center justify-center gap-1.5 rounded-2xl border border-border/30 px-3.5 text-[11px] font-medium text-muted transition-colors hover:bg-background focus-visible:border-primaryAccent focus-visible:outline-none cursor-pointer list-none'
}

export default function MarkdownReportExportMenu({
  title,
  markdown,
  filenameBase = '审查报告',
  subtitle,
  metaRows,
  disabled = false,
  disabledReason,
  className = '',
  testIdPrefix = 'markdown-report-export',
  showMarkdownDownload = false,
  onDownloadMarkdown,
  alwaysVisible = true,
}: Props) {
  const trimmed = resolveBusinessExportMarkdown(markdown)
  const canExport = !disabled && Boolean(trimmed)
  const exportBodyDisabled = !trimmed
  const exportDisabledReason = exportBodyDisabled ? (disabledReason || '报告尚未生成') : undefined

  const buildOptions = useCallback(
    () => ({
      title,
      subtitle,
      markdown: trimmed,
      metaRows,
    }),
    [metaRows, subtitle, title, trimmed],
  )

  const handlePrint = useCallback(() => {
    if (!canExport) return
    openPrintPreview(buildMarkdownReportExportHtml(buildOptions()))
  }, [buildOptions, canExport])

  const handleHtml = useCallback(() => {
    if (!canExport) return
    downloadBlobFile(
      `${filenameBase}.html`,
      buildMarkdownReportExportHtml(buildOptions()),
      'text/html;charset=utf-8',
    )
  }, [buildOptions, canExport, filenameBase])

  const handleWord = useCallback(() => {
    if (!canExport) return
    downloadBlobFile(
      `${filenameBase}.doc`,
      buildMarkdownReportWordExportHtml(buildOptions()),
      'application/msword;charset=utf-8',
    )
  }, [buildOptions, canExport, filenameBase])

  if (!alwaysVisible && !canExport && !showMarkdownDownload) return null

  return (
    <details className={`relative ${className}`.trim()} data-testid={`${testIdPrefix}-options`}>
      <summary className={headerActionClass()}>
        导出报告
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </summary>
      <div className="absolute right-0 top-full z-30 mt-2 min-w-[180px] overflow-hidden rounded-2xl border border-border/20 bg-background/95 p-1.5 shadow-warm backdrop-blur-md">
        {showMarkdownDownload && onDownloadMarkdown ? (
          <button
            type="button"
            onClick={onDownloadMarkdown}
            disabled={exportBodyDisabled}
            title={exportDisabledReason}
            className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[11px] text-primary transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40"
            data-testid={`${testIdPrefix}-md`}
          >
            导出 Markdown
          </button>
        ) : null}
        <button
          type="button"
          onClick={handlePrint}
          disabled={exportBodyDisabled}
          title={exportDisabledReason}
          className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[11px] text-primary transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40"
          data-testid={`${testIdPrefix}-pdf`}
        >
          打印 / PDF
        </button>
        <button
          type="button"
          onClick={handleWord}
          disabled={exportBodyDisabled}
          title={exportDisabledReason}
          className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[11px] text-primary transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40"
          data-testid={`${testIdPrefix}-word`}
        >
          导出 Word
        </button>
        <button
          type="button"
          onClick={handleHtml}
          disabled={exportBodyDisabled}
          title={exportDisabledReason}
          className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[11px] text-primary transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40"
          data-testid={`${testIdPrefix}-html`}
        >
          导出 HTML
        </button>
      </div>
    </details>
  )
}
