'use client'

import Link from 'next/link'
import { ExternalLink, LayoutDashboard } from 'lucide-react'
import ResultSummaryBar from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import {
  REVIEW_PLUS_VERDICT_COLORS,
  REVIEW_PLUS_VERDICT_LABELS,
  inferReviewPlusVerdict,
} from '@/features/review-plus-v2/utils/reviewPlusConclusion'
import type { SuperAgentResultExplainability } from '@/features/super-agent/utils/superAgentProcessingViewModel'
import type { ReviewResultSummary } from '@/features/super-agent/utils/superAgentResultOverview'
import type { SuperAgentRun } from '@/features/super-agent/types'
import {
  buildReviewWorkbenchResultPreviewModel,
  buildWorkbenchTabHref,
  type ReviewWorkbenchResultPreviewModel,
  type WorkbenchPreviewSection,
} from '@/features/unified-review-workbench/utils/reviewWorkbenchResultPreviewModel'
import type { UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

function PreviewSectionCard({
  section,
  reviewId,
  model,
}: {
  section: WorkbenchPreviewSection
  reviewId: string
  model: ReviewWorkbenchResultPreviewModel
}) {
  const sectionHref = section.tab ? buildWorkbenchTabHref(model, section.tab, reviewId) : null

  return (
    <article
      className="rounded-xl border border-border/15 bg-background/70 p-3"
      data-testid={`workbench-preview-section-${section.key}`}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold text-primary">{section.title}</h3>
        {sectionHref ? (
          <Link
            href={sectionHref}
            className="inline-flex items-center gap-0.5 text-[10px] text-primaryAccent hover:underline"
            data-testid={`workbench-preview-section-link-${section.key}`}
          >
            在工作台查看
            <ExternalLink className="h-3 w-3" aria-hidden />
          </Link>
        ) : null}
      </div>
      {section.items.length ? (
        <ul className="mt-2 space-y-1.5">
          {section.items.map((item, index) => (
            <li
              key={`${section.key}-${item.title}-${index}`}
              className="rounded-lg border border-border/10 bg-surface px-2.5 py-2 text-[11px]"
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-medium text-primary">{item.title}</span>
                {item.status ? (
                  <span className="rounded-full border border-border/15 px-1.5 py-0.5 text-[9px] text-muted">
                    {item.status}
                  </span>
                ) : null}
              </div>
              {item.detail ? (
                <p className="mt-1 line-clamp-2 leading-relaxed text-muted">{item.detail}</p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[10px] leading-relaxed text-muted">{section.emptyHint || '暂无数据'}</p>
      )}
    </article>
  )
}

export default function ReviewWorkbenchResultPreview({
  run,
  summary,
  explainability,
}: {
  run: SuperAgentRun
  summary: ReviewResultSummary
  explainability: SuperAgentResultExplainability
}) {
  const reviewId = run.source_review_id?.trim() || ''
  const model = buildReviewWorkbenchResultPreviewModel(run, summary, explainability)

  if (!model) return null

  const verdictTone = model.rationale ? inferReviewPlusVerdict(model.rationale) : null
  const kindLabel = model.reviewKind === 'gnc'
    ? 'GNC 审查工作台'
    : model.reviewKind === 'smart'
      ? '智能审查工作台'
      : 'Review-Plus 工作台'

  return (
    <div
      className="space-y-4"
      data-testid="review-workbench-result-preview"
      data-review-kind={model.reviewKind}
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="inline-flex items-center gap-1.5 rounded-lg border border-primaryAccent/20 bg-primaryAccent/5 px-2.5 py-1 text-[10px] font-medium text-primaryAccent">
          <LayoutDashboard className="h-3.5 w-3.5" aria-hidden />
          {kindLabel}
        </div>
        <span className="rounded-full border border-border/15 bg-background px-2 py-0.5 text-[10px] text-muted">
          {model.statusLabel}
        </span>
        {model.phaseLabel ? (
          <span className="rounded-full border border-border/15 bg-background px-2 py-0.5 text-[10px] text-muted">
            {model.phaseLabel}
          </span>
        ) : null}
        {model.arbitrationLabel ? (
          <span className="rounded-full border border-amber-500/25 bg-amber-500/8 px-2 py-0.5 text-[10px] text-amber-800">
            {model.arbitrationLabel}
          </span>
        ) : null}
      </div>

      {(model.verdict || model.rationale) ? (
        <section className="rounded-xl border border-border/15 bg-background/70 p-4">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <h2 className="text-[13px] font-medium text-primary">审查结论</h2>
              <p className="mt-1 text-[12px] leading-relaxed text-primary">
                {model.rationale || model.verdict}
              </p>
            </div>
            {model.verdict ? (
              <div className={`shrink-0 rounded-lg border px-3 py-1.5 text-center ${
                verdictTone ? REVIEW_PLUS_VERDICT_COLORS[verdictTone] : 'border-border/20 bg-background text-primary'
              }`}
              >
                <div className="text-[10px] font-medium">
                  {verdictTone ? REVIEW_PLUS_VERDICT_LABELS[verdictTone] : model.verdict}
                </div>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      <ResultSummaryBar
        items={model.summaryItems}
        hint={model.summaryHint}
        actions={model.workbenchHref ? (
          <Link
            href={model.workbenchHref}
            className="inline-flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-[10px] font-medium text-white"
            data-testid="workbench-preview-open-full"
          >
            打开完整工作台
            <ExternalLink className="h-3 w-3" aria-hidden />
          </Link>
        ) : undefined}
      />

      <div className="grid gap-3 lg:grid-cols-2">
        {model.sections.map((section) => (
          <PreviewSectionCard
            key={section.key}
            section={section}
            reviewId={reviewId}
            model={model}
          />
        ))}
      </div>

      {model.actions.length ? (
        <div className="flex flex-wrap gap-2">
          {model.actions.map((action) => {
            const href = buildWorkbenchTabHref(model, action.tab, reviewId)
            if (!href) return null
            const isPrimary = action.variant === 'primary'
            return (
              <Link
                key={`${action.tab}-${action.label}`}
                href={href}
                className={`inline-flex min-h-9 items-center gap-1 rounded-lg border px-3 text-[11px] font-medium ${
                  isPrimary
                    ? 'border-brand/30 bg-brand text-white'
                    : 'border-border/20 bg-background text-primary hover:bg-primaryAccent/5'
                }`}
                data-testid={`workbench-preview-action-${action.tab}`}
              >
                {action.label}
                <ExternalLink className="h-3 w-3" aria-hidden />
              </Link>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

export { buildReviewWorkbenchResultPreviewModel, buildWorkbenchTabHref }
export type { ReviewWorkbenchResultPreviewModel, UnifiedWorkbenchTabKey }
