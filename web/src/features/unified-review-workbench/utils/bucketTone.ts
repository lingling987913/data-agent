import {
  BUSINESS_BUCKET_LABELS,
  type BusinessBucketKey,
} from '@/features/unified-review-workbench/utils/conclusionOverviewModel'

export interface BucketToneClasses {
  card: string
  badge: string
  listItem: string
}

/** 业务分桶 → 稳定 Tailwind 语义色（card / badge / listItem） */
export const BUCKET_TONE_MAP: Record<BusinessBucketKey, BucketToneClasses> = {
  severe_error: {
    card: 'border-red-300 bg-red-50 text-red-900',
    badge: 'border-red-400 bg-red-100 text-red-900',
    listItem: 'border-red-200 bg-red-50/60 border-l-red-600',
  },
  content_nonconforming: {
    card: 'border-orange-400 bg-orange-50 text-orange-950',
    badge: 'border-orange-400 bg-orange-100 text-orange-950',
    listItem: 'border-orange-300 bg-orange-50/60 border-l-orange-600',
  },
  template_structure_nonconforming: {
    card: 'border-amber-300 bg-amber-50 text-amber-950',
    badge: 'border-amber-400 bg-amber-100 text-amber-950',
    listItem: 'border-amber-200 bg-amber-50/60 border-l-amber-600',
  },
  cross_document_inconsistency: {
    card: 'border-purple-300 bg-purple-50 text-purple-950',
    badge: 'border-purple-400 bg-purple-100 text-purple-950',
    listItem: 'border-purple-200 bg-purple-50/60 border-l-purple-600',
  },
  insufficient_evidence: {
    card: 'border-blue-300 bg-blue-50 text-blue-950',
    badge: 'border-blue-400 bg-blue-100 text-blue-950',
    listItem: 'border-blue-200 bg-blue-50/60 border-l-blue-600',
  },
  manual_review: {
    card: 'border-slate-300 bg-slate-50 text-slate-700',
    badge: 'border-slate-400 bg-slate-100 text-slate-700',
    listItem: 'border-slate-200 bg-slate-50/60 border-l-slate-500',
  },
  verified: {
    card: 'border-emerald-300 bg-emerald-50 text-emerald-900',
    badge: 'border-emerald-400 bg-emerald-100 text-emerald-900',
    listItem: 'border-emerald-200 bg-emerald-50/60 border-l-emerald-600',
  },
}

const BUCKET_ALIASES: Record<string, BusinessBucketKey> = {
  critical: 'severe_error',
  rid_open: 'severe_error',
  nonconforming: 'content_nonconforming',
  major: 'content_nonconforming',
  blocked: 'insufficient_evidence',
  evidence_supported: 'verified',
  rid_closed: 'verified',
  passed: 'verified',
  attention: 'manual_review',
}

const DEFAULT_TONE: BucketToneClasses = {
  card: 'border-border/20 bg-surface text-primary',
  badge: 'border-border/15 bg-surface text-muted',
  listItem: 'border-border/15 bg-background border-l-border/40',
}

export function normalizeBucketKey(raw: unknown): BusinessBucketKey | string {
  const key = String(raw ?? '').trim().toLowerCase()
  if (!key) return ''
  if (key in BUCKET_TONE_MAP) return key as BusinessBucketKey
  if (key in BUCKET_ALIASES) return BUCKET_ALIASES[key]
  return key
}

function toneFor(key: unknown): BucketToneClasses {
  const normalized = normalizeBucketKey(key)
  if (normalized && normalized in BUCKET_TONE_MAP) {
    return BUCKET_TONE_MAP[normalized as BusinessBucketKey]
  }
  return DEFAULT_TONE
}

export function bucketToneClass(key: unknown): string {
  return toneFor(key).card
}

export function bucketBadgeClass(key: unknown): string {
  return toneFor(key).badge
}

export function bucketListItemClass(key: unknown): string {
  return toneFor(key).listItem
}

export function resolveItemBucketKey(item: Record<string, unknown>): string {
  return normalizeBucketKey(
    item.business_bucket || item.conclusion_bucket || item.status || item.severity,
  )
}

function isKnownBucketToken(value: string): boolean {
  const normalized = normalizeBucketKey(value)
  return Boolean(normalized && normalized in BUCKET_TONE_MAP)
}

/** 分桶 key → 中文标签（避免 UI 暴露英文 bucket 名） */
export function resolveBucketLabel(key: unknown): string {
  const normalized = normalizeBucketKey(key)
  if (normalized && normalized in BUSINESS_BUCKET_LABELS) {
    return BUSINESS_BUCKET_LABELS[normalized as BusinessBucketKey]
  }
  return ''
}

export function resolveConclusionBadge(item: Record<string, unknown>): { bucketKey: string; label: string } {
  const bucketKey = resolveItemBucketKey(item)
  const explicitLabel = String(
    item.business_bucket_label || item.status_label || item.conclusion_label || '',
  ).trim()
  if (explicitLabel && !isKnownBucketToken(explicitLabel)) {
    return { bucketKey, label: explicitLabel }
  }
  const fromBucket = resolveBucketLabel(bucketKey)
  if (fromBucket) return { bucketKey, label: fromBucket }
  return { bucketKey, label: explicitLabel || '待人工确认' }
}
