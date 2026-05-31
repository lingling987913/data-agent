'use client'

import { useMemo, useRef, type ReactNode } from 'react'
import MarkdownRenderer from '@aqua/ui-core/typography/MarkdownRenderer'
import { FileText, ListChecks } from 'lucide-react'
import ExecutionMetricsPanel from '@/features/super-agent/components/ExecutionMetricsPanel'
import SmartCommitteeDiagnosticsCard from '@/features/super-agent/components/SmartCommitteeDiagnosticsCard'
import ResultSummaryBar from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import {
  REVIEW_PLUS_VERDICT_COLORS,
  REVIEW_PLUS_VERDICT_LABELS,
} from '@/features/review-plus-v2/utils/reviewPlusConclusion'
import type { MaterialClassification, SuperAgentRun } from '@/features/super-agent/types'
import type { SuperAgentResultExplainability } from '@/features/super-agent/utils/superAgentProcessingViewModel'
import {
  buildFallbackOverviewMetrics,
  type ReviewIssueItem,
  type ReviewResultSummary,
} from '@/features/super-agent/utils/superAgentResultOverview'

const PRIORITY_FINDINGS_LIMIT = 3

function ResultSection({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-border/15 bg-background/70 p-4">
      <h3 className="text-[12px] font-semibold text-primary">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function ParsedMaterialsPanel({ result }: { result: SuperAgentResultExplainability }) {
  if (!result.materials.length) {
    return (
      <ResultSection title="文档解析效果">
        <div className="rounded-lg border border-border/10 bg-surface px-3 py-3 text-[11px] text-muted">
          暂无逐文件解析明细；本次检查范围：{result.checkedScope.join('、') || '暂无结构化统计'}。
        </div>
      </ResultSection>
    )
  }
  return (
    <ResultSection title="文档解析效果">
      <div className="grid gap-2 md:grid-cols-2">
        {result.materials.map((material) => (
          <article key={material.id} className="rounded-lg border border-border/10 bg-surface px-3 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-[12px] font-medium text-primary">{material.name}</div>
                <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-muted">
                  <span>{material.parseStatus || '已解析'}</span>
                  {material.role ? <span>{material.role}</span> : null}
                  {material.parser ? <span>{material.parser}</span> : null}
                </div>
              </div>
              {material.roleConfidence !== undefined ? (
                <span className="shrink-0 rounded-full border border-border/15 px-2 py-0.5 text-[10px] text-muted">
                  {Math.round(material.roleConfidence * 100)}%
                </span>
              ) : null}
            </div>
            {material.metrics.length ? (
              <div className="mt-2 flex flex-wrap gap-1">
                {material.metrics.map((metric) => (
                  <span key={`${material.id}-${metric}`} className="rounded-full bg-background px-2 py-0.5 text-[10px] text-muted">
                    {metric}
                  </span>
                ))}
              </div>
            ) : null}
            <p className="mt-2 text-[11px] leading-relaxed text-muted">{material.summary}</p>
          </article>
        ))}
      </div>
    </ResultSection>
  )
}

function ReviewItemsPanel({ result }: { result: SuperAgentResultExplainability }) {
  const statusClass = {
    passed: 'border-positive/20 bg-positive/10 text-positive',
    attention: 'border-[rgb(var(--color-sa-gold))]/25 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]',
    failed: 'border-destructive/20 bg-destructive/10 text-destructive',
  }
  const statusText = {
    passed: '通过',
    attention: '需关注',
    failed: '不符合',
  }
  if (!result.reviewItems.length) {
    return (
      <ResultSection title="审查了什么">
        <div className="rounded-lg border border-border/10 bg-surface px-3 py-3 text-[11px] text-muted">
          暂未返回逐项检查记录；已执行范围：{result.checkedScope.join('、') || '暂无结构化统计'}。
        </div>
      </ResultSection>
    )
  }
  return (
    <ResultSection title="审查了什么">
      <div className="space-y-2">
        {result.reviewItems.slice(0, 12).map((item) => (
          <details key={item.id} className="rounded-lg border border-border/10 bg-surface px-3 py-2">
            <summary className="flex cursor-pointer list-none items-start gap-2">
              <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${statusClass[item.status]}`}>
                {statusText[item.status]}
              </span>
              <span className="min-w-0 flex-1 text-[12px] font-medium text-primary">{item.title}</span>
              <span className="text-[10px] text-muted">展开</span>
            </summary>
            <div className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-muted">
              {item.requirement ? <p>检查依据：{item.requirement}</p> : null}
              {item.conclusion ? <p>结论：{item.conclusion}</p> : null}
              {item.recommendation ? <p>建议：{item.recommendation}</p> : null}
              {item.source ? <p>来源：{item.source}</p> : null}
            </div>
          </details>
        ))}
      </div>
    </ResultSection>
  )
}

function PriorityFindingCard({ item }: { item: ReviewIssueItem }) {
  const isFail = item.severity === 'fail'
  return (
    <div className="rounded-lg border border-border/15 bg-background p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${
            isFail
              ? 'border-destructive/25 bg-destructive/10 text-destructive'
              : 'border-[rgb(var(--color-sa-gold))]/25 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]'
          }`}
        >
          {isFail ? '不满足' : '证据不足'}
        </span>
      </div>
      <div className="mt-1.5 text-[12px] font-medium text-primary">{item.title}</div>
      {(item.problem || item.suggestion) ? (
        <p className="mt-1 line-clamp-2 text-[10px] leading-5 text-muted">{item.problem || item.suggestion}</p>
      ) : null}
    </div>
  )
}

export default function SuperAgentFallbackResultOverview({
  run,
  summary,
  explainability,
  classification,
  onExpandFullReport,
  compact = false,
}: {
  run: SuperAgentRun
  summary: ReviewResultSummary
  explainability: SuperAgentResultExplainability
  classification?: MaterialClassification | null
  onExpandFullReport?: () => void
  /** 工作台预览已展示结论与指标时，仅保留报告与诊断明细 */
  compact?: boolean
}) {
  const fullReportRef = useRef<HTMLDetailsElement | null>(null)
  const metrics = useMemo(
    () => buildFallbackOverviewMetrics(run, summary, explainability),
    [run, summary, explainability],
  )

  const priorityFindings = useMemo(() => {
    return [
      ...summary.failItems,
      ...summary.attentionItems,
    ].slice(0, PRIORITY_FINDINGS_LIMIT)
  }, [summary.attentionItems, summary.failItems])

  const priorityTotal = summary.failItems.length + summary.attentionItems.length
  const reportMarkdown = String(run.report_markdown || '').trim()
    || String((run.review_plus_result?.report as { markdown?: string } | undefined)?.markdown || '').trim()

  const handleExpandFullReport = () => {
    if (onExpandFullReport) {
      onExpandFullReport()
      return
    }
    const el = fullReportRef.current
    if (!el) return
    el.open = true
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="space-y-4">
      {!compact ? (
        <>
          <section className="rounded-xl border border-border/15 bg-background/70 p-4">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="text-[13px] font-medium text-primary">审查结论</h2>
                <p className="mt-1 text-[12px] leading-relaxed text-primary">{metrics.conclusionText}</p>
              </div>
              {metrics.verdict ? (
                <div className={`shrink-0 rounded-lg border px-3 py-1.5 text-center ${REVIEW_PLUS_VERDICT_COLORS[metrics.verdict]}`}>
                  <div className="text-[10px] font-medium">{REVIEW_PLUS_VERDICT_LABELS[metrics.verdict]}</div>
                </div>
              ) : null}
            </div>
          </section>

          <ResultSummaryBar items={metrics.summaryItems} hint={metrics.summaryHint} />

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleExpandFullReport}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-2xl bg-brand px-4 text-[11px] font-medium text-white motion-safe:active:scale-[0.98]"
            >
              <FileText size={14} aria-hidden />
              展开完整报告
            </button>
          </div>

          <section className="rounded-xl border border-border/15 bg-background/70 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <ListChecks size={15} className="text-primaryAccent" aria-hidden />
                <h2 className="text-[13px] font-medium text-primary">建议优先处理</h2>
              </div>
              <span className="text-[10px] text-muted">
                {priorityTotal ? `${Math.min(priorityFindings.length, PRIORITY_FINDINGS_LIMIT)} / ${priorityTotal} 项` : '无'}
              </span>
            </div>
            {priorityFindings.length ? (
              <div className="mt-3 space-y-2">
                {priorityFindings.map((item) => (
                  <PriorityFindingCard key={item.id} item={item} />
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-lg border border-border/20 bg-background p-4 text-[11px] text-muted">
                未发现需要优先处理的不满足项或主要问题，可展开完整报告确认结论。
              </p>
            )}
          </section>
        </>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleExpandFullReport}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-2xl border border-border/20 bg-background px-4 text-[11px] font-medium text-primary motion-safe:active:scale-[0.98]"
          >
            <FileText size={14} aria-hidden />
            展开完整报告
          </button>
        </div>
      )}

      {explainability.riskItems.length ? (
        <details className="rounded-xl border border-border/15 bg-background/70 p-4">
          <summary className="cursor-pointer text-[12px] font-medium text-primary">
            剩余风险（{explainability.riskItems.length} 项）
          </summary>
          <ul className="mt-3 space-y-1.5">
            {explainability.riskItems.slice(0, 8).map((risk, index) => (
              <li key={`${risk}-${index}`} className="flex items-start gap-2 text-[11px] leading-relaxed text-destructive/80">
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-destructive/50" />
                <span>{risk}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <details ref={fullReportRef} className="rounded-xl border border-border/15 bg-background/70 p-4">
        <summary className="cursor-pointer text-[12px] font-medium text-primary">完整报告正文</summary>
        <div className="mt-4 border-t border-border/15 pt-4">
          {reportMarkdown ? (
            <div className="prose prose-sm max-w-none">
              <MarkdownRenderer>{reportMarkdown}</MarkdownRenderer>
            </div>
          ) : (
            <p className="text-[11px] text-muted">报告正文尚未生成，请导出报告或在工作台查看完整内容。</p>
          )}
        </div>
      </details>

      <details className="rounded-xl border border-border/15 bg-background/70 p-4">
        <summary className="cursor-pointer text-[12px] font-medium text-primary">检查项明细 / 解析效果</summary>
        <div className="mt-4 space-y-4">
          <ReviewItemsPanel result={explainability} />
          <ParsedMaterialsPanel result={explainability} />
        </div>
      </details>

      <details className="rounded-xl border border-border/15 bg-background/70 p-4">
        <summary className="cursor-pointer text-[12px] font-medium text-primary">
          质量评分与调度诊断（技术细节）
        </summary>
        <div className="mt-4 space-y-4">
          <ExecutionMetricsPanel
            snapshot={run.execution_metrics_snapshot}
            qualityReport={run.quality_report}
            className="rounded-xl border border-border/15 bg-background/70 p-4"
            testId="super-agent-wizard-execution-metrics"
          />
          <SmartCommitteeDiagnosticsCard
            run={run}
            classification={classification ?? undefined}
            testId="super-agent-wizard-smart-diagnostics"
          />
        </div>
      </details>
    </div>
  )
}
