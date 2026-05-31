import { fetchApiJson } from '@/lib/apiClient'
import type { UnifiedReviewType, UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'

const PREFIX = '/api/v1/review-workbench'

function basePath(reviewType: UnifiedReviewType, reviewId: string): string {
  return `${PREFIX}/${reviewType}/${reviewId}`
}

export async function getUnifiedWorkbenchDetail(
  reviewType: UnifiedReviewType,
  reviewId: string,
): Promise<UnifiedReviewWorkbenchDetail> {
  return fetchApiJson<UnifiedReviewWorkbenchDetail>(basePath(reviewType, reviewId))
}

export async function getUnifiedWorkbenchPhase(
  reviewType: UnifiedReviewType,
  reviewId: string,
): Promise<{ workbench_phase: string }> {
  return fetchApiJson<{ workbench_phase: string }>(`${basePath(reviewType, reviewId)}/phase`)
}

export async function getUnifiedWorkbenchResource<T>(
  reviewType: UnifiedReviewType,
  reviewId: string,
  resource: string,
): Promise<T> {
  return fetchApiJson<T>(`${basePath(reviewType, reviewId)}/${resource}`)
}

export async function patchGncRidItem(
  reviewId: string,
  ridId: string,
  body: { status?: string; notes?: string; comment?: string },
): Promise<Record<string, unknown>> {
  return fetchApiJson<Record<string, unknown>>(
    `${PREFIX}/gnc/${reviewId}/rid/${encodeURIComponent(ridId)}`,
    { method: 'PATCH', body: JSON.stringify(body) },
  )
}

export async function submitGncArbitration(
  reviewId: string,
  body: {
    status: string
    decisions: Array<Record<string, unknown>>
    notes?: string
  },
): Promise<Record<string, unknown>> {
  return fetchApiJson<Record<string, unknown>>(
    `${PREFIX}/gnc/${reviewId}/arbitration`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}
