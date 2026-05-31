'use client'

import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import { useOptionalGncWorkbenchLink } from '@/features/unified-review-workbench/components/GncWorkbenchLinkContext'
import { LightMarkdownView } from '@/features/unified-review-workbench/components/LightMarkdownView'
import MarkdownReportExportMenu from '@/features/review-plus-shared/components/MarkdownReportExportMenu'
import { parseGncReportPayload } from '@/features/unified-review-workbench/utils/gncRichPanels'
import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'

export function GncReportTab({
  reviewId,
  enabled,
  detail,
}: {
  reviewId: string
  enabled: boolean
  detail: UnifiedReviewWorkbenchDetail
}) {
  const link = useOptionalGncWorkbenchLink()
  const { data, loading, error } = useGncResource<Record<string, unknown> | string | null>(
    reviewId,
    'report',
    enabled,
  )

  if (loading) return <p className="text-[11px] text-muted">加载报告…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>

  const report = parseGncReportPayload(data)
  const hasReport = Boolean(report?.markdown || report?.summary) || detail.summary.report_available

  if (!hasReport) {
    return (
      <div className="rounded-xl border border-dashed border-border/20 px-4 py-10 text-center text-[11px]">
        <p className="font-medium text-primary">正式报告尚未生成</p>
        <p className="mt-2 leading-relaxed text-muted">
          审查闭环并生成 report_markdown 后，将在此展示 Markdown 摘要。
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <button
            type="button"
            onClick={() => link?.openLinkedTab('minutes')}
            className="rounded-lg border border-border/20 px-3 py-1.5 text-[10px] text-primaryAccent hover:bg-primaryAccent/5"
          >
            查看纪要
          </button>
          <button
            type="button"
            onClick={() => link?.openLinkedTab('decision')}
            className="rounded-lg border border-border/20 px-3 py-1.5 text-[10px] text-primaryAccent hover:bg-primaryAccent/5"
          >
            查看总师裁定
          </button>
        </div>
      </div>
    )
  }

  return (
    <article className="space-y-3 text-[11px]">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <MarkdownReportExportMenu
          title={detail.name || 'GNC 审查报告'}
          markdown={report?.markdown || ''}
          filenameBase={`${detail.name || 'gnc'}-审查报告`}
          disabled={!report?.markdown?.trim()}
          disabledReason="报告正文尚未生成"
          testIdPrefix="gnc-report-tab-export"
        />
      </div>
      {report?.summary ? (
        <section className="rounded-xl border border-border/15 bg-surface px-4 py-3">
          <div className="text-[10px] font-medium text-muted">报告摘要</div>
          <p className="mt-1 text-primary">{report.summary}</p>
        </section>
      ) : null}
      {report?.markdown ? (
        <section className="rounded-xl border border-border/15 bg-background p-4">
          <div className="text-[10px] font-medium text-muted">Markdown 正文</div>
          <div className="mt-2 max-h-[560px] overflow-auto">
            <LightMarkdownView markdown={report.markdown} />
          </div>
        </section>
      ) : (
        <p className="text-muted">报告元数据已登记，正文为空。</p>
      )}
    </article>
  )
}

export default GncReportTab
