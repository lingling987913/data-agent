import type {
  UnifiedReviewWorkbenchDetail,
  UnifiedReviewType,
  UnifiedWorkbenchTabKey,
} from '@/features/unified-review-workbench/types'
import { ROUTE_LABELS } from '@/lib/aeroTerminology'
import {
  deriveRationaleSummary,
  resolveLocalizedRationale,
  resolveLocalizedVerdict,
  resolveReviewModeLabel,
  sanitizeBusinessText,
  sanitizePriorityItemText,
} from '@/features/unified-review-workbench/utils/zhWorkbenchText'

export const BUSINESS_BUCKET_ORDER = [
  'severe_error',
  'content_nonconforming',
  'template_structure_nonconforming',
  'cross_document_inconsistency',
  'insufficient_evidence',
  'manual_review',
  'verified',
] as const

export type BusinessBucketKey = (typeof BUSINESS_BUCKET_ORDER)[number]

export const BUSINESS_BUCKET_LABELS: Record<BusinessBucketKey, string> = {
  severe_error: '严重错误',
  content_nonconforming: '内容不合格',
  template_structure_nonconforming: '模板/结构不合格',
  cross_document_inconsistency: '文文不一致',
  insufficient_evidence: '证据不足/无法印证',
  manual_review: '待人工确认',
  verified: '已通过/已印证',
}

export interface ConclusionPriorityItem {
  id: string
  title: string
  business_bucket: BusinessBucketKey | string
  business_bucket_label: string
  severity?: string
  judgment?: string
  reason?: string
  missing_reason?: string
  recommendation?: string
  tab_hint?: UnifiedWorkbenchTabKey
}

export interface ConclusionOverviewViewModel {
  taskDisplayName: string
  reviewSubjectLines: string[]
  reviewPlanLines: string[]
  reviewModeLabel: string
  actualScopeLines: string[]
  documentTypePending: boolean
  headlineVerdict: string
  oneLineConclusion: string
  verdict: string
  verdictLabel: string
  rationale: string
  rationaleDisplay: string
  materialInsufficiency: boolean
  bucketCards: Array<{ key: BusinessBucketKey | string; label: string; count: number }>
  priorityItems: ConclusionPriorityItem[]
  coverageSummary: {
    totalCheckItems: number
    verifiedCount: number
    evidenceCount: number
    coverageRateLabel: string
    documentTypeLabel: string
    notes: string[]
  }
  drillDownTabs: Array<{ tab: UnifiedWorkbenchTabKey; label: string }>
}

const GENERIC_TASK_NAME_PATTERNS = [
  /^super agent run$/i,
  /^super agent 审查$/i,
  /^智能审查\s*[\d./-]*$/i,
  /^综合审查\s*[\d./-]*$/i,
]

function materialBasename(filename: string): string {
  const base = filename.split(/[/\\]/).pop() || filename
  const dot = base.lastIndexOf('.')
  return dot > 0 ? base.slice(0, dot) : base
}

function isGenericReviewTaskName(name: string): boolean {
  const text = name.trim()
  if (!text) return true
  return GENERIC_TASK_NAME_PATTERNS.some((pattern) => pattern.test(text))
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => textValue(item)).filter(Boolean)
}

function withUniquePriorityItemIds(items: ConclusionPriorityItem[]): ConclusionPriorityItem[] {
  const seen = new Set<string>()
  return items.map((item, index) => {
    const stem = (item.id || item.title || `priority-item-${index}`).trim() || `priority-item-${index}`
    let id = stem
    let suffix = 1
    while (seen.has(id)) {
      id = `${stem}#${suffix}`
      suffix += 1
    }
    seen.add(id)
    return item.id === id ? item : { ...item, id }
  })
}

export function deriveReviewTaskDisplayName(detail: UnifiedReviewWorkbenchDetail): string {
  const explicitName = textValue(detail.name)
  if (explicitName && !isGenericReviewTaskName(explicitName)) {
    return explicitName
  }
  const reviewScope = asRecord(detail.conclusion_overview?.review_scope)
  const materialNames = stringList(reviewScope.material_names)
  if (materialNames.length === 1) {
    return materialBasename(materialNames[0])
  }
  if (materialNames.length > 1) {
    return `${materialBasename(materialNames[0])} 等 ${materialNames.length} 份材料`
  }
  return explicitName || detail.review_id || '审查任务'
}

export function buildReviewSubjectLines(reviewScope: Record<string, unknown>): string[] {
  const summaryLines = stringList(reviewScope.material_summary_lines)
  if (summaryLines.length) return summaryLines
  const materialNames = stringList(reviewScope.material_names)
  if (materialNames.length) return materialNames
  const actualScope = stringList(reviewScope.actual_scope)
  const materialTypeLine = actualScope.find((line) => line.startsWith('材料类型：'))
  if (materialTypeLine) return [materialTypeLine.replace(/^材料类型：/, '材料类型 · ')]
  return []
}

export function buildReviewPlanLines(
  reviewScope: Record<string, unknown>,
  reviewModeLabel: string,
): string[] {
  const explicit = stringList(reviewScope.review_plan_lines)
  if (explicit.length) return explicit
  const lines: string[] = []
  if (reviewModeLabel) lines.push(`审查模式：${reviewModeLabel}`)
  const routeKey = textValue(reviewScope.route_key)
  if (routeKey) {
    lines.push(`执行路由：${ROUTE_LABELS[routeKey] || routeKey}`)
  }
  for (const line of stringList(reviewScope.actual_scope)) {
    if (!lines.includes(line)) lines.push(line)
  }
  return lines
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function numberValue(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function textValue(value: unknown, fallback = ''): string {
  const text = String(value ?? '').trim()
  return text || fallback
}

export function normalizeIssueBuckets(
  buckets: Record<string, unknown> | undefined,
  labels?: Record<string, string>,
): ConclusionOverviewViewModel['bucketCards'] {
  const source = buckets || {}
  const cards: ConclusionOverviewViewModel['bucketCards'] = []
  const seen = new Set<string>()
  for (const key of BUSINESS_BUCKET_ORDER) {
    const count = numberValue(source[key])
    if (count <= 0) continue
    cards.push({
      key,
      label: labels?.[key] || BUSINESS_BUCKET_LABELS[key],
      count,
    })
    seen.add(key)
  }
  for (const [key, value] of Object.entries(source)) {
    if (seen.has(key) || numberValue(value) <= 0) continue
    cards.push({
      key,
      label: labels?.[key] || BUSINESS_BUCKET_LABELS[key as BusinessBucketKey] || '其他',
      count: numberValue(value),
    })
  }
  return cards
}

export function buildConclusionOverviewFromDetail(
  detail: UnifiedReviewWorkbenchDetail,
  reviewType: UnifiedReviewType,
  decisionPayload?: Record<string, unknown> | null,
): ConclusionOverviewViewModel {
  const overview = detail.conclusion_overview
  const decision = decisionPayload || {}
  const issueBuckets = (overview?.issue_buckets || decision.issue_buckets || decision.issue_summary) as Record<string, unknown> | undefined
  const bucketSource = asRecord(issueBuckets).buckets ? asRecord(asRecord(issueBuckets).buckets) : asRecord(issueBuckets)
  const bucketLabels = (overview?.bucket_labels || decision.bucket_labels || asRecord(decision.issue_summary).bucket_labels) as Record<string, string> | undefined
  const reviewScope = asRecord(overview?.review_scope || decision.review_scope)
  const coverage = asRecord(overview?.coverage_summary || decision.coverage_summary)
  const priorityRaw = (overview?.priority_items || decision.priority_items) as unknown[] | undefined

  const reviewModeLabel = resolveReviewModeLabel(
    reviewScope.review_mode_label || detail.summary.review_mode_label,
    reviewType,
  )
  const actualScope = Array.isArray(reviewScope.actual_scope)
    ? reviewScope.actual_scope.map((line) => textValue(line)).filter(Boolean)
    : []

  const bucketCards = normalizeIssueBuckets(bucketSource, bucketLabels)
  const bucketCountMap = Object.fromEntries(bucketCards.map((card) => [card.key, card.count]))
  const materialInsufficiency = Boolean(
    reviewScope.material_insufficiency
    || overview?.material_insufficiency
    || decision.material_insufficiency,
  )

  const verdictRaw = textValue(detail.summary.verdict || decision.verdict)
  const verdictLabel = resolveLocalizedVerdict({
    verdict: verdictRaw,
    verdictLabelZh: detail.summary.verdict_label_zh || decision.verdict_label_zh || overview?.verdict_label_zh,
    headline: overview?.headline_verdict || decision.headline_verdict || detail.summary.headline_verdict,
    oneLine: overview?.one_line_conclusion || decision.one_line_conclusion || detail.summary.one_line_conclusion,
  })

  const headlineVerdict = sanitizeBusinessText(
    overview?.headline_zh
    || overview?.headline_verdict
    || decision.headline_zh
    || decision.headline_verdict
    || detail.summary.headline_verdict,
    deriveRationaleSummary({ buckets: bucketCountMap, verdict: verdictRaw, materialInsufficiency }),
  )

  const oneLineConclusion = sanitizeBusinessText(
    overview?.one_line_conclusion || decision.one_line_conclusion || detail.summary.one_line_conclusion,
    headlineVerdict,
  )

  const rationaleDisplay = resolveLocalizedRationale({
    rationale: detail.summary.rationale || decision.rationale,
    rationaleZh: detail.summary.rationale_zh || decision.rationale_zh || overview?.rationale_zh,
    verdict: verdictRaw,
    buckets: bucketCountMap,
    materialInsufficiency,
  })

  const rate = coverage.coverage_rate
  const coverageRateLabel = rate == null
    ? '—'
    : `${Math.round(Number(rate) <= 1 ? Number(rate) * 100 : Number(rate))}%`

  const drillDownCandidates: ConclusionOverviewViewModel['drillDownTabs'] =
    reviewType === 'super_agent'
      ? [
          { tab: 'findings', label: '发现与证据' },
          { tab: 'routes', label: '审查路线' },
          { tab: 'closure', label: '结论与闭环' },
          { tab: 'quality', label: '运行质量' },
        ]
      : [
          { tab: 'findings', label: '审查发现' },
          { tab: 'check_items', label: '检查项' },
          { tab: 'cross_doc', label: '文文一致性' },
          { tab: 'coverage', label: '覆盖矩阵' },
          { tab: 'decision', label: '裁定结论' },
          { tab: 'report', label: '审查报告' },
        ]
  const drillDownTabs = drillDownCandidates.filter((entry) => {
    if (reviewType === 'super_agent') {
      const aliases: Record<string, string[]> = {
        findings: ['findings', 'check_items', 'evidences'],
        routes: ['routes', 'flow', 'committee', 'events'],
        closure: ['closure', 'decision', 'report'],
        quality: ['quality', 'events'],
      }
      const keys = aliases[entry.tab] || [entry.tab]
      return keys.some((key) => detail.visible_tabs.includes(key))
    }
    return detail.visible_tabs.includes(entry.tab)
  })

  return {
    taskDisplayName: deriveReviewTaskDisplayName(detail),
    reviewSubjectLines: buildReviewSubjectLines(reviewScope),
    reviewPlanLines: buildReviewPlanLines(reviewScope, reviewModeLabel),
    reviewModeLabel,
    actualScopeLines: actualScope,
    documentTypePending: Boolean(reviewScope.document_type_pending),
    headlineVerdict,
    oneLineConclusion,
    verdict: verdictLabel,
    verdictLabel,
    rationale: textValue(detail.summary.rationale || decision.rationale),
    rationaleDisplay,
    materialInsufficiency,
    bucketCards,
    priorityItems: withUniquePriorityItemIds(
      (priorityRaw || [])
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
        .map((item) => {
          const localized = sanitizePriorityItemText(item)
          return {
            id: textValue(item.id),
            title: localized.title || textValue(item.title, '审查项'),
            business_bucket: textValue(item.business_bucket, 'manual_review'),
            business_bucket_label: textValue(item.business_bucket_label, '待人工确认'),
            severity: textValue(item.severity) || undefined,
            judgment: textValue(item.judgment) || undefined,
            reason: localized.reason || textValue(item.reason) || undefined,
            missing_reason: localized.missingReason || textValue(item.missing_reason) || undefined,
            recommendation: localized.recommendation || textValue(item.recommendation) || undefined,
            tab_hint: textValue(item.tab_hint) as UnifiedWorkbenchTabKey | undefined,
          }
        }),
    ),
    coverageSummary: {
      totalCheckItems: numberValue(coverage.total_check_items),
      verifiedCount: numberValue(coverage.verified_count),
      evidenceCount: numberValue(coverage.evidence_count || detail.metrics.evidence_count),
      coverageRateLabel,
      documentTypeLabel: textValue(coverage.document_type_label),
      notes: Array.isArray(coverage.notes) ? coverage.notes.map((n) => textValue(n)).filter(Boolean) : [],
    },
    drillDownTabs,
  }
}

export function mergeConclusionOverviewDecision(
  vm: ConclusionOverviewViewModel,
  decision: Record<string, unknown>,
): ConclusionOverviewViewModel {
  return buildConclusionOverviewFromDetail(
    {
      review_id: '',
      name: '',
      review_type: 'super_agent',
      status: '',
      workbench_phase: 'completed',
      visible_tabs: [],
      current_step: '',
      metrics: {
        finding_count: 0,
        rid_count: 0,
        open_rid_count: 0,
        evidence_count: 0,
        conflict_count: 0,
        requires_arbitration: false,
      },
      summary: {
        verdict: vm.verdict,
        verdict_label_zh: vm.verdictLabel,
        rationale: vm.rationale,
        rationale_zh: vm.rationaleDisplay,
        requires_arbitration: false,
        arbitration_status: '',
        report_available: false,
        headline_verdict: vm.headlineVerdict,
        one_line_conclusion: vm.oneLineConclusion,
        review_mode_label: vm.reviewModeLabel,
      },
      conclusion_overview: {
        headline_verdict: vm.headlineVerdict,
        headline_zh: vm.headlineVerdict,
        one_line_conclusion: vm.oneLineConclusion,
        verdict_label_zh: vm.verdictLabel,
        rationale_zh: vm.rationaleDisplay,
        material_insufficiency: vm.materialInsufficiency,
        issue_buckets: Object.fromEntries(vm.bucketCards.map((c) => [c.key, c.count])),
        bucket_labels: Object.fromEntries(vm.bucketCards.map((c) => [c.key, c.label])),
        review_scope: {
          review_mode_label: vm.reviewModeLabel,
          actual_scope: vm.actualScopeLines,
          document_type_pending: vm.documentTypePending,
          material_summary_lines: vm.reviewSubjectLines,
          review_plan_lines: vm.reviewPlanLines,
        },
        priority_items: vm.priorityItems.map((item) => ({ ...item })) as Array<Record<string, unknown>>,
        coverage_summary: {
          total_check_items: vm.coverageSummary.totalCheckItems,
          verified_count: vm.coverageSummary.verifiedCount,
          evidence_count: vm.coverageSummary.evidenceCount,
          coverage_rate: vm.coverageSummary.coverageRateLabel === '—' ? null : vm.coverageSummary.coverageRateLabel,
          document_type_label: vm.coverageSummary.documentTypeLabel,
          notes: vm.coverageSummary.notes,
        },
      },
      error: '',
      created_at: '',
      updated_at: '',
    },
    'super_agent',
    decision,
  )
}
