'use client'

import type { ReviewPlusCoverageMatrix, ReviewPlusCoverageMatrixRow } from '@/features/review-plus-shared/types'
import { COVERAGE_STATUS_LABELS, JUDGMENT_LABELS } from '@/features/review-plus-shared/types'

function coverageTone(status: string): string {
  switch (status) {
    case 'closed':
      return 'border-positive/20 bg-positive/8 text-positive'
    case 'task_only':
      return 'border-warning/20 bg-warning/8 text-warning'
    case 'subject_only':
      return 'border-warning/20 bg-warning/8 text-warning'
    case 'missing':
      return 'border-destructive/20 bg-destructive/8 text-destructive'
    default:
      return 'border-border/25 bg-muted/8 text-muted'
  }
}

function percentConfidence(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n)
  return `${pct}%`
}

interface Props {
  matrix: ReviewPlusCoverageMatrix
  maxRows?: number
  onViewFindings?: () => void
  onOpenCoverage?: () => void
}

export default function ReviewPlusCoverageMatrixPanel({
  matrix,
  maxRows = 12,
  onViewFindings,
  onOpenCoverage,
}: Props) {
  const rows = (matrix.rows || []).slice(0, maxRows)
  const total = matrix.summary?.row_count ?? matrix.rows?.length ?? 0
  const hasMore = (matrix.rows?.length || 0) > rows.length

  if (!rows.length) {
    return (
      <p className="text-[10px] text-muted">覆盖矩阵暂无明细行，请稍后刷新任务详情。</p>
    )
  }

  return (
    <div className="space-y-2" data-testid="review-plus-coverage-matrix">
      <div className="overflow-x-auto rounded-lg border border-border/20">
        <table className="w-full min-w-[480px] border-collapse text-left text-[10px]">
          <thead>
            <tr className="border-b border-border/20 bg-background/80 text-muted">
              <th className="px-2 py-1.5 font-medium">检查项</th>
              <th className="px-2 py-1.5 font-medium">覆盖</th>
              <th className="px-2 py-1.5 font-medium">判定</th>
              <th className="px-2 py-1.5 font-medium">置信度</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row: ReviewPlusCoverageMatrixRow, index) => {
              const status = String(row.coverage_status || '')
              const judgment = String(row.judgment || '')
              return (
                <tr key={`${row.check_item_id || index}`} className="border-b border-border/10 last:border-0">
                  <td className="max-w-[200px] truncate px-2 py-1.5 text-primary" title={row.check_item_title}>
                    {row.check_item_title || row.check_item_id || '—'}
                  </td>
                  <td className="px-2 py-1.5">
                    <span className={`inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-medium ${coverageTone(status)}`}>
                      {COVERAGE_STATUS_LABELS[status] || status || '—'}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-muted">
                    {JUDGMENT_LABELS[judgment] || judgment || '—'}
                  </td>
                  <td className="px-2 py-1.5 tabular-nums text-muted">
                    {percentConfidence(row.confidence)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {hasMore ? (
        <p className="text-[9px] text-muted">
          共 {total} 行，当前展示前 {rows.length} 行。
        </p>
      ) : null}
      <div className="flex flex-wrap gap-3">
        {onOpenCoverage ? (
          <button
            type="button"
            onClick={onOpenCoverage}
            className="text-[10px] font-medium text-primaryAccent hover:underline"
          >
            查看完整覆盖矩阵
          </button>
        ) : null}
        {onViewFindings ? (
          <button
            type="button"
            onClick={onViewFindings}
            className="text-[10px] font-medium text-primaryAccent hover:underline"
          >
            查看审查记录
          </button>
        ) : null}
      </div>
    </div>
  )
}
