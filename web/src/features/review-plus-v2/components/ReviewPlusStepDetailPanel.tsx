'use client'

import type { ReviewPlusStepDetail } from '@/features/review-plus-v2/utils/reviewPlusStepDetail'
import { formatStepTimeRange } from '@/features/review-plus-v2/utils/reviewPlusStepDetail'
import { REVIEW_PLUS_TAB_LABELS, type ReviewPlusWorkbenchTabKey } from '@/features/review-plus-v2/utils/reviewPlusPipeline'

function metricToneClass(tone?: string): string {
  switch (tone) {
    case 'brand':
      return 'border-primaryAccent/20 bg-primaryAccent/8 text-primaryAccent'
    case 'success':
      return 'border-positive/20 bg-positive/8 text-positive'
    case 'warning':
      return 'border-warning/20 bg-warning/8 text-warning'
    case 'danger':
      return 'border-destructive/20 bg-destructive/8 text-destructive'
    default:
      return 'border-border/25 bg-background text-primary'
  }
}

interface Props {
  detail: ReviewPlusStepDetail
  compact?: boolean
  canOpenRelatedTab?: boolean
  onOpenRelatedTab?: (tab: ReviewPlusWorkbenchTabKey) => void
}

export default function ReviewPlusStepDetailPanel({
  detail,
  compact = false,
  canOpenRelatedTab = true,
  onOpenRelatedTab,
}: Props) {
  const timeRange = formatStepTimeRange(detail)
  const showNavigate =
    Boolean(onOpenRelatedTab)
    && canOpenRelatedTab
    && detail.relatedTab !== 'flow'
    && detail.status === 'completed'

  if (detail.status === 'pending') {
    return (
      <div className="space-y-2 text-[10px] leading-relaxed text-muted">
        <p>{detail.pendingHint || detail.description}</p>
      </div>
    )
  }

  return (
    <div className={`space-y-3 ${compact ? '' : ''}`}>
      {timeRange ? (
        <p className="text-[9px] text-muted tabular-nums">{timeRange}</p>
      ) : null}

      {detail.summaryLines.length > 0 ? (
        <div className="space-y-1.5">
          {detail.summaryLines.map((line, index) => (
            <p key={`summary-${index}`} className="text-[10px] leading-relaxed text-primary/80">
              {line}
            </p>
          ))}
        </div>
      ) : null}

      {detail.metrics.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {detail.metrics.map((metric) => (
            <span
              key={`${metric.label}-${metric.value}`}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-medium ${metricToneClass(metric.tone)}`}
            >
              <span className="text-muted/80">{metric.label}</span>
              <span>{metric.value}</span>
            </span>
          ))}
        </div>
      ) : null}

      {detail.findingPreviews.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-[9px] font-medium text-muted">问题摘要</p>
          <ul className="space-y-1.5">
            {detail.findingPreviews.map((preview) => (
              <li
                key={preview.id}
                className={`rounded-lg border px-2.5 py-2 text-[10px] leading-relaxed ${
                  preview.tone === 'danger'
                    ? 'border-destructive/20 bg-destructive/8 text-destructive'
                    : 'border-warning/20 bg-warning/8 text-warning'
                }`}
              >
                <p className="font-medium">{preview.title}</p>
                {preview.subtitle ? (
                  <p className="mt-0.5 text-[9px] opacity-90 line-clamp-2">{preview.subtitle}</p>
                ) : null}
              </li>
            ))}
          </ul>
          {!showNavigate && detail.findingPreviews.length > 0 ? (
            <p className="text-[9px] text-muted">完整列表可在对应业务页查看。</p>
          ) : null}
        </div>
      ) : null}

      {detail.highlights.length > 0 ? (
        <ul className="space-y-1.5">
          {detail.highlights.map((line, index) => (
            <li
              key={`highlight-${index}`}
              className="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/8 px-2.5 py-2 text-[10px] leading-relaxed text-warning"
            >
              <span className="mt-0.5 size-1.5 shrink-0 rounded-full bg-warning" aria-hidden />
              <span>{line}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {detail.status === 'running' && detail.pendingHint ? (
        <p className="text-[10px] text-muted">{detail.pendingHint}</p>
      ) : null}

      {detail.metrics.length === 0 && detail.summaryLines.length === 0 && detail.status !== 'running' ? (
        <p className="text-[10px] text-muted">本步骤已执行，详细结果可在对应业务页查看。</p>
      ) : null}

      {showNavigate ? (
        <button
          type="button"
          onClick={() => onOpenRelatedTab?.(detail.relatedTab)}
          className="inline-flex min-h-8 items-center gap-1 rounded-xl border border-border/30 bg-background px-3 py-1.5 text-[10px] font-medium text-primary transition-colors hover:border-primaryAccent/40 hover:bg-primaryAccent/5"
          data-testid={`review-plus-step-open-${detail.stepKey}`}
        >
          查看完整{REVIEW_PLUS_TAB_LABELS[detail.relatedTab]}
          <span aria-hidden>→</span>
        </button>
      ) : null}
    </div>
  )
}
