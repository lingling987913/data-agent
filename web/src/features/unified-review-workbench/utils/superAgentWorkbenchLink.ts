import { buildUnifiedReviewWorkbenchHref } from '@/features/unified-review-workbench/tabNavigation'
import type { UnifiedReviewType, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'
import type { SuperAgentRun } from '@/features/super-agent/types'

function textValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function gncResultRecord(run: SuperAgentRun): Record<string, unknown> {
  return (run.gnc_review_result && typeof run.gnc_review_result === 'object')
    ? run.gnc_review_result as Record<string, unknown>
    : {}
}

function reviewPlusResultRecord(run: SuperAgentRun): Record<string, unknown> {
  return (run.review_plus_result && typeof run.review_plus_result === 'object')
    ? run.review_plus_result as Record<string, unknown>
    : {}
}

export function resolveSuperAgentWorkbenchReviewType(run: SuperAgentRun): UnifiedReviewType | null {
  const reviewId = resolveSuperAgentWorkbenchReviewId(run)
  if (!reviewId) return null

  const route = String(run.route_decision?.route || run.requested_route || '').toLowerCase()
  if (route === 'gnc_review' || route === 'gnc_review_only') return 'gnc'
  if (route === 'review_plus') return 'review_plus'
  if (route === 'hybrid') {
    return resolveSuperAgentReviewPlusId(run) ? 'review_plus' : 'gnc'
  }
  if (route === 'smart') {
    if (resolveSuperAgentReviewPlusId(run)) return 'review_plus'
    if (resolveSuperAgentGncId(run)) return 'gnc'
    if (hasNativeSuperAgentWorkbench(run)) return 'super_agent'
  }
  if (run.gnc_review_result && Object.keys(run.gnc_review_result).length > 0) return 'gnc'
  if (hasNativeSuperAgentWorkbench(run)) return 'super_agent'
  if (run.review_plus_result && Object.keys(run.review_plus_result).length > 0) return 'review_plus'
  return null
}

function resolveSuperAgentGncId(run: SuperAgentRun): string {
  const gnc = gncResultRecord(run)
  return textValue(run.route_decision?.gnc_review_id)
    || textValue(gnc.gnc_review_id)
    || textValue(gnc.review_id)
}

function resolveSuperAgentReviewPlusId(run: SuperAgentRun): string {
  const reviewPlus = reviewPlusResultRecord(run)
  return textValue(reviewPlus.review_plus_id)
}

function hasNativeSuperAgentWorkbench(run: SuperAgentRun): boolean {
  const reviewPlus = reviewPlusResultRecord(run)
  return textValue(reviewPlus.review_mode) === 'smart_committee'
    || Boolean(reviewPlus.smart_task_board)
    || Boolean(reviewPlus.specialist_reviews)
    || Boolean(run.report_markdown)
}

export function resolveSuperAgentWorkbenchReviewId(run: SuperAgentRun): string {
  const route = String(run.route_decision?.route || run.requested_route || '').toLowerCase()
  const gncId = resolveSuperAgentGncId(run)
  const explicitReviewPlusId = resolveSuperAgentReviewPlusId(run)
  const sourceReviewId = textValue(run.source_review_id)
  const reviewPlusId = explicitReviewPlusId || sourceReviewId

  if (route === 'gnc_review' || route === 'gnc_review_only') {
    return gncId || sourceReviewId
  }
  if (route === 'review_plus') return reviewPlusId
  if (route === 'hybrid') return reviewPlusId || gncId
  if (route === 'smart') {
    if (explicitReviewPlusId) return explicitReviewPlusId
    return gncId || sourceReviewId || (hasNativeSuperAgentWorkbench(run) ? run.run_id : '')
  }
  return reviewPlusId || gncId || sourceReviewId || (hasNativeSuperAgentWorkbench(run) ? run.run_id : '')
}

export function resolveSuperAgentNativeWorkbenchType(run: SuperAgentRun): UnifiedReviewType | null {
  if (!hasNativeSuperAgentWorkbench(run)) return null
  return 'super_agent'
}

export function buildSuperAgentWorkbenchHref(
  run: SuperAgentRun,
  options?: { tab?: UnifiedWorkbenchTabKey | string },
): string | null {
  const reviewType = resolveSuperAgentWorkbenchReviewType(run)
  const reviewId = resolveSuperAgentWorkbenchReviewId(run)
  if (!reviewType || !reviewId) return null
  const tab = options?.tab ?? defaultWorkbenchTabForRun(run)
  return buildUnifiedReviewWorkbenchHref(reviewType, reviewId, tab ? { tab } : undefined)
}

export function buildSuperAgentRunWorkbenchHref(
  run: SuperAgentRun,
  options?: { tab?: UnifiedWorkbenchTabKey | string },
): string | null {
  if (!run.run_id) return null
  const params = new URLSearchParams({
    reviewType: 'super_agent',
    reviewId: run.run_id,
  })
  const tab = options?.tab ?? defaultWorkbenchTabForRun(run)
  if (tab) params.set('tab', tab)
  return `/review/workbench?${params.toString()}`
}

export function defaultWorkbenchTabForRun(run: SuperAgentRun): UnifiedWorkbenchTabKey | undefined {
  const reviewType = resolveSuperAgentWorkbenchReviewType(run)
  if (reviewType === 'gnc') {
    const gnc = gncResultRecord(run)
    const phase = String(gnc.workbench_phase || '').toLowerCase()
    const status = String(gnc.status || run.status || '').toLowerCase()
    const arbitrationStatus = String(gnc.arbitration_status || '').toLowerCase()
    const requiresArbitration = Boolean(gnc.requires_arbitration)

    if (
      phase === 'arbitration'
      || status.includes('arbitration')
      || arbitrationStatus === 'pending'
      || (requiresArbitration && arbitrationStatus !== 'resolved' && arbitrationStatus !== 'completed')
    ) {
      return 'arbitration'
    }

    if (status === 'completed' || phase === 'completed') {
      const openRid = Number(gnc.open_rid_count ?? gnc.open_rid ?? 0)
      if (openRid > 0) return 'rid'
      return 'decision'
    }

    return 'overview'
  }

  if (reviewType === 'review_plus') {
    const review = reviewPlusResultRecord(run)
    const status = String(review.status || run.status || '').toLowerCase()
    const report = review.report && typeof review.report === 'object'
      ? review.report as Record<string, unknown>
      : {}
    const reportMarkdown = String(
      report.markdown || report.content || review.report_markdown || '',
    ).trim()
    if (status === 'completed' || reportMarkdown) return 'report'
    return 'overview'
  }

  if (reviewType === 'super_agent') {
    return 'overview'
  }

  return undefined
}
