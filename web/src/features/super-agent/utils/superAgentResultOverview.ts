import { resolveSuperAgentWorkbenchReviewType } from '@/features/unified-review-workbench/utils/superAgentWorkbenchLink'
import { resolveReviewPlusFindingTitle } from '@/features/review-plus-v2/utils/reviewPlusCheckItemLabel'
import {
  formatReviewPlusPassRate,
  inferReviewPlusVerdict,
  type ReviewPlusVerdictTone,
} from '@/features/review-plus-v2/utils/reviewPlusConclusion'
import type { ResultSummaryItem } from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import type { SuperAgentResultExplainability } from '@/features/super-agent/utils/superAgentProcessingViewModel'
import { filterBusinessFindings } from '@/features/super-agent/utils/smartCommitteeDiagnostics'
import type { SuperAgentRun } from '@/features/super-agent/types'

export interface ReviewIssueItem {
  id: string
  severity: 'attention' | 'fail'
  title: string
  suggestion?: string
  basis?: string
  problem?: string
  source?: string
}

export interface ReviewResultSummary {
  passed: number
  attention: number
  failed: number
  attentionItems: ReviewIssueItem[]
  failItems: ReviewIssueItem[]
}

export interface FallbackOverviewMetrics {
  totalCheckItems: number
  satisfied: number
  notSatisfied: number
  insufficientEvidence: number
  passRate: string
  summaryItems: ResultSummaryItem[]
  verdict: ReviewPlusVerdictTone
  conclusionText: string
  summaryHint: string
}

export function shouldLoadReviewPlusResult(run: SuperAgentRun): boolean {
  const reviewId = run.source_review_id?.trim()
  if (!reviewId) return false
  if (resolveSuperAgentWorkbenchReviewType(run) === 'gnc') return false
  if (run.status === 'completed' || run.status === 'limited') return true
  const result = run.review_plus_result
  if (!result || typeof result !== 'object') return false
  const report = (result as { report?: unknown }).report
  const findings = (result as { findings?: unknown[] }).findings
  return Boolean(report) || (Array.isArray(findings) && findings.length > 0)
}

export function extractReviewSummary(run: SuperAgentRun): ReviewResultSummary {
  const report = (run.review_plus_result?.report || null) as {
    satisfied_count?: number
    not_satisfied_count?: number
    insufficient_evidence_count?: number
    critical_count?: number
    findings?: Array<{
      finding_id?: string
      check_item_id?: string
      title?: string
      judgment?: string
      recommendation?: string
      reasoning?: string
      source_quote?: string
      severity?: string
    }>
    markdown?: string
  } | null

  const attentionItems: ReviewIssueItem[] = []
  const failItems: ReviewIssueItem[] = []
  let passed = 0
  const checkItems = (run.structured_bundle?.check_items || []) as Array<{
    check_item_id?: string
    title?: string
    requirement_text?: string
  }>
  const checkItemById = new Map(checkItems.map((item) => [String(item.check_item_id || ''), item]))

  if (report?.findings?.length) {
    for (const [index, finding] of report.findings.entries()) {
      const id = finding.finding_id || `R-${String(index + 1).padStart(3, '0')}`
      const checkItem = checkItemById.get(String(finding.check_item_id || ''))
      const title = resolveReviewPlusFindingTitle(finding, {
        check_item_id: String(checkItem?.check_item_id || finding.check_item_id || ''),
        title: String(checkItem?.title || ''),
      })
      const source = finding.source_quote || ''
      const suggestion = finding.recommendation || finding.reasoning || ''
      const judgment = (finding.judgment || '').toLowerCase()

      if (judgment === 'satisfied' || judgment === 'not_applicable') {
        passed += 1
        continue
      }
      if (judgment === 'not_satisfied') {
        failItems.push({
          id,
          severity: 'fail',
          title,
          problem: finding.reasoning || suggestion,
          basis: finding.severity ? `严重度：${finding.severity}` : undefined,
          source,
        })
        continue
      }
      attentionItems.push({
        id,
        severity: 'attention',
        title,
        suggestion,
        source,
      })
    }
  }

  if (report && !report.findings?.length) {
    passed = Number(report.satisfied_count || 0)
    const attention = Number(report.insufficient_evidence_count || 0)
    const failed = Number(report.not_satisfied_count || 0) + Number(report.critical_count || 0)
    if (passed + attention + failed > 0) {
      return {
        passed,
        attention,
        failed,
        attentionItems: filterBusinessFindings(run.quality_report?.warnings || []).map((warning, i) => ({
          id: `W-${String(i + 1).padStart(3, '0')}`,
          severity: 'attention' as const,
          title: warning.slice(0, 48) || '需关注项',
          suggestion: warning,
          source: '质量评估',
        })),
        failItems: filterBusinessFindings(run.trace_report?.degradation_summary || []).map((item, i) => ({
          id: `F-${String(i + 1).padStart(3, '0')}`,
          severity: 'fail' as const,
          title: item.slice(0, 48) || '不符合项',
          problem: item,
          source: '执行追踪',
        })),
      }
    }
  }

  if (!attentionItems.length && !failItems.length) {
    const warnings = filterBusinessFindings(run.quality_report?.warnings || [])
    warnings.forEach((warning, i) => {
      attentionItems.push({
        id: `W-${String(i + 1).padStart(3, '0')}`,
        severity: 'attention',
        title: warning.slice(0, 40) || '需关注项',
        suggestion: warning,
        source: '审查引擎',
      })
    })
    const degradations = filterBusinessFindings(run.trace_report?.degradation_summary || [])
    degradations.forEach((item, i) => {
      failItems.push({
        id: `F-${String(i + 1).padStart(3, '0')}`,
        severity: 'fail',
        title: item.slice(0, 40) || '不符合项',
        problem: item,
        source: '执行追踪',
      })
    })
    passed = Math.max(0, Number(run.review_plus_result?.finding_count || 0) - attentionItems.length - failItems.length)
  }

  if (passed === 0 && attentionItems.length === 0 && failItems.length === 0) {
    const findingCount = Number(run.review_plus_result?.finding_count || 0)
    passed = findingCount > 0 ? findingCount : 1
  }

  return {
    passed,
    attention: attentionItems.length,
    failed: failItems.length,
    attentionItems,
    failItems,
  }
}

export function buildFallbackOverviewMetrics(
  run: SuperAgentRun,
  summary: ReviewResultSummary,
  explainability: SuperAgentResultExplainability,
): FallbackOverviewMetrics {
  const report = (run.review_plus_result?.report || null) as {
    total_check_items?: number
    satisfied_count?: number
    not_satisfied_count?: number
    insufficient_evidence_count?: number
    conclusion?: string
    summary?: string
  } | null

  const reviewItemCount = explainability.reviewItems.length
  const totalCheckItems = report?.total_check_items
    ?? (reviewItemCount > 0 ? reviewItemCount : summary.passed + summary.attention + summary.failed)
  const satisfied = report?.satisfied_count ?? summary.passed
  const notSatisfied = report?.not_satisfied_count ?? summary.failed
  const insufficientEvidence = report?.insufficient_evidence_count ?? summary.attention
  const passRate = formatReviewPlusPassRate(totalCheckItems, satisfied)
  const conclusionText = report?.conclusion || explainability.conclusionSummary
  const summaryHint = report?.summary || explainability.conclusionBasis || '汇总本轮审查结论与建议优先处理的问题。'

  return {
    totalCheckItems,
    satisfied,
    notSatisfied,
    insufficientEvidence,
    passRate,
    conclusionText,
    summaryHint,
    verdict: inferReviewPlusVerdict(conclusionText),
    summaryItems: [
      { label: '检查项', value: totalCheckItems, tone: 'brand' },
      { label: '满足', value: satisfied, tone: 'success' },
      { label: '不满足', value: notSatisfied, tone: notSatisfied > 0 ? 'danger' : 'default' },
      { label: '证据不足', value: insufficientEvidence, tone: insufficientEvidence > 0 ? 'warning' : 'default' },
      { label: '通过率', value: passRate, tone: 'brand' },
    ],
  }
}
