'use client'

import { Gauge } from 'lucide-react'
import type { ExecutionMetricsSnapshot, SuperAgentQualityReport } from '@/features/super-agent/types'

const SCORE_ITEMS: Array<{ key: keyof SuperAgentQualityReport; label: string }> = [
  { key: 'parse_quality_score', label: '解析' },
  { key: 'evidence_quality_score', label: '证据' },
  { key: 'traceability_score', label: '追溯' },
  { key: 'consistency_score', label: '一致' },
  { key: 'stability_score', label: '稳定' },
]

function passTone(passed: boolean): string {
  return passed ? 'border-positive/25 bg-positive/10 text-positive' : 'border-destructive/25 bg-destructive/10 text-destructive'
}

export function ScoreStrip({ report }: { report: SuperAgentQualityReport }) {
  return (
    <div className="grid grid-cols-5 gap-2">
      {SCORE_ITEMS.map((item) => {
        const value = Number(report[item.key] || 0)
        return (
          <div key={item.key} className="min-w-0 rounded-lg border border-border/10 bg-background/70 px-2 py-2">
            <div className="text-[10px] text-muted/65">{item.label}</div>
            <div className="mt-1 text-sm font-semibold tabular-nums text-primary">{Math.round(value * 100)}</div>
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-border/10">
              <div className="h-full rounded-full bg-primaryAccent" style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function ExecutionMetricsPanel({
  snapshot,
  qualityReport,
  className = '',
  testId,
}: {
  snapshot?: ExecutionMetricsSnapshot
  qualityReport: SuperAgentQualityReport
  className?: string
  testId?: string
}) {
  if (!snapshot || !snapshot.quality_scores) {
    return (
      <section className={className} data-testid={testId}>
        <div className="mb-2 flex items-center gap-2 text-[12px] font-medium text-primary">
          <Gauge className="h-4 w-4 text-primaryAccent" aria-hidden />
          五维质量评分
        </div>
        <ScoreStrip report={qualityReport} />
      </section>
    )
  }

  const scoreReport: SuperAgentQualityReport = {
    ...qualityReport,
    parse_quality_score: snapshot.quality_scores.parse_quality_score,
    evidence_quality_score: snapshot.quality_scores.evidence_quality_score,
    traceability_score: snapshot.quality_scores.traceability_score,
    consistency_score: snapshot.quality_scores.consistency_score,
    stability_score: snapshot.quality_scores.stability_score,
    overall_score: snapshot.quality_scores.overall_score,
  }
  const summary = snapshot.parse_artifact_summary
  const degradationPct = Math.round((snapshot.degradation_rate || 0) * 100)

  return (
    <section className={`space-y-3 ${className}`.trim()} data-testid={testId}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full border px-2 py-0.5 text-[10px] ${passTone(snapshot.execution_pass)}`}>
          执行通过 {snapshot.execution_pass ? '✓' : '✗'}
        </span>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] ${passTone(snapshot.capability_pass)}`}>
          能力通过 {snapshot.capability_pass ? '✓' : '✗'}
        </span>
        <span className="rounded-full border border-border/15 bg-background px-2 py-0.5 text-[10px] text-muted">
          降级率 {degradationPct}%
        </span>
        {summary.file_count ? (
          <span className="rounded-full border border-border/15 bg-background px-2 py-0.5 text-[10px] text-muted">
            文件 {summary.parsed_count}/{summary.file_count}
          </span>
        ) : null}
      </div>
      <div>
        <div className="mb-2 flex items-center gap-2 text-[12px] font-medium text-primary">
          <Gauge className="h-4 w-4 text-primaryAccent" aria-hidden />
          五维质量评分
        </div>
        <ScoreStrip report={scoreReport} />
      </div>
    </section>
  )
}
