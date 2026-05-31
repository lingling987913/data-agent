'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ResultSummaryBar from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import type { ReviewPlusCoverageMatrixRow, ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { COVERAGE_STATUS_LABELS, JUDGMENT_LABELS } from '@/features/review-plus-v2/types'
import { buildHarnessSummaryMetrics, getHarnessPlan } from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'

type CoverageFilter = 'all' | 'closed' | 'task_only' | 'subject_only' | 'missing'
type JudgmentFilter = 'all' | 'satisfied' | 'not_satisfied' | 'insufficient_evidence' | 'not_applicable' | 'not_checked'

const ROW_HEIGHT_PX = 44
const VIEWPORT_HEIGHT_PX = 480
const VIRTUAL_THRESHOLD = 100

function coverageTone(status: string): string {
  switch (status) {
    case 'closed':
      return 'border-positive/20 bg-positive/8 text-positive'
    case 'task_only':
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

export default function ReviewPlusCoverageTab({
  task,
  onOpenEvidenceCompare,
  onCheckItemClick,
  highlightCheckItemId,
}: {
  task: ReviewPlusTaskDetail
  onOpenEvidenceCompare?: (row: ReviewPlusCoverageMatrixRow) => void
  onCheckItemClick?: (checkItemId: string) => void
  highlightCheckItemId?: string
}) {
  const matrix = task.coverage_matrix
  const rows = matrix?.rows || []
  const [coverageFilter, setCoverageFilter] = useState<CoverageFilter>('all')
  const [judgmentFilter, setJudgmentFilter] = useState<JudgmentFilter>('all')
  const [activeRowId, setActiveRowId] = useState<string | undefined>()
  const [scrollTop, setScrollTop] = useState(0)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const filteredRows = useMemo(() => {
    return rows.filter((row) => {
      const cov = String(row.coverage_status || '') as CoverageFilter
      const jud = String(row.judgment || '') as JudgmentFilter
      const covMatch = coverageFilter === 'all' || cov === coverageFilter
      const judMatch = judgmentFilter === 'all' || jud === judgmentFilter
      return covMatch && judMatch
    })
  }, [coverageFilter, judgmentFilter, rows])

  useEffect(() => {
    if (highlightCheckItemId) {
      setActiveRowId(highlightCheckItemId)
      const rowIndex = filteredRows.findIndex((r) => r.check_item_id === highlightCheckItemId)
      if (rowIndex !== -1 && scrollRef.current) {
        scrollRef.current.scrollTop = rowIndex * ROW_HEIGHT_PX - VIEWPORT_HEIGHT_PX / 2
      }
    }
  }, [highlightCheckItemId, filteredRows])

  const metrics = useMemo(
    () => buildHarnessSummaryMetrics(getHarnessPlan(task), task.agent_run_traces || [], matrix),
    [matrix, task],
  )

  const useVirtual = filteredRows.length >= VIRTUAL_THRESHOLD
  const totalHeight = filteredRows.length * ROW_HEIGHT_PX
  const startIndex = useVirtual ? Math.max(0, Math.floor(scrollTop / ROW_HEIGHT_PX) - 2) : 0
  const visibleCount = useVirtual ? Math.ceil(VIEWPORT_HEIGHT_PX / ROW_HEIGHT_PX) + 6 : filteredRows.length
  const visibleRows = filteredRows.slice(startIndex, startIndex + visibleCount)
  const offsetY = startIndex * ROW_HEIGHT_PX

  const onScroll = useCallback(() => {
    if (!scrollRef.current) return
    setScrollTop(scrollRef.current.scrollTop)
  }, [])

  const renderRow = (row: ReviewPlusCoverageMatrixRow, index: number) => {
    const status = String(row.coverage_status || '')
    const judgment = String(row.judgment || '')
    const isActive = activeRowId === row.check_item_id
    const hasEvidence = Boolean(
      row.task_book_evidence_refs?.length || row.subject_evidence_refs?.length,
    )
    return (
      <tr
        key={`${row.check_item_id || index}-${startIndex + index}`}
        className={`border-b border-border/10 cursor-pointer hover:bg-muted/10 transition-colors ${
          isActive ? 'bg-primaryAccent/10 font-medium' : ''
        }`}
        style={useVirtual ? { height: ROW_HEIGHT_PX } : undefined}
        onClick={() => {
          const checkItemId = row.check_item_id
          if (!checkItemId) return
          setActiveRowId(checkItemId)
          onCheckItemClick?.(checkItemId)
        }}
      >
        <td className="max-w-[240px] truncate px-2 py-2 text-primary" title={row.check_item_title}>
          {row.check_item_title || row.check_item_id || '—'}
        </td>
        <td className="px-2 py-2">
          <span className={`inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-medium ${coverageTone(status)}`}>
            {COVERAGE_STATUS_LABELS[status] || status || '—'}
          </span>
        </td>
        <td className="px-2 py-2 text-muted">{JUDGMENT_LABELS[judgment] || judgment || '—'}</td>
        <td className="px-2 py-2 tabular-nums text-muted">{percentConfidence(row.confidence)}</td>
        <td className="px-2 py-2">
          {row.requires_human_confirmation ? (
            <span className="inline-flex rounded-full border border-warning/25 bg-warning/10 px-1.5 py-0.5 text-[9px] font-medium text-warning">
              待审签
            </span>
          ) : (
            <span className="text-muted">—</span>
          )}
        </td>
        <td className="max-w-[160px] truncate px-2 py-2 text-muted" title={(row.risks || []).join('；')}>
          {(row.risks || []).length ? (row.risks || []).join('；') : '—'}
        </td>
        <td className="px-2 py-2">
          {hasEvidence ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onOpenEvidenceCompare?.(row)
              }}
              className="rounded-lg border border-border/25 px-2 py-1 text-[9px] text-primaryAccent hover:border-brand/40"
            >
              对照原文
            </button>
          ) : (
            <span className="text-muted">—</span>
          )}
        </td>
      </tr>
    )
  }

  if (!rows.length) {
    return (
      <div className="rounded-xl border border-border/20 bg-surface p-6 text-center text-[11px] text-muted">
        覆盖矩阵尚未生成。请完成「动态组队符合性审查」后刷新查看。
      </div>
    )
  }

  return (
    <div className="space-y-3" data-testid="review-plus-coverage-tab">
      <ResultSummaryBar
        items={[
          { label: '已闭合', value: metrics.closedCount, tone: 'success' },
          { label: '仅任务书', value: metrics.taskOnlyCount, tone: 'warning' },
          { label: '仅被审材料', value: metrics.subjectOnlyCount, tone: 'warning' },
          { label: '缺失', value: metrics.missingCount, tone: metrics.missingCount > 0 ? 'danger' : 'default' },
          { label: '总行数', value: metrics.rowCount, tone: 'brand' },
        ]}
        hint={`当前筛选显示 ${filteredRows.length} / ${rows.length} 行${useVirtual ? '（已启用虚拟滚动）' : ''}`}
      />

      <div className="flex flex-wrap gap-2">
        <select
          value={coverageFilter}
          onChange={(e) => setCoverageFilter(e.target.value as CoverageFilter)}
          className="min-h-9 rounded-xl border border-border/25 bg-surface px-3 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
          aria-label="覆盖状态筛选"
        >
          <option value="all">全部覆盖状态</option>
          {Object.entries(COVERAGE_STATUS_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        <select
          value={judgmentFilter}
          onChange={(e) => setJudgmentFilter(e.target.value as JudgmentFilter)}
          className="min-h-9 rounded-xl border border-border/25 bg-surface px-3 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
          aria-label="判定筛选"
        >
          <option value="all">全部判定</option>
          {Object.entries(JUDGMENT_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </div>

      <div className="overflow-hidden rounded-xl border border-border/20 bg-surface">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-left text-[10px]">
            <thead className="sticky top-0 z-10 border-b border-border/20 bg-surface">
              <tr className="text-muted">
                <th className="px-2 py-2 font-medium">检查项</th>
                <th className="px-2 py-2 font-medium">覆盖状态</th>
                <th className="px-2 py-2 font-medium">判定</th>
                <th className="px-2 py-2 font-medium">置信度</th>
                <th className="px-2 py-2 font-medium">人工确认</th>
                <th className="px-2 py-2 font-medium">风险</th>
                <th className="px-2 py-2 font-medium">操作</th>
              </tr>
            </thead>
          </table>
        </div>
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="overflow-auto"
          style={{ maxHeight: VIEWPORT_HEIGHT_PX }}
        >
          <div style={useVirtual ? { height: totalHeight, position: 'relative' } : undefined}>
            <table
              className="w-full min-w-[720px] border-collapse text-left text-[10px]"
              style={useVirtual ? { transform: `translateY(${offsetY}px)` } : undefined}
            >
              <tbody>
                {visibleRows.map((row, index) => renderRow(row, index))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
