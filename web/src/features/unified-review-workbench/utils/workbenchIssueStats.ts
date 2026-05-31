import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'
import { BUSINESS_BUCKET_ORDER } from '@/features/unified-review-workbench/utils/conclusionOverviewModel'

export const PROBLEM_BUCKET_KEYS = BUSINESS_BUCKET_ORDER.filter((key) => key !== 'verified')

function numberValue(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

export function sumProblemBuckets(buckets: Record<string, unknown> | undefined): number {
  if (!buckets) return 0
  return PROBLEM_BUCKET_KEYS.reduce((sum, key) => sum + numberValue(buckets[key]), 0)
}

/** Non-verified bucket total — aligns with backend problem_count. */
export function resolveWorkbenchProblemCount(detail: UnifiedReviewWorkbenchDetail): number {
  const explicit = numberValue(detail.metrics.problem_count)
  if (explicit > 0) return explicit
  const fromBuckets = sumProblemBuckets(detail.conclusion_overview?.issue_buckets)
  if (fromBuckets > 0) return fromBuckets
  return numberValue(detail.metrics.finding_count)
}

export function resolveWorkbenchPendingConfirm(detail: UnifiedReviewWorkbenchDetail): number {
  const explicit = numberValue(detail.metrics.pending_confirm)
  if (explicit > 0) return explicit
  return numberValue(detail.metrics.open_rid_count)
    + numberValue(detail.conclusion_overview?.issue_buckets?.manual_review)
}

export function resolveWorkbenchCheckItemCount(detail: UnifiedReviewWorkbenchDetail): number {
  const explicit = numberValue(detail.metrics.check_item_count)
  if (explicit > 0) return explicit
  return numberValue(detail.conclusion_overview?.coverage_summary?.total_check_items)
}
