import {
  BUSINESS_BUCKET_LABELS,
  type BusinessBucketKey,
} from '@/features/unified-review-workbench/utils/conclusionOverviewModel'
import { resolveBucketLabel } from '@/features/unified-review-workbench/utils/bucketTone'

const VERDICT_LABELS: Record<string, string> = {
  pass: '通过',
  passed: '通过',
  approved: '通过',
  approve: '通过',
  conditional_pass: '有条件通过',
  conditionally_approved: '有条件通过',
  conditional_rejection: '材料不足，暂无法完成完整审查',
  conditionally_rejected: '材料不足，暂无法完成完整审查',
  blocked: '材料不足，暂无法完成完整审查',
  insufficient_materials: '材料不足，暂无法完成完整审查',
  material_insufficient: '材料不足，暂无法完成完整审查',
  reject: '不通过',
  rejected: '不通过',
  failed: '不通过',
  fail: '不通过',
  not_approved: '不通过',
  not_passed: '不通过',
  conditional: '有条件通过',
  needs_human_review: '待人工确认',
  needs_review: '待人工确认',
  pending: '待确认',
}

const JUDGMENT_LABELS: Record<string, string> = {
  satisfied: '已满足',
  passed: '通过',
  pass: '通过',
  compliant: '符合',
  not_satisfied: '未满足',
  insufficient_evidence: '证据不足',
  not_checked: '未检查',
  blocked: '受阻/待补材料',
  failed: '不通过',
  non_compliant: '不符合',
  nonconforming: '不合格',
  open: '待处理',
  pending: '待处理',
  closed: '已关闭',
  resolved: '已解决',
}

const EVIDENCE_STATUS_LABELS: Record<string, string> = {
  supported: '已印证',
  verified: '已印证',
  evidence_supported: '已印证',
  missing: '待补证',
  insufficient: '证据不足',
  insufficient_evidence: '证据不足',
  not_checked: '未检查',
  blocked: '受阻',
  pending: '待补证',
}

const WORKBENCH_STATUS_LABELS: Record<string, string> = {
  completed: '已完成',
  pending: '待处理',
  running: '执行中',
  failed: '失败',
  open: '待处理',
  closed: '已关闭',
  resolved: '已解决',
  ...JUDGMENT_LABELS,
  ...EVIDENCE_STATUS_LABELS,
}

const MATERIAL_INSUFFICIENT_RATIONALE =
  '当前资料包不足以支撑完整 GNC 关键设计审查，系统仅完成可审范围内的结构、内容和局部专业检查。请先补齐关键设计说明、故障分析、算法验证矩阵等材料后再复审。'

export function containsCjk(text: string): boolean {
  return /[\u4e00-\u9fff]/.test(text)
}

export function isRawEnumToken(value: unknown): boolean {
  const token = String(value ?? '').trim()
  return Boolean(token) && token.includes('_') && /^[a-z][a-z0-9_]*$/i.test(token)
}

export function isLikelyEnglishBusinessText(value: unknown): boolean {
  const text = String(value ?? '').trim()
  if (!text || containsCjk(text) || isRawEnumToken(text)) return false
  const latin = (text.match(/[a-zA-Z]/g) || []).length
  return latin >= 12
}

export function isPredominantlyEnglishText(value: unknown): boolean {
  const text = String(value ?? '').trim()
  if (!text) return false
  const latin = (text.match(/[a-zA-Z]/g) || []).length
  const cjk = (text.match(/[\u4e00-\u9fff]/g) || []).length
  if (latin >= 12 && latin > cjk * 2) return true
  return isLikelyEnglishBusinessText(text)
}

function isUsableChineseBusinessText(value: unknown): boolean {
  const text = String(value ?? '').trim()
  if (!text) return false
  if (isPredominantlyEnglishText(text)) return false
  if (isLikelyEnglishBusinessText(text)) return false
  if (containsCjk(text)) return true
  return false
}

export function resolveVerdictLabel(raw: unknown, fallback = '待确认'): string {
  const text = String(raw ?? '').trim()
  if (!text) return fallback
  const mapped = VERDICT_LABELS[text.toLowerCase()]
  if (mapped) return mapped
  if (containsCjk(text)) return text
  if (isRawEnumToken(text)) return fallback
  if (isLikelyEnglishBusinessText(text)) return fallback
  return text
}

export function resolveWorkbenchStatusText(raw: unknown, fallback = '待确认'): string {
  const text = String(raw ?? '').trim()
  if (!text) return fallback
  const key = text.toLowerCase()
  if (WORKBENCH_STATUS_LABELS[key]) return WORKBENCH_STATUS_LABELS[key]
  const bucket = resolveBucketLabel(key)
  if (bucket) return bucket
  if (containsCjk(text)) return text
  if (isRawEnumToken(text)) return fallback
  return text
}

export function resolveJudgmentLabel(raw: unknown, fallback = ''): string {
  const text = String(raw ?? '').trim()
  if (!text) return fallback
  const mapped = JUDGMENT_LABELS[text.toLowerCase()]
  if (mapped) return mapped
  const bucket = resolveBucketLabel(text)
  if (bucket) return bucket
  if (containsCjk(text)) return text
  if (isRawEnumToken(text)) return fallback || '待确认'
  return text
}

export function resolveEvidenceStatusLabel(raw: unknown, fallback = '待补证'): string {
  const text = String(raw ?? '').trim()
  if (!text) return fallback
  const mapped = EVIDENCE_STATUS_LABELS[text.toLowerCase()]
  if (mapped) return mapped
  if (containsCjk(text)) return text
  if (isRawEnumToken(text)) return fallback
  return text
}

export interface SanitizeBusinessTextOptions {
  hideEnglish?: boolean
  enumMap?: Record<string, string>
}

export function sanitizeBusinessText(
  value: unknown,
  fallback: string,
  options: SanitizeBusinessTextOptions = {},
): string {
  const text = String(value ?? '').trim()
  if (!text) return fallback
  const enumMapped = options.enumMap?.[text.toLowerCase()]
  if (enumMapped) return enumMapped
  if (isRawEnumToken(text)) {
    return resolveVerdictLabel(text, fallback)
      !== fallback
      ? resolveVerdictLabel(text, fallback)
      : resolveWorkbenchStatusText(text, fallback)
  }
  if (options.hideEnglish !== false && isLikelyEnglishBusinessText(text)) return fallback
  if (containsCjk(text)) return text
  return fallback
}

export type DisplayNameKind = 'expert' | 'check_item' | 'field'

export function resolveDisplayName(raw: unknown, kind: DisplayNameKind = 'check_item'): string {
  const text = String(raw ?? '').trim()
  if (!text) return kind === 'expert' ? '专业审查项' : '审查项'
  if (containsCjk(text)) return text
  if (isRawEnumToken(text) || isLikelyEnglishBusinessText(text)) {
    return kind === 'expert' ? '专业审查项' : '审查项'
  }
  return text
}

export function resolveCheckItemTitle(
  raw: unknown,
  bucket?: BusinessBucketKey | string,
): string {
  const text = String(raw ?? '').trim()
  if (!text) return '审查项'
  if (containsCjk(text)) return text
  if (isLikelyEnglishBusinessText(text)) {
    return bucket === 'insufficient_evidence'
      ? '该检查项需补充材料后确认'
      : '该检查项待进一步确认'
  }
  if (isRawEnumToken(text)) return '审查项'
  return text
}

export function deriveRationaleSummary(input: {
  buckets?: Record<string, number>
  verdict?: string
  materialInsufficiency?: boolean
}): string {
  const verdict = String(input.verdict ?? '').trim().toLowerCase()
  if (
    input.materialInsufficiency
    || verdict === 'material_insufficient'
    || verdict === 'conditional_rejection'
    || verdict === 'conditionally_rejected'
    || verdict === 'insufficient_materials'
    || verdict === 'blocked'
  ) {
    return MATERIAL_INSUFFICIENT_RATIONALE
  }
  const buckets = input.buckets || {}
  if (buckets.severe_error) return '存在严重错误或关键风险，建议暂停放行并优先整改后再复审。'
  if (buckets.cross_document_inconsistency) return '发现跨文档术语、指标或约束不一致，需对齐任务书、需求与报告后再复审。'
  if (buckets.template_structure_nonconforming) return '模板或文档结构存在缺项/不合格，需先补齐结构与必填章节后再复审。'
  if (buckets.content_nonconforming) return '存在内容不合格项，需按专业意见完成整改并补充支撑材料。'
  if (buckets.insufficient_evidence) return '部分审查点证据不足，需补充材料后复审（不代表设计不通过）。'
  if (buckets.manual_review) return '部分审查点仍需人工确认，请结合原文证据与专业意见复核。'
  if (buckets.verified && !Object.entries(buckets).some(([key, count]) => key !== 'verified' && Number(count) > 0)) {
    return '审查点已印证，可按流程进入下一环节。'
  }
  return '审查已完成，请查看分桶明细与优先整改项。'
}

export function resolveLocalizedRationale(input: {
  rationale?: unknown
  rationaleZh?: unknown
  verdict?: unknown
  buckets?: Record<string, number>
  materialInsufficiency?: boolean
}): string {
  const derived = deriveRationaleSummary({
    buckets: input.buckets,
    verdict: String(input.verdict ?? ''),
    materialInsufficiency: input.materialInsufficiency,
  })
  const zh = String(input.rationaleZh ?? '').trim()
  if (isUsableChineseBusinessText(zh)) return zh
  const rationale = String(input.rationale ?? '').trim()
  if (isUsableChineseBusinessText(rationale)) return rationale
  return derived
}

export function resolveLocalizedVerdict(input: {
  verdict?: unknown
  verdictLabelZh?: unknown
  headline?: unknown
  oneLine?: unknown
}): string {
  const zh = String(input.verdictLabelZh ?? '').trim()
  if (zh) return zh
  const mapped = resolveVerdictLabel(input.verdict)
  if (mapped !== '待确认' || !isRawEnumToken(input.verdict)) return mapped
  const headline = String(input.headline ?? input.oneLine ?? '').trim()
  if (headline && containsCjk(headline)) return headline
  return mapped
}

export function resolveReviewModeLabel(raw: unknown, reviewType?: string): string {
  const text = String(raw ?? '').trim()
  if (text.includes('Super Agent')) return '智能审查'
  if (text) return text
  if (reviewType === 'super_agent') return '智能审查'
  if (reviewType === 'gnc') return 'GNC 审查'
  return '通用审查'
}

export function sanitizePriorityItemText(item: {
  title?: unknown
  reason?: unknown
  missing_reason?: unknown
  recommendation?: unknown
  business_bucket?: unknown
}): {
  title: string
  reason: string
  missingReason: string
  recommendation: string
} {
  const bucket = String(item.business_bucket ?? '')
  return {
    title: resolveCheckItemTitle(item.title, bucket),
    reason: sanitizeBusinessText(item.reason, '', { hideEnglish: true }),
    missingReason: sanitizeBusinessText(item.missing_reason, '', { hideEnglish: false }),
    recommendation: sanitizeBusinessText(item.recommendation, '', { hideEnglish: true }),
  }
}
