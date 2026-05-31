'use client'

import Link from 'next/link'
import { useMemo } from 'react'
import {
  AlertTriangle,
  ExternalLink,
  RefreshCw,
  Search,
  Target,
} from 'lucide-react'
import { AGENT_RUN_STATUS_LABELS, resolveUiLabel } from '@/lib/aeroTerminology'
import UnifiedReviewWorkbenchShell from '@/features/unified-review-workbench/components/UnifiedReviewWorkbenchShell'
import type { MaterialClassification, ParsePreviewResponse, SuperAgentRun } from '@/features/super-agent/types'
import MarkdownReportExportMenu from '@/features/review-plus-shared/components/MarkdownReportExportMenu'
import {
  buildSuperAgentExportMarkdown,
  buildSuperAgentResultExplainability,
} from '@/features/super-agent/utils/superAgentProcessingViewModel'
import { extractReviewSummary } from '@/features/super-agent/utils/superAgentResultOverview'
import { defaultWorkbenchTabForRun } from '@/features/unified-review-workbench/utils/superAgentWorkbenchLink'

interface SuperAgentResultStepProps {
  run: SuperAgentRun
  classification: MaterialClassification | null
  loadFailedRunId: string
  busy: boolean
  parsePreview: ParsePreviewResponse | null
  onReloadRun: () => void | Promise<void>
  onExport: () => void
  onStartReview: () => void | Promise<void>
  onViewParsePreview: () => void | Promise<void>
  onResetWizard: () => void
}

function buildNativeWorkbenchHref(run: SuperAgentRun): string {
  const params = new URLSearchParams({
    reviewType: 'super_agent',
    reviewId: run.run_id,
  })
  const tab = defaultWorkbenchTabForRun(run)
  if (tab) params.set('tab', tab)
  return `/review/workbench?${params.toString()}`
}

export default function SuperAgentResultStep({
  run,
  classification,
  loadFailedRunId,
  busy,
  parsePreview,
  onReloadRun,
  onExport,
  onStartReview,
  onViewParsePreview,
  onResetWizard,
}: SuperAgentResultStepProps) {
  const summary = useMemo(() => extractReviewSummary(run), [run])
  const explainability = useMemo(() => buildSuperAgentResultExplainability(run), [run])
  const workbenchHref = useMemo(() => buildNativeWorkbenchHref(run), [run])
  const exportMarkdown = useMemo(() => buildSuperAgentExportMarkdown(run), [run])

  if (loadFailedRunId) {
    return (
      <section className="flex min-h-[560px] flex-1 flex-col rounded-xl border border-border/15 bg-surface p-5 shadow-soft sm:p-6">
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16 text-center">
          <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden />
          <p className="text-[12px] text-muted">无法加载审查结果，请重试。</p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void onReloadRun()}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border/20 bg-background px-4 text-[12px] font-medium text-primary disabled:opacity-50"
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            重新加载
          </button>
        </div>
      </section>
    )
  }

  if (!summary || !explainability) {
    return (
      <section className="flex min-h-[560px] flex-1 flex-col rounded-xl border border-border/15 bg-surface p-5 shadow-soft sm:p-6">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Target className="h-5 w-5 text-primaryAccent" aria-hidden />
          <h2 className="text-base font-semibold text-primary">审查结果工作台</h2>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <MarkdownReportExportMenu
              title={run.name || '智能审查报告'}
              markdown={exportMarkdown}
              filenameBase={`${run.name || 'super-agent'}-审查报告`}
              showMarkdownDownload
              onDownloadMarkdown={onExport}
              testIdPrefix="super-agent-result-export"
            />
          </div>
        </div>
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-16 text-center text-[12px] text-muted">
          审查已完成，暂无可展示的结果摘要。
        </div>
      </section>
    )
  }

  return (
    <section className="flex min-h-[560px] flex-1 flex-col rounded-xl border border-border/15 bg-surface p-4 shadow-soft sm:p-5">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Target className="h-5 w-5 text-primaryAccent" aria-hidden />
        <h2 className="text-base font-semibold text-primary">审查结果工作台</h2>
        {run.status ? (
          <span className="rounded-full border border-border/15 bg-background px-2 py-0.5 text-[10px] text-muted">
            {resolveUiLabel(AGENT_RUN_STATUS_LABELS, run.status)}
          </span>
        ) : null}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <MarkdownReportExportMenu
            title={run.name || '智能审查报告'}
            markdown={exportMarkdown}
            filenameBase={`${run.name || 'super-agent'}-审查报告`}
            showMarkdownDownload
            onDownloadMarkdown={onExport}
            testIdPrefix="super-agent-result-export"
          />
          <Link
            href={workbenchHref}
            className="inline-flex items-center gap-1 rounded-lg border border-border/20 bg-background px-2.5 py-1 text-[10px] font-medium text-primaryAccent hover:bg-primaryAccent/5"
          >
            打开完整统一工作台
            <ExternalLink className="h-3 w-3" aria-hidden />
          </Link>
        </div>
      </div>

      <div className="min-h-[620px] overflow-hidden rounded-xl border border-border/15 bg-background">
        <UnifiedReviewWorkbenchShell
          reviewType="super_agent"
          reviewId={run.run_id}
        />
      </div>

      <div className="mt-6 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void onStartReview()}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border/20 bg-background px-4 text-[12px] font-medium text-primary disabled:opacity-50"
        >
          <RefreshCw className="h-4 w-4" aria-hidden />
          重新审查
        </button>
        {parsePreview || run.parse_preview ? (
          <button
            type="button"
            onClick={() => void onViewParsePreview()}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border/20 bg-background px-4 text-[12px] font-medium text-primary"
          >
            <Search className="h-4 w-4" aria-hidden />
            查看解析预览
          </button>
        ) : null}
        <button
          type="button"
          onClick={onResetWizard}
          className="inline-flex min-h-10 items-center justify-center rounded-lg bg-brand px-4 text-[12px] font-medium text-white"
        >
          ← 新建审查
        </button>
      </div>
    </section>
  )
}
