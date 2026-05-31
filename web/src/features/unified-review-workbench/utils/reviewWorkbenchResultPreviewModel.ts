import type { ResultSummaryItem } from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import type { SuperAgentResultExplainability } from '@/features/super-agent/utils/superAgentProcessingViewModel'
import {
  buildFallbackOverviewMetrics,
  type ReviewResultSummary,
} from '@/features/super-agent/utils/superAgentResultOverview'
import type { SuperAgentRun } from '@/features/super-agent/types'
import {
  arbitrationStatusLabel,
  formatGncVerdictLabel,
  parseGncDecision,
  parseGncReportPayload,
  resolveGncArbitrationDisplayStatus,
} from '@/features/unified-review-workbench/utils/gncRichPanels'
import {
  buildSuperAgentWorkbenchHref,
  defaultWorkbenchTabForRun,
  resolveSuperAgentWorkbenchReviewType,
} from '@/features/unified-review-workbench/utils/superAgentWorkbenchLink'
import { buildUnifiedReviewWorkbenchHref } from '@/features/unified-review-workbench/tabNavigation'
import type { UnifiedReviewType, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export type WorkbenchPreviewReviewKind = 'gnc' | 'review_plus' | 'smart'

export interface WorkbenchPreviewHighlightItem {
  title: string
  detail?: string
  status?: string
}

export interface WorkbenchPreviewSection {
  key: string
  title: string
  items: WorkbenchPreviewHighlightItem[]
  emptyHint?: string
  tab?: UnifiedWorkbenchTabKey
}

export interface WorkbenchPreviewAction {
  label: string
  tab: UnifiedWorkbenchTabKey
  variant?: 'primary' | 'secondary'
}

export interface ReviewWorkbenchResultPreviewModel {
  reviewType: UnifiedReviewType | null
  reviewKind: WorkbenchPreviewReviewKind
  statusLabel: string
  phaseLabel?: string
  arbitrationLabel?: string
  verdict?: string
  rationale?: string
  summaryItems: ResultSummaryItem[]
  summaryHint?: string
  sections: WorkbenchPreviewSection[]
  actions: WorkbenchPreviewAction[]
  workbenchHref: string | null
  defaultTab?: UnifiedWorkbenchTabKey
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function gncRecord(run: SuperAgentRun): Record<string, unknown> {
  return asRecord(run.gnc_review_result)
}

function reviewPlusRecord(run: SuperAgentRun): Record<string, unknown> {
  return asRecord(run.review_plus_result)
}

function resolveReviewKind(run: SuperAgentRun, reviewType: UnifiedReviewType | null): WorkbenchPreviewReviewKind {
  const route = String(run.route_decision?.route || run.requested_route || '').toLowerCase()
  if (reviewType === 'gnc' || route.includes('gnc')) return 'gnc'
  if (route === 'smart' || route === 'comprehensive' || route === 'auto') return 'smart'
  return 'review_plus'
}

function statusLabelForRun(run: SuperAgentRun, payload: Record<string, unknown>): string {
  const status = String(payload.status || run.status || '').trim()
  if (!status) return '已完成'
  const labels: Record<string, string> = {
    completed: '已完成',
    limited: '有限结论',
    running: '执行中',
    failed: '失败',
    paused: '已暂停',
  }
  return labels[status.toLowerCase()] || status
}

function phaseLabelFromPayload(payload: Record<string, unknown>): string | undefined {
  const phase = String(payload.workbench_phase || '').trim()
  if (!phase) return undefined
  const labels: Record<string, string> = {
    pre_review: '预审',
    startup: '启动',
    executing: '执行中',
    arbitration: '仲裁',
    completed: '已闭环',
    failed: '失败',
  }
  return labels[phase.toLowerCase()] || phase
}

function mapFindingItems(
  items: unknown[],
  limit = 3,
): WorkbenchPreviewHighlightItem[] {
  return items.slice(0, limit).map((raw) => {
    const item = asRecord(raw)
    return {
      title: String(item.title || item.description || item.finding_id || item.rid_id || '项'),
      detail: String(item.description || item.reasoning || item.summary || item.recommendation || '').trim() || undefined,
      status: String(item.status || item.severity || item.judgment || '').trim() || undefined,
    }
  })
}

function buildGncPreviewModel(
  run: SuperAgentRun,
  summary: ReviewResultSummary,
  explainability: SuperAgentResultExplainability,
  workbenchHref: string | null,
  defaultTab?: UnifiedWorkbenchTabKey,
): ReviewWorkbenchResultPreviewModel {
  const gnc = gncRecord(run)
  const findings = Array.isArray(gnc.findings) ? gnc.findings : []
  const ridItems = Array.isArray(gnc.rid_ledger)
    ? gnc.rid_ledger
    : Array.isArray(gnc.rid_items)
      ? gnc.rid_items
      : []
  const openRid = Number(gnc.open_rid_count ?? gnc.open_rid ?? 0)
  const evidenceCount = Number(gnc.evidence_count ?? 0)
  const findingCount = findings.length || Number(gnc.finding_count ?? explainability.reviewItems.length)
  const ridCount = ridItems.length || Number(gnc.rid_count ?? 0)

  const decision = parseGncDecision(
    asRecord(gnc.chief_decision) || asRecord(gnc.decision) || asRecord(gnc.editorial_synthesis),
  )
  const arbitrationStatus = resolveGncArbitrationDisplayStatus({
    arbitrationStatus: String(gnc.arbitration_status || ''),
    requiresArbitration: Boolean(gnc.requires_arbitration ?? decision.requiresArbitration),
    workbenchPhase: String(gnc.workbench_phase || ''),
  })
  const report = parseGncReportPayload(gnc.report || gnc.report_markdown)

  const disciplineReviews = asRecord(gnc.discipline_reviews)
  const committeeItems: WorkbenchPreviewHighlightItem[] = Object.entries(disciplineReviews)
    .slice(0, 4)
    .map(([key, raw]) => {
      const entry = asRecord(raw)
      const nestedFindings = Array.isArray(entry.findings) ? entry.findings.length : 0
      const status = entry.completed === true
        ? '已完成'
        : entry.status === 'failed'
          ? '失败'
          : String(entry.status || '进行中')
      return {
        title: key.replace(/_/g, ' '),
        detail: nestedFindings ? `${nestedFindings} 条发现` : undefined,
        status,
      }
    })

  const conflicts = Array.isArray(gnc.conflicts) ? gnc.conflicts : decision.expertConflicts

  const sections: WorkbenchPreviewSection[] = [
    {
      key: 'rid',
      title: 'RID 台账',
      tab: 'rid',
      items: mapFindingItems(ridItems),
      emptyHint: openRid > 0 ? `${openRid} 条未闭环 RID 待处理` : '暂无 RID 记录',
    },
    {
      key: 'committee',
      title: '专家组 / AD·AC',
      tab: 'committee',
      items: committeeItems.length
        ? committeeItems
        : mapFindingItems(findings).slice(0, 3),
      emptyHint: '专家组审查明细将在工作台查看',
    },
    {
      key: 'decision',
      title: '总师裁定 / 仲裁',
      tab: arbitrationStatus === 'pending' ? 'arbitration' : 'decision',
      items: [
        ...(decision.verdict ? [{ title: '裁定', detail: formatGncVerdictLabel(decision.verdict) }] : []),
        ...(decision.rationale ? [{ title: '依据', detail: decision.rationale }] : []),
        ...mapFindingItems(Array.isArray(conflicts) ? conflicts : [], 2).map((item) => ({
          ...item,
          title: item.title || '专家冲突',
        })),
      ],
      emptyHint: arbitrationStatus === 'pending' ? '存在待人工仲裁项' : '总师裁定尚未登记',
    },
    {
      key: 'report',
      title: '审查报告',
      tab: 'report',
      items: report?.summary
        ? [{ title: '摘要', detail: report.summary }]
        : report?.markdown
          ? [{ title: '正文', detail: report.markdown.slice(0, 160) + (report.markdown.length > 160 ? '…' : '') }]
          : [],
      emptyHint: '正式报告尚未生成，可在工作台查看纪要与裁定',
    },
  ]

  const actions: WorkbenchPreviewAction[] = []
  if (openRid > 0) actions.push({ label: '处理 RID', tab: 'rid', variant: 'primary' })
  if (arbitrationStatus === 'pending') {
    actions.push({ label: '进入仲裁', tab: 'arbitration', variant: 'primary' })
  } else if (decision.verdict || gnc.status === 'completed') {
    actions.push({ label: '查看总师裁定', tab: 'decision', variant: 'primary' })
  }
  actions.push(
    { label: '专家组审查', tab: 'committee' },
    { label: '证据链', tab: 'evidences' },
    { label: '完整报告', tab: 'report' },
  )

  const verdict = decision.verdict
    ? formatGncVerdictLabel(decision.verdict)
    : String(asRecord(gnc.editorial_synthesis).conclusion_draft || explainability.conclusionSummary || '').trim() || undefined

  return {
    reviewType: 'gnc',
    reviewKind: 'gnc',
    statusLabel: statusLabelForRun(run, gnc),
    phaseLabel: phaseLabelFromPayload(gnc),
    arbitrationLabel: arbitrationStatusLabel(arbitrationStatus),
    verdict,
    rationale: decision.rationale || explainability.conclusionBasis,
    summaryItems: [
      { label: '发现', value: findingCount, tone: 'brand' },
      { label: 'RID', value: ridCount, tone: 'default' },
      { label: '未闭环 RID', value: openRid, tone: openRid > 0 ? 'warning' : 'default' },
      { label: '证据', value: evidenceCount, tone: 'default' },
    ],
    summaryHint: explainability.conclusionSummary || 'GNC 审查结果摘要，完整台账与裁定请在工作台继续处理。',
    sections,
    actions: dedupeActions(actions),
    workbenchHref,
    defaultTab,
  }
}

function buildReviewPlusPreviewModel(
  run: SuperAgentRun,
  summary: ReviewResultSummary,
  explainability: SuperAgentResultExplainability,
  workbenchHref: string | null,
  defaultTab?: UnifiedWorkbenchTabKey,
  reviewKind: WorkbenchPreviewReviewKind = 'review_plus',
): ReviewWorkbenchResultPreviewModel {
  const review = reviewPlusRecord(run)
  const report = asRecord(review.report)
  const metrics = buildFallbackOverviewMetrics(run, summary, explainability)

  const findings = Array.isArray(review.findings)
    ? review.findings
    : Array.isArray(report.findings)
      ? report.findings
      : []
  const coverageMatrix = asRecord(review.coverage_matrix)
  const coverageSummary = asRecord(coverageMatrix.summary)
  const coverageRows = coverageMatrix.rows
  const coverageCount = Array.isArray(coverageRows)
    ? coverageRows.length
    : Number(coverageSummary.row_count ?? 0)
  const crossDocCount = Array.isArray(review.cross_document_review_items)
    ? review.cross_document_review_items.length
    : 0
  const traceability = review.traceability_result

  const sections: WorkbenchPreviewSection[] = [
    {
      key: 'findings',
      title: '审查发现',
      tab: 'findings',
      items: mapFindingItems(findings),
      emptyHint: summary.failItems.length + summary.attentionItems.length > 0
        ? `${summary.failItems.length + summary.attentionItems.length} 项待关注`
        : '暂无结构化审查发现',
    },
    {
      key: 'coverage',
      title: '覆盖矩阵',
      tab: 'coverage',
      items: coverageCount > 0
        ? [{ title: '覆盖矩阵', detail: `${coverageCount} 行`, status: '已生成' }]
        : [],
      emptyHint: '覆盖矩阵尚未生成',
    },
    {
      key: 'traceability',
      title: '追溯矩阵',
      tab: 'traceability',
      items: traceability
        ? [{ title: '追溯结果', detail: '已登记', status: '可查看' }]
        : [],
      emptyHint: '追溯矩阵尚未生成',
    },
    {
      key: 'cross_doc',
      title: '文文一致性',
      tab: 'cross_doc',
      items: crossDocCount > 0
        ? [{ title: '跨文档项', detail: `${crossDocCount} 项`, status: '已生成' }]
        : [],
      emptyHint: '暂无跨文档一致性项',
    },
    {
      key: 'report',
      title: '审查报告',
      tab: 'report',
      items: metrics.conclusionText
        ? [{ title: '结论', detail: metrics.conclusionText }]
        : [],
      emptyHint: '报告尚未生成',
    },
  ]

  const actions: WorkbenchPreviewAction[] = [
    { label: '查看审查发现', tab: 'findings', variant: summary.failed > 0 ? 'primary' : 'secondary' },
    { label: '覆盖矩阵', tab: 'coverage' },
    { label: '完整报告', tab: 'report', variant: 'primary' },
  ]

  return {
    reviewType: 'review_plus',
    reviewKind,
    statusLabel: statusLabelForRun(run, review),
    phaseLabel: phaseLabelFromPayload(review),
    rationale: metrics.conclusionText,
    summaryItems: metrics.summaryItems,
    summaryHint: metrics.summaryHint,
    sections,
    actions,
    workbenchHref,
    defaultTab,
  }
}

function buildSmartPreviewModel(
  run: SuperAgentRun,
  summary: ReviewResultSummary,
  explainability: SuperAgentResultExplainability,
  workbenchHref: string | null,
  defaultTab?: UnifiedWorkbenchTabKey,
): ReviewWorkbenchResultPreviewModel {
  const metrics = buildFallbackOverviewMetrics(run, summary, explainability)
  const chiefItems = explainability.chiefReviewItems.slice(0, 3).map((item) => ({
    title: item.title,
    detail: item.recommendation || item.conclusion,
    status: item.status,
  }))
  const reviewItems = explainability.reviewItems.slice(0, 3).map((item) => ({
    title: item.title,
    detail: item.conclusion || item.recommendation,
    status: item.status === 'failed' ? '不满足' : item.status === 'attention' ? '需关注' : '通过',
  }))

  const sections: WorkbenchPreviewSection[] = [
    {
      key: 'findings',
      title: '审查发现',
      tab: 'findings',
      items: reviewItems,
      emptyHint: '暂无结构化发现',
    },
    {
      key: 'experts',
      title: '专家 / 总师结论',
      tab: 'overview',
      items: chiefItems,
      emptyHint: explainability.conclusionSummary || '暂无专家综合结论',
    },
    {
      key: 'report',
      title: '报告与裁定',
      tab: 'report',
      items: metrics.conclusionText
        ? [{ title: '综合结论', detail: metrics.conclusionText }]
        : [],
      emptyHint: '完整报告可在工作台或下方展开查看',
    },
  ]

  const actions: WorkbenchPreviewAction[] = []
  if (workbenchHref) {
    actions.push(
      { label: '查看审查发现', tab: 'findings', variant: summary.failed > 0 ? 'primary' : 'secondary' },
      { label: '结论总览', tab: defaultTab || 'overview', variant: 'primary' },
    )
  }

  return {
    reviewType: resolveSuperAgentWorkbenchReviewType(run),
    reviewKind: 'smart',
    statusLabel: statusLabelForRun(run, reviewPlusRecord(run)),
    verdict: undefined,
    rationale: explainability.conclusionSummary,
    summaryItems: metrics.summaryItems,
    summaryHint: metrics.summaryHint,
    sections,
    actions,
    workbenchHref,
    defaultTab,
  }
}

function dedupeActions(actions: WorkbenchPreviewAction[]): WorkbenchPreviewAction[] {
  const seen = new Set<string>()
  return actions.filter((action) => {
    const key = `${action.tab}:${action.label}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function buildWorkbenchTabHref(
  model: ReviewWorkbenchResultPreviewModel,
  tab: UnifiedWorkbenchTabKey,
  reviewId: string,
): string | null {
  if (!model.reviewType || !reviewId) return null
  return buildUnifiedReviewWorkbenchHref(model.reviewType, reviewId, { tab })
}

export function buildReviewWorkbenchResultPreviewModel(
  run: SuperAgentRun,
  summary: ReviewResultSummary,
  explainability: SuperAgentResultExplainability,
): ReviewWorkbenchResultPreviewModel | null {
  const reviewId = run.source_review_id?.trim()
  if (!reviewId) return null

  const reviewType = resolveSuperAgentWorkbenchReviewType(run)
  const reviewKind = resolveReviewKind(run, reviewType)
  const defaultTab = defaultWorkbenchTabForRun(run)
  const workbenchHref = buildSuperAgentWorkbenchHref(run, { tab: defaultTab })

  if (reviewType === 'gnc') {
    return buildGncPreviewModel(run, summary, explainability, workbenchHref, defaultTab)
  }

  if (reviewKind === 'smart') {
    return buildSmartPreviewModel(run, summary, explainability, workbenchHref, defaultTab)
  }

  return buildReviewPlusPreviewModel(
    run,
    summary,
    explainability,
    workbenchHref,
    defaultTab,
    reviewKind,
  )
}

export function buildReviewPlusResultPreviewModel(
  run: SuperAgentRun,
  summary: ReviewResultSummary,
  explainability: SuperAgentResultExplainability,
): ReviewWorkbenchResultPreviewModel | null {
  const reviewId = run.source_review_id?.trim()
  if (!reviewId) return null
  const defaultTab = defaultWorkbenchTabForRun(run)
  const workbenchHref = buildSuperAgentWorkbenchHref(run, { tab: defaultTab })
  return buildReviewPlusPreviewModel(
    run,
    summary,
    explainability,
    workbenchHref,
    defaultTab,
    'review_plus',
  )
}
