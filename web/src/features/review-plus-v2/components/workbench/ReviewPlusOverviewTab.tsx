'use client'

import { useMemo } from 'react'
import type { ReactNode, Ref } from 'react'
import { FileSearch, FileText, ListChecks, Network, Users } from 'lucide-react'
import ReviewPlusFlowWorkbenchView from '@/features/review-plus-v2/components/ReviewPlusFlowWorkbenchView'
import ReviewPlusHarnessTeamPanel from '@/features/review-plus-shared/components/harness/ReviewPlusHarnessTeamPanel'
import { hasHarnessArtifacts } from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'
import ReviewPlusConclusionPanel, {
  type ReviewPlusConclusionPanelHandle,
} from '@/features/review-plus-v2/components/workbench/ReviewPlusConclusionPanel'
import ResultSummaryBar from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { JUDGMENT_LABELS, SEVERITY_LABELS } from '@/features/review-plus-v2/types'
import type { ReviewPlusWorkbenchTabKey } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import {
  REVIEW_PLUS_VERDICT_COLORS,
  REVIEW_PLUS_VERDICT_LABELS,
  formatReviewPlusPassRate,
  inferReviewPlusVerdict,
} from '@/features/review-plus-v2/utils/reviewPlusConclusion'
import { hasReviewPlusReviewStarted } from '@/features/review-plus-v2/utils/reviewPlusUx'

const PRIORITY_FINDINGS_LIMIT = 3

type Tone = 'default' | 'brand' | 'success' | 'warning' | 'danger'

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function textValue(value: unknown, fallback = '—'): string {
  const text = String(value ?? '').trim()
  return text || fallback
}

function percent(value: unknown): string {
  const n = Number(value || 0)
  if (!Number.isFinite(n)) return '0%'
  return `${Math.round((n <= 1 ? n * 100 : n))}%`
}

function StatusPill({ label, tone = 'default' }: { label: string; tone?: Tone }) {
  const cls = tone === 'success' ? 'border-positive/20 bg-positive/8 text-positive'
    : tone === 'warning' ? 'border-warning/20 bg-warning/8 text-warning'
      : tone === 'danger' ? 'border-destructive/20 bg-destructive/8 text-destructive'
        : tone === 'brand' ? 'border-primaryAccent/20 bg-primaryAccent/8 text-primaryAccent'
          : 'border-border/25 bg-muted/8 text-muted'
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium ${cls}`}>{label}</span>
}

function SectionHeader({
  icon,
  title,
  meta,
}: {
  icon: ReactNode
  title: string
  meta?: string
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border/20 bg-background text-primaryAccent">
          {icon}
        </span>
        <h2 className="truncate text-[13px] font-medium text-primary">{title}</h2>
      </div>
      {meta ? <span className="shrink-0 text-[10px] text-muted">{meta}</span> : null}
    </div>
  )
}

export default function ReviewPlusOverviewTab({
  task,
  reviewId,
  isExecuting = false,
  visibleTabs,
  reportMarkdown = '',
  showConclusionPanel = false,
  conclusionPanelRef,
  onOpenTab,
  onExpandFullReport,
}: {
  task: ReviewPlusTaskDetail
  reviewId: string
  isExecuting?: boolean
  visibleTabs?: Set<ReviewPlusWorkbenchTabKey>
  reportMarkdown?: string
  showConclusionPanel?: boolean
  conclusionPanelRef?: Ref<ReviewPlusConclusionPanelHandle>
  onOpenTab: (tab: Exclude<ReviewPlusWorkbenchTabKey, 'flow' | 'report'>) => void
  onExpandFullReport?: () => void
}) {
  const report = task.report
  const traceSummary = asRecord(asRecord(task.traceability_result).summary)
  const crossDocItems = task.cross_document_review_items || []
  const taskStatus = String(task.status || '')
  const reviewStarted = hasReviewPlusReviewStarted(task)
  const showProcessReplay = reviewStarted && taskStatus === 'completed'
  const verdict = inferReviewPlusVerdict(report?.conclusion)

  const flowWorkbenchProps = {
    reviewId,
    task,
    visibleTabs,
    bannerVariant: 'workbench' as const,
    showHeaderMetrics: false,
    layoutMode: 'workbench' as const,
    onOpenRelatedTab: (tab: ReviewPlusWorkbenchTabKey) => {
      if (tab === 'flow' || tab === 'report') return
      onOpenTab(tab)
    },
  }

  const findingCounts = useMemo(() => {
    const counts = { satisfied: 0, not_satisfied: 0, insufficient_evidence: 0, not_checked: 0, not_applicable: 0 }
    for (const item of task.check_items || []) {
      counts.not_checked += 1
    }
    for (const finding of task.findings || []) {
      const judgment = String(finding.judgment || 'not_checked') as keyof typeof counts
      if (judgment in counts) {
        counts[judgment] += 1
        if (counts.not_checked > 0) counts.not_checked -= 1
      }
    }
    return counts
  }, [task.check_items, task.findings])

  const priorityFindingsAll = useMemo(() => {
    return (task.findings || [])
      .filter((finding) => ['critical', 'major'].includes(String(finding.severity || '').toLowerCase())
        || ['not_satisfied', 'insufficient_evidence'].includes(String(finding.judgment || '')))
  }, [task.findings])

  const priorityFindings = priorityFindingsAll.slice(0, PRIORITY_FINDINGS_LIMIT)
  const hasMorePriorityFindings = priorityFindingsAll.length > PRIORITY_FINDINGS_LIMIT

  const openCrossItems = crossDocItems.filter((item) => !['closed', 'resolved'].includes(String(item.status || 'open'))).length
  const notSatisfied = report?.not_satisfied_count ?? findingCounts.not_satisfied
  const insufficient = report?.insufficient_evidence_count ?? findingCounts.insufficient_evidence
  const satisfied = report?.satisfied_count ?? findingCounts.satisfied
  const totalCheckItems = report?.total_check_items ?? task.check_items?.length ?? 0
  const passRate = formatReviewPlusPassRate(totalCheckItems, satisfied)

  const summaryItems = showConclusionPanel && report
    ? [
      { label: '检查项', value: totalCheckItems, tone: 'brand' as const },
      { label: '满足', value: satisfied, tone: 'success' as const },
      { label: '不满足', value: notSatisfied, tone: notSatisfied > 0 ? 'danger' as const : 'default' as const },
      { label: '证据不足', value: insufficient, tone: insufficient > 0 ? 'warning' as const : 'default' as const },
      { label: '通过率', value: passRate, tone: 'brand' as const },
      { label: '跨文档待处理', value: openCrossItems, tone: openCrossItems > 0 ? 'danger' as const : 'success' as const },
    ]
    : [
      { label: '不满足', value: notSatisfied, tone: notSatisfied > 0 ? 'danger' as const : 'success' as const },
      { label: '证据不足', value: insufficient, tone: insufficient > 0 ? 'warning' as const : 'default' as const },
      { label: '跨文档待处理', value: openCrossItems, tone: openCrossItems > 0 ? 'danger' as const : 'success' as const },
      { label: '检查项', value: task.check_items?.length || 0, tone: 'brand' as const },
    ]

  const summaryHint = showConclusionPanel && report?.summary
    ? report.summary
    : report?.conclusion || report?.summary || task.scenario_reason || '汇总本轮审查结论与建议优先处理的问题。'

  return (
    <div className="max-w-7xl space-y-3 p-1">
      {showConclusionPanel && report?.conclusion ? (
        <section className="aq-soft-panel rounded-xl p-4">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <h2 className="text-[13px] font-medium text-primary">审查结论</h2>
              <p className="mt-1 text-[12px] leading-relaxed text-primary">{report.conclusion}</p>
            </div>
            {verdict ? (
              <div className={`shrink-0 rounded-lg border px-3 py-1.5 text-center ${REVIEW_PLUS_VERDICT_COLORS[verdict]}`}>
                <div className="text-[10px] font-medium">{REVIEW_PLUS_VERDICT_LABELS[verdict]}</div>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      <ResultSummaryBar items={summaryItems} hint={summaryHint} />

      <div className="flex flex-wrap gap-2">
        {showConclusionPanel ? (
          <button
            type="button"
            onClick={() => onExpandFullReport?.()}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-2xl bg-brand px-4 text-[11px] font-medium text-white motion-safe:active:scale-[0.98]"
            data-testid="review-plus-expand-full-report"
          >
            <FileText size={14} />
            展开完整报告
          </button>
        ) : null}
        {notSatisfied > 0 ? (
          <button
            type="button"
            onClick={() => onOpenTab('findings')}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-2xl border border-destructive/25 px-4 text-[11px] font-medium text-destructive hover:bg-destructive/5"
          >
            <ListChecks size={14} />
            查看全部审查记录
          </button>
        ) : null}
      </div>

      {showProcessReplay ? (
        <details className="aq-soft-panel overflow-hidden rounded-xl">
          <summary className="cursor-pointer list-none border-b border-border/15 px-4 py-3 text-[11px] font-medium text-primary">
            查看审查流程回放
          </summary>
          <ReviewPlusFlowWorkbenchView
            {...flowWorkbenchProps}
            isExecuting={false}
            showCurrentStepBanner={false}
          />
        </details>
      ) : null}

      <section className="aq-soft-panel rounded-xl p-4">
        <SectionHeader
          icon={<ListChecks size={15} />}
          title="建议优先处理"
          meta={priorityFindingsAll.length ? `${Math.min(priorityFindingsAll.length, PRIORITY_FINDINGS_LIMIT)} / ${priorityFindingsAll.length} 项` : '无'}
        />
        {priorityFindings.length ? (
          <div className="mt-3 space-y-2">
            {priorityFindings.map((finding) => {
              const severity = String(finding.severity || 'info').toLowerCase()
              const judgment = String(finding.judgment || '')
              return (
                <button
                  key={finding.finding_id}
                  type="button"
                  onClick={() => onOpenTab('findings')}
                  className="w-full rounded-lg border border-border/15 bg-background p-3 text-left transition-colors hover:border-primaryAccent/30 hover:bg-primaryAccent/5"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <StatusPill label={SEVERITY_LABELS[severity] || severity} tone={severity === 'critical' ? 'danger' : severity === 'major' ? 'warning' : 'default'} />
                    <StatusPill label={JUDGMENT_LABELS[judgment] || judgment || '—'} tone={judgment === 'not_satisfied' ? 'danger' : judgment === 'insufficient_evidence' ? 'warning' : 'default'} />
                  </div>
                  <div className="mt-1.5 line-clamp-2 text-[12px] font-medium text-primary">{finding.title || '未命名审查发现'}</div>
                  {finding.reasoning ? <p className="mt-1 line-clamp-2 text-[10px] leading-5 text-muted">{finding.reasoning}</p> : null}
                </button>
              )
            })}
            {hasMorePriorityFindings ? (
              <button
                type="button"
                onClick={() => onOpenTab('findings')}
                className="w-full rounded-lg border border-border/20 bg-background px-3 py-2 text-[11px] font-medium text-primaryAccent transition-colors hover:border-primaryAccent/30 hover:bg-primaryAccent/5"
                data-testid="review-plus-view-all-findings"
              >
                查看全部 {priorityFindingsAll.length} 项
              </button>
            ) : null}
          </div>
        ) : (
          <p className="mt-3 rounded-lg border border-border/20 bg-background p-4 text-[11px] text-muted">
            {showConclusionPanel
              ? '未发现需要优先处理的不满足项或主要问题，可展开完整报告确认结论。'
              : '审查进行中，完成后将在此汇总建议优先处理的问题。'}
          </p>
        )}
      </section>

      <div className="grid gap-3 sm:grid-cols-2">
        <button type="button" onClick={() => onOpenTab('cross_doc')} className="aq-soft-panel rounded-xl p-4 text-left transition-colors hover:border-primaryAccent/30">
          <SectionHeader icon={<FileSearch size={15} />} title="跨文档一致性" meta={`${openCrossItems} 项待处理`} />
          <p className="mt-2 text-[11px] leading-relaxed text-muted">任务书、检查单与报告之间的指标、版本与引用一致性问题。</p>
        </button>
        <button type="button" onClick={() => onOpenTab('traceability')} className="aq-soft-panel rounded-xl p-4 text-left transition-colors hover:border-primaryAccent/30">
          <SectionHeader icon={<Network size={15} />} title="需求闭环" meta={`闭合 ${percent(traceSummary.design_closure_coverage)}`} />
          <p className="mt-2 text-[11px] leading-relaxed text-muted">
            追溯链 {textValue(traceSummary.trace_link_count, '0')} 条 · 缺口 {textValue(traceSummary.closure_gap_count, '0')}
          </p>
        </button>
      </div>

      {hasHarnessArtifacts(task) && !showConclusionPanel ? (
        <section className="aq-soft-panel rounded-xl p-4">
          <SectionHeader icon={<Users size={15} />} title="动态组队与覆盖" meta="符合性审查" />
          <div className="mt-3">
            <ReviewPlusHarnessTeamPanel
              task={task}
              onViewFindings={() => onOpenTab('findings')}
              onOpenCoverage={() => onOpenTab('coverage')}
            />
          </div>
        </section>
      ) : null}

      {!showConclusionPanel ? (
        <section className="aq-soft-panel rounded-xl p-4">
          <SectionHeader icon={<ListChecks size={15} />} title="符合性统计" />
          <div className="mt-3 grid gap-2 sm:grid-cols-4">
            {[
              { label: '满足', value: satisfied, tone: 'text-positive' },
              { label: '不满足', value: notSatisfied, tone: 'text-destructive' },
              { label: '证据不足', value: insufficient, tone: 'text-warning' },
              { label: '未检查', value: report?.not_checked_count ?? findingCounts.not_checked, tone: 'text-muted' },
            ].map((item) => (
              <button
                key={item.label}
                type="button"
                onClick={() => onOpenTab('findings')}
                className="rounded-lg border border-border/20 bg-background p-3 text-left transition-colors hover:border-primaryAccent/30 hover:bg-primaryAccent/5"
              >
                <div className="text-[10px] text-muted">{item.label}</div>
                <div className={`mt-1 text-xl font-medium tabular-nums ${item.tone}`}>{item.value}</div>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {showConclusionPanel ? (
        <ReviewPlusConclusionPanel
          ref={conclusionPanelRef}
          task={task}
          markdown={reportMarkdown}
        />
      ) : null}
    </div>
  )
}
