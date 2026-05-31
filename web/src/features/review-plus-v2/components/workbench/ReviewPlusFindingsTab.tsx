'use client'

import { Fragment, useEffect, useMemo, useState } from 'react'
import { StatusBadge } from '@aqua/ui-core'
import ActionEmptyState from '@/features/review-plus-v2/components/workbench/ActionEmptyState'
import ResultSummaryBar from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import type { ReviewPlusCheckItem, ReviewPlusCoverageMatrixRow, ReviewPlusFinding } from '@/features/review-plus-v2/types'
import {
  COVERAGE_STATUS_LABELS,
  JUDGMENT_LABELS,
  SEVERITY_LABELS,
} from '@/features/review-plus-v2/types'
import { reviewPlusJudgmentTone } from '@/features/review-plus-shared/utils/reviewPlusStatusTone'
import {
  resolveReviewPlusCheckItemTitle,
  resolveReviewPlusFindingTitle,
} from '@/features/review-plus-v2/utils/reviewPlusCheckItemLabel'
import { parseEvidenceRef } from '@/features/review-plus-v2/utils/aeroDesignerWorkbenchUtils'

type SeverityFilter = 'all' | 'critical' | 'major' | 'minor' | 'info'
type JudgmentFilter = 'all' | 'satisfied' | 'not_satisfied' | 'insufficient_evidence' | 'not_applicable' | 'not_checked'
type SortOption = 'severity' | 'judgment' | 'item_no'

const SEVERITY_ORDER: Record<string, number> = { critical: 0, major: 1, minor: 2, info: 3 }
const JUDGMENT_ORDER: Record<string, number> = {
  not_satisfied: 0,
  insufficient_evidence: 1,
  not_checked: 2,
  satisfied: 3,
  not_applicable: 4,
}

interface FindingRow {
  item: ReviewPlusCheckItem
  finding: ReviewPlusFinding
  displayTitle: string
}

function percentConfidence(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n)
  return `${pct}%`
}

function severityClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return 'border-destructive/20 bg-destructive/5 text-destructive'
    case 'major':
      return 'border-warning/20 bg-warning/8 text-warning'
    case 'minor':
      return 'border-info/20 bg-info/8 text-info'
    default:
      return 'border-border/30 bg-muted/10 text-muted'
  }
}

function formatEvidenceSummary(finding: ReviewPlusFinding): string {
  const taskCount = finding.task_book_evidence_refs?.length || 0
  const subjectCount = finding.subject_evidence_refs?.length || 0
  if (taskCount || subjectCount) {
    return `任务书 ${taskCount} · 报告 ${subjectCount}`
  }
  const refs = finding.evidence_refs || []
  if (!refs.length) return '—'
  const parsed = refs.slice(0, 2).map((ref) => {
    const ev = parseEvidenceRef(ref)
    return ev ? `${ev.materialName}:${ev.lineNo}` : ref
  })
  return parsed.join(' / ')
}

function buildFindingRows(
  checkItems: ReviewPlusCheckItem[],
  findings: ReviewPlusFinding[],
  coverageRows: ReviewPlusCoverageMatrixRow[] = [],
): FindingRow[] {
  const findingsByItem = new Map(findings.map((f) => [f.check_item_id, f]))
  const coverageByItem = new Map(
    coverageRows.filter((row) => row.check_item_id).map((row) => [String(row.check_item_id), row]),
  )

  return checkItems.map((item, index) => {
    const existing = findingsByItem.get(item.check_item_id)
    const coverage = coverageByItem.get(item.check_item_id)
    const itemIndex = index + 1
    const finding: ReviewPlusFinding = {
      ...(existing || {
        finding_id: `pending-${item.check_item_id}`,
        check_item_id: item.check_item_id,
        judgment: 'not_checked',
        severity: 'info',
        title: resolveReviewPlusCheckItemTitle(item, itemIndex),
        reasoning: '',
        evidence_refs: [],
        source_quotes: item.source_quote ? [item.source_quote] : [],
        source_quote: item.source_quote,
        confidence: item.confidence,
      }),
      task_book_evidence_refs: existing?.task_book_evidence_refs?.length
        ? existing.task_book_evidence_refs
        : coverage?.task_book_evidence_refs,
      subject_evidence_refs: existing?.subject_evidence_refs?.length
        ? existing.subject_evidence_refs
        : coverage?.subject_evidence_refs,
      coverage_status: existing?.coverage_status || coverage?.coverage_status,
      requires_human_confirmation: existing?.requires_human_confirmation ?? coverage?.requires_human_confirmation,
      checklist_source_material_name: existing?.checklist_source_material_name || coverage?.checklist_source_material_name,
      source_quote: existing?.source_quote || coverage?.source_quote || item.source_quote,
      confidence: existing?.confidence ?? coverage?.confidence ?? item.confidence,
      judgment: existing?.judgment || coverage?.judgment || 'not_checked',
      reasoning: existing?.reasoning || (coverage?.risks || []).join('；') || '',
      recommendation: existing?.recommendation || ((coverage?.risks || []).length ? '请补充证据或人工确认该检查项。' : ''),
    }
    return {
      item,
      finding,
      displayTitle: resolveReviewPlusFindingTitle(finding, item, itemIndex),
    }
  })
}

export default function ReviewPlusFindingsTab({
  checkItems,
  findings,
  coverageRows = [],
  initialJudgmentFilter,
  onOpenEvidenceCompare,
  variant = 'cards',
  onLocateInCoverage,
  highlightCheckItemId,
}: {
  checkItems: ReviewPlusCheckItem[]
  findings: ReviewPlusFinding[]
  coverageRows?: ReviewPlusCoverageMatrixRow[]
  initialJudgmentFilter?: JudgmentFilter
  onOpenEvidenceCompare?: (finding: ReviewPlusFinding) => void
  variant?: 'cards' | 'table' | 'focus'
  onLocateInCoverage?: (checkItemId: string) => void
  highlightCheckItemId?: string
}) {
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all')
  const [judgmentFilter, setJudgmentFilter] = useState<JudgmentFilter>(initialJudgmentFilter || 'all')
  const [sortBy, setSortBy] = useState<SortOption>('severity')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [issuesOnly, setIssuesOnly] = useState(variant === 'focus' && !initialJudgmentFilter)
  const [focusedId, setFocusedId] = useState<string | null>(null)

  const rows = useMemo(
    () => buildFindingRows(checkItems, findings, coverageRows),
    [checkItems, findings, coverageRows],
  )

  useEffect(() => {
    if (highlightCheckItemId) {
      const row = rows.find((r) => r.finding.check_item_id === highlightCheckItemId || r.item.check_item_id === highlightCheckItemId)
      if (row) {
        setFocusedId(row.finding.finding_id)
        setIssuesOnly(false)
      }
    }
  }, [highlightCheckItemId, rows])

  useEffect(() => {
    if (initialJudgmentFilter) {
      setJudgmentFilter(initialJudgmentFilter)
    }
  }, [initialJudgmentFilter])

  const counts = useMemo(() => {
    const tally = { satisfied: 0, not_satisfied: 0, insufficient_evidence: 0, not_checked: 0, not_applicable: 0 }
    for (const row of rows) {
      const j = String(row.finding.judgment || 'not_checked')
      if (j in tally) tally[j as keyof typeof tally] += 1
    }
    return tally
  }, [rows])

  const filteredRows = useMemo(() => {
    const filtered = rows.filter(({ finding }) => {
      const sev = String(finding.severity || '').toLowerCase() as SeverityFilter
      const jud = String(finding.judgment || 'not_checked') as JudgmentFilter
      const sevMatch = severityFilter === 'all' || sev === severityFilter
      const judMatch = judgmentFilter === 'all' || jud === judgmentFilter
      const issuesMatch = !issuesOnly || variant !== 'focus' || (
        jud === 'not_satisfied'
        || jud === 'insufficient_evidence'
        || Boolean(finding.requires_human_confirmation)
      )
      return sevMatch && judMatch && issuesMatch
    })

    filtered.sort((a, b) => {
      if (sortBy === 'severity') {
        const sevA = SEVERITY_ORDER[String(a.finding.severity || '')] ?? 999
        const sevB = SEVERITY_ORDER[String(b.finding.severity || '')] ?? 999
        return sevA - sevB
      }
      if (sortBy === 'judgment') {
        const judA = JUDGMENT_ORDER[String(a.finding.judgment || '')] ?? 999
        const judB = JUDGMENT_ORDER[String(b.finding.judgment || '')] ?? 999
        return judA - judB
      }
      if (sortBy === 'item_no') {
        return (a.item.item_no || '').localeCompare(b.item.item_no || '', 'zh-CN')
      }
      return 0
    })

    return filtered
  }, [rows, severityFilter, judgmentFilter, sortBy, issuesOnly, variant])

  useEffect(() => {
    if (variant !== 'focus') return
    if (focusedId && filteredRows.some((row) => row.finding.finding_id === focusedId)) return
    setFocusedId(filteredRows[0]?.finding.finding_id || null)
  }, [filteredRows, focusedId, variant])

  const focusedRow = useMemo(
    () => filteredRows.find((row) => row.finding.finding_id === focusedId) || null,
    [filteredRows, focusedId],
  )

  const issueCount = useMemo(
    () => rows.filter(({ finding }) => {
      const jud = String(finding.judgment || '')
      return jud === 'not_satisfied' || jud === 'insufficient_evidence' || finding.requires_human_confirmation
    }).length,
    [rows],
  )

  if (!checkItems.length) {
    return (
      <ActionEmptyState
        title="暂无审查记录"
        description="上传检查单或检查需求并启动审查后，将在此展示逐项判定与证据引用。"
        hint="可先查看送审包与审查流程，确认检查项已加载。"
      />
    )
  }

  const filterBar = (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex flex-wrap gap-1.5">
        {[
          ['all', '全部判定'],
          ['not_satisfied', '不满足'],
          ['insufficient_evidence', '证据不足'],
          ['satisfied', '满足'],
          ['not_checked', '未检查'],
          ['not_applicable', '不适用'],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setJudgmentFilter(key as JudgmentFilter)}
            className={`rounded-full px-2.5 py-1 text-[10px] transition-colors ${
              judgmentFilter === key
                ? 'bg-primaryAccent text-white'
                : 'bg-background text-muted hover:bg-muted/15'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <select
        value={severityFilter}
        onChange={(e) => setSeverityFilter(e.target.value as SeverityFilter)}
        className="min-h-9 rounded-xl border border-border/25 bg-surface px-3 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
        aria-label="严重度筛选"
      >
        <option value="all">全部严重度</option>
        <option value="critical">关键</option>
        <option value="major">主要</option>
        <option value="minor">一般</option>
        <option value="info">提示</option>
      </select>

      <select
        value={sortBy}
        onChange={(e) => setSortBy(e.target.value as SortOption)}
        className="min-h-9 rounded-xl border border-border/25 bg-surface px-3 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
        aria-label="排序方式"
      >
        <option value="severity">按严重度</option>
        <option value="judgment">按判定</option>
        <option value="item_no">按项号</option>
      </select>

      <span className="text-[10px] text-muted">当前显示 {filteredRows.length} / {rows.length} 项</span>
    </div>
  )

  const renderExpandedDetail = (row: FindingRow) => {
    const { item, finding } = row
    const judgment = String(finding.judgment || 'not_checked')
    const previewQuote = finding.source_quote || finding.source_quotes?.[0] || item.source_quote

    return (
      <div className="space-y-2 border-t border-border/15 bg-background-secondary/20 px-3 py-3">
        {item.requirement_text ? (
          <div>
            <div className="text-[10px] font-medium text-muted">检查要求</div>
            <p className="mt-1 text-[11px] leading-relaxed text-primary/85">{item.requirement_text}</p>
          </div>
        ) : null}

        {finding.reasoning ? (
          <div>
            <div className="text-[10px] font-medium text-muted">判定推理</div>
            <p className="mt-1 text-[11px] leading-relaxed text-primary/85">{finding.reasoning}</p>
          </div>
        ) : null}

        {previewQuote ? (
          <div>
            <div className="text-[10px] font-medium text-muted">源文摘录</div>
            <p className="mt-1 rounded-lg border border-warning/20 bg-warning/8 px-2 py-1.5 text-[10px] leading-relaxed text-primary">
              {previewQuote}
            </p>
          </div>
        ) : null}

        {finding.recommendation ? (
          <div>
            <div className="text-[10px] font-medium text-muted">整改建议</div>
            <p className="mt-1 text-[11px] leading-relaxed text-primary/85">{finding.recommendation}</p>
          </div>
        ) : null}

        {item.acceptance_criteria ? (
          <div>
            <div className="text-[10px] font-medium text-muted">验收准则</div>
            <p className="mt-1 text-[10px] leading-relaxed text-muted">{item.acceptance_criteria}</p>
          </div>
        ) : null}

        {(finding.evidence_refs?.length || finding.task_book_evidence_refs?.length || finding.subject_evidence_refs?.length) ? (
          <div>
            <div className="text-[10px] font-medium text-muted">证据定位</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {[...(finding.task_book_evidence_refs || []), ...(finding.subject_evidence_refs || []), ...(finding.evidence_refs || [])]
                .filter((ref, idx, arr) => arr.indexOf(ref) === idx)
                .slice(0, 8)
                .map((ref, refIndex) => (
                  <span key={`${finding.finding_id}-${ref}-${refIndex}`} className="inline-flex rounded-md border border-border/20 bg-background px-2 py-0.5 text-[9px] text-primaryAccent">
                    {ref}
                  </span>
                ))}
            </div>
          </div>
        ) : null}
      </div>
    )
  }

  const renderReadingPane = (row: FindingRow) => {
    const { item, finding } = row
    const judgment = String(finding.judgment || 'not_checked')
    const severity = String(finding.severity || 'info').toLowerCase()
    const previewQuote = finding.source_quote || finding.source_quotes?.[0] || item.source_quote
    const hasEvidence = Boolean(
      finding.evidence_refs?.length
      || finding.task_book_evidence_refs?.length
      || finding.subject_evidence_refs?.length,
    )

    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 space-y-2 border-b border-border/15 pb-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${severityClass(severity)}`}>
              {SEVERITY_LABELS[severity] || severity}
            </span>
            <StatusBadge tone={reviewPlusJudgmentTone(judgment)}>
              {JUDGMENT_LABELS[judgment] || judgment}
            </StatusBadge>
            {item.item_no ? (
              <span className="text-[11px] text-muted">项号 {item.item_no}</span>
            ) : null}
            <span className="text-[11px] text-muted">置信 {percentConfidence(finding.confidence ?? item.confidence)}</span>
            {finding.requires_human_confirmation ? (
              <span className="inline-flex rounded-full border border-warning/25 bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning">
                待审签
              </span>
            ) : null}
          </div>
          <h3 className="text-[15px] font-medium leading-snug text-primary">
            {row.displayTitle}
          </h3>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto py-4">
          {item.requirement_text ? (
            <div>
              <div className="text-[11px] font-medium text-muted">检查要求</div>
              <p className="mt-2 text-[13px] leading-7 text-primary/90">{item.requirement_text}</p>
            </div>
          ) : null}

          {finding.reasoning ? (
            <div>
              <div className="text-[11px] font-medium text-muted">判定推理</div>
              <p className="mt-2 text-[13px] leading-7 text-primary/90">{finding.reasoning}</p>
            </div>
          ) : null}

          {previewQuote ? (
            <div>
              <div className="text-[11px] font-medium text-muted">源文摘录</div>
              <p className="mt-2 rounded-xl border border-warning/20 border-l-4 border-l-warning bg-warning/8 px-3 py-3 text-[12px] leading-relaxed text-primary">
                {previewQuote}
              </p>
            </div>
          ) : null}

          {finding.recommendation ? (
            <div>
              <div className="text-[11px] font-medium text-muted">整改建议</div>
              <p className="mt-2 text-[13px] leading-7 text-primary/90">{finding.recommendation}</p>
            </div>
          ) : null}

          {item.acceptance_criteria ? (
            <div>
              <div className="text-[11px] font-medium text-muted">验收准则</div>
              <p className="mt-2 text-[12px] leading-relaxed text-muted">{item.acceptance_criteria}</p>
            </div>
          ) : null}
        </div>

        <div className="shrink-0 border-t border-border/15 pt-4 flex gap-2">
          {hasEvidence ? (
            <button
              type="button"
              onClick={() => onOpenEvidenceCompare?.(finding)}
              className="rounded-2xl bg-brand px-4 py-2.5 text-[11px] font-medium text-white transition-colors hover:bg-brand/90 motion-safe:active:scale-[0.98]"
              data-testid="review-plus-findings-open-evidence"
            >
              对照原文证据
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => onLocateInCoverage?.(finding.check_item_id)}
            className="rounded-2xl border border-border/20 bg-surface px-4 py-2.5 text-[11px] font-medium text-muted hover:text-primary transition-colors hover:bg-muted/10 motion-safe:active:scale-[0.98]"
            data-testid="review-plus-findings-locate-coverage"
          >
            在覆盖矩阵中定位
          </button>
        </div>
      </div>
    )
  }

  if (variant === 'focus') {
    return (
      <div className="flex h-full min-h-[520px] flex-col" data-testid="review-plus-findings-tab">
        <div className="mb-3 flex shrink-0 flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[13px] font-medium text-primary">审查记录</p>
            <p className="text-[11px] text-muted">
              {issueCount} 项需处理 · 共 {rows.length} 项
              {filteredRows.length !== rows.length ? ` · 当前显示 ${filteredRows.length} 项` : ''}
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setIssuesOnly(true)}
              className={`rounded-full px-3 py-1.5 text-[10px] transition-colors ${
                issuesOnly ? 'bg-primaryAccent text-white' : 'bg-background text-muted hover:bg-muted/15'
              }`}
            >
              需处理
            </button>
            <button
              type="button"
              onClick={() => setIssuesOnly(false)}
              className={`rounded-full px-3 py-1.5 text-[10px] transition-colors ${
                !issuesOnly ? 'bg-primaryAccent text-white' : 'bg-background text-muted hover:bg-muted/15'
              }`}
            >
              全部
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 gap-4 overflow-hidden">
          <div className="w-[280px] shrink-0 overflow-y-auto border-r border-border/15 pr-2">
            {filteredRows.length ? filteredRows.map((row) => {
              const { item, finding, displayTitle } = row
              const judgment = String(finding.judgment || 'not_checked')
              const isFocused = focusedId === finding.finding_id
              return (
                <button
                  key={finding.finding_id}
                  type="button"
                  onClick={() => setFocusedId(finding.finding_id)}
                  className={`mb-1.5 w-full rounded-xl border px-3 py-2.5 text-left transition-colors ${
                    isFocused
                      ? 'border-primaryAccent bg-primaryAccent/8 ring-1 ring-primaryAccent/25'
                      : 'border-border/15 bg-surface hover:border-brand/30'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {item.item_no ? (
                      <span className="text-[10px] tabular-nums text-muted">{item.item_no}</span>
                    ) : null}
                    <StatusBadge tone={reviewPlusJudgmentTone(judgment)}>
                      {JUDGMENT_LABELS[judgment] || judgment}
                    </StatusBadge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[11px] font-medium leading-relaxed text-primary">
                    {displayTitle}
                  </p>
                </button>
              )
            }) : (
              <div className="rounded-xl border border-border/20 bg-surface p-4 text-center text-[11px] text-muted">
                当前筛选条件下无审查记录
              </div>
            )}
          </div>

          <div className="min-w-0 flex-1 overflow-hidden rounded-2xl border border-border/20 bg-surface p-5 shadow-soft">
            {focusedRow ? renderReadingPane(focusedRow) : (
              <div className="flex h-full items-center justify-center text-[11px] text-muted">
                请选择左侧条目查看详细判定与建议
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (variant === 'table') {
    return (
      <div className="space-y-3" data-testid="review-plus-findings-tab">
        <ResultSummaryBar
          items={[
            { label: '检查项', value: rows.length, tone: 'brand' },
            { label: '不满足', value: counts.not_satisfied, tone: counts.not_satisfied > 0 ? 'danger' : 'default' },
            { label: '证据不足', value: counts.insufficient_evidence, tone: counts.insufficient_evidence > 0 ? 'warning' : 'default' },
            { label: '满足', value: counts.satisfied, tone: 'success' },
            { label: '未检查', value: counts.not_checked, tone: counts.not_checked > 0 ? 'warning' : 'default' },
          ]}
          hint="展开行查看推理、摘录与整改建议；使用「对照原文」打开证据蒙层。"
        />

        {filterBar}

        <div className="overflow-hidden rounded-xl border border-border/20 bg-surface">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] border-collapse text-left text-[10px]">
              <thead className="sticky top-0 z-10 border-b border-border/20 bg-surface text-muted">
                <tr>
                  <th className="px-2 py-2 font-medium">项号</th>
                  <th className="px-2 py-2 font-medium">检查项</th>
                  <th className="px-2 py-2 font-medium">判定</th>
                  <th className="px-2 py-2 font-medium">严重度</th>
                  <th className="px-2 py-2 font-medium">置信度</th>
                  <th className="px-2 py-2 font-medium">覆盖</th>
                  <th className="px-2 py-2 font-medium">审签</th>
                  <th className="px-2 py-2 font-medium">证据</th>
                  <th className="px-2 py-2 font-medium">结论摘要</th>
                  <th className="px-2 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => {
                  const { item, finding, displayTitle } = row
                  const judgment = String(finding.judgment || 'not_checked')
                  const severity = String(finding.severity || 'info').toLowerCase()
                  const isExpanded = expandedId === finding.finding_id
                  const summaryText = finding.reasoning
                    || finding.recommendation
                    || item.requirement_text
                    || '—'
                  const coverage = String(finding.coverage_status || '')
                  const hasEvidence = Boolean(
                    finding.evidence_refs?.length
                    || finding.task_book_evidence_refs?.length
                    || finding.subject_evidence_refs?.length,
                  )

                  return (
                    <Fragment key={finding.finding_id}>
                      <tr
                        className="cursor-pointer border-b border-border/10 transition-colors hover:bg-muted/10"
                        onClick={() => {
                          setExpandedId((prev) => (prev === finding.finding_id ? null : finding.finding_id))
                        }}
                      >
                        <td className="whitespace-nowrap px-2 py-2 tabular-nums text-muted">{item.item_no || '—'}</td>
                        <td className="max-w-[220px] px-2 py-2 text-primary" title={displayTitle}>
                          <div className="truncate font-medium">{displayTitle}</div>
                          {finding.checklist_source_material_name ? (
                            <div className="truncate text-[9px] text-muted">来源 {finding.checklist_source_material_name}</div>
                          ) : item.source_material_name ? (
                            <div className="truncate text-[9px] text-muted">来源 {item.source_material_name}</div>
                          ) : null}
                        </td>
                        <td className="px-2 py-2">
                          <StatusBadge tone={reviewPlusJudgmentTone(judgment)}>
                            {JUDGMENT_LABELS[judgment] || judgment}
                          </StatusBadge>
                        </td>
                        <td className="px-2 py-2">
                          <span className={`inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-medium ${severityClass(severity)}`}>
                            {SEVERITY_LABELS[severity] || severity}
                          </span>
                        </td>
                        <td className="px-2 py-2 tabular-nums text-muted">{percentConfidence(finding.confidence ?? item.confidence)}</td>
                        <td className="px-2 py-2 text-muted">
                          {coverage ? (COVERAGE_STATUS_LABELS[coverage] || coverage) : '—'}
                        </td>
                        <td className="px-2 py-2">
                          {finding.requires_human_confirmation ? (
                            <span className="inline-flex rounded-full border border-warning/25 bg-warning/10 px-1.5 py-0.5 text-[9px] font-medium text-warning">
                              待审签
                            </span>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-muted">{formatEvidenceSummary(finding)}</td>
                        <td className="max-w-[240px] truncate px-2 py-2 text-muted" title={summaryText}>
                          {summaryText}
                        </td>
                        <td className="px-2 py-2">
                          {hasEvidence ? (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                onOpenEvidenceCompare?.(finding)
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
                      {isExpanded ? (
                        <tr>
                          <td colSpan={10} className="p-0">
                            {renderExpandedDetail(row)}
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {!filteredRows.length ? (
          <div className="rounded-xl border border-border/20 bg-surface p-6 text-center text-[11px] text-muted">
            当前筛选条件下无审查记录，请调整过滤器。
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="max-w-5xl space-y-3" data-testid="review-plus-findings-tab">
      <ResultSummaryBar
        items={[
          { label: '满足', value: counts.satisfied, tone: 'success' },
          { label: '不满足', value: counts.not_satisfied, tone: counts.not_satisfied > 0 ? 'danger' : 'default' },
          { label: '证据不足', value: counts.insufficient_evidence, tone: counts.insufficient_evidence > 0 ? 'warning' : 'default' },
          { label: '未检查', value: counts.not_checked, tone: 'default' },
          { label: '不适用', value: counts.not_applicable, tone: 'default' },
        ]}
        hint="符合性审查完成后可在此核对逐项结论与推理依据。"
      />

      <div className="flex flex-wrap gap-2 rounded-xl border border-border/15 bg-background px-3 py-2">
        {(['critical', 'major', 'minor', 'info'] as const).map((sev) => {
          const c = rows.filter(({ finding }) => String(finding.severity || '').toLowerCase() === sev).length
          return c > 0 ? (
            <span key={sev} className={`rounded-full px-2 py-0.5 text-[10px] ${severityClass(sev)}`}>
              {SEVERITY_LABELS[sev]}: {c}
            </span>
          ) : null
        })}
      </div>

      {filterBar}

      <div className="space-y-2">
        {filteredRows.length ? filteredRows.map((row) => {
          const { item, finding, displayTitle } = row
          const judgment = String(finding.judgment || 'not_checked')
          const severity = String(finding.severity || 'info').toLowerCase()
          const hasEvidence = Boolean(
            finding.evidence_refs?.length
            || finding.task_book_evidence_refs?.length
            || finding.subject_evidence_refs?.length,
          )
          return (
            <details
              key={finding.finding_id}
              className="group aq-soft-panel rounded-lg border border-border/15 p-3 transition-colors hover:border-primaryAccent/30"
            >
              <summary className="flex cursor-pointer list-none flex-wrap items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded border px-1.5 py-0.5 text-[9px] font-medium ${severityClass(severity)}`}>
                      {SEVERITY_LABELS[severity] || severity}
                    </span>
                    <StatusBadge tone={reviewPlusJudgmentTone(judgment)}>
                      {JUDGMENT_LABELS[judgment] || judgment}
                    </StatusBadge>
                    {item.item_no ? (
                      <span className="text-[10px] text-muted">项号 {item.item_no}</span>
                    ) : null}
                    <span className="text-[10px] text-muted">置信 {percentConfidence(finding.confidence ?? item.confidence)}</span>
                  </div>
                  <h3 className="mt-1.5 text-sm font-medium text-primary">{displayTitle}</h3>
                  <p className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-muted">
                    {finding.reasoning || item.requirement_text || '暂无判定说明'}
                  </p>
                </div>
              </summary>

              {renderExpandedDetail(row)}

              {hasEvidence ? (
                <div className="mt-2 border-t border-border/10 pt-2">
                  <button
                    type="button"
                    onClick={() => onOpenEvidenceCompare?.(finding)}
                    className="rounded-xl border border-border/25 px-3 py-1.5 text-[10px] font-medium text-primaryAccent hover:border-brand/40"
                  >
                    对照原文证据
                  </button>
                </div>
              ) : null}
            </details>
          )
        }) : (
          <div className="aq-soft-panel space-y-2 rounded-xl p-8 text-center">
            <p className="text-[13px] font-medium text-primary">当前筛选条件下无审查记录</p>
            <p className="text-[11px] leading-6 text-primary/70">请调整过滤器或查看全部检查项。</p>
          </div>
        )}
      </div>
    </div>
  )
}
