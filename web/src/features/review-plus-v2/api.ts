/**
 * Review-Plus API — /api/v1/review-plus/reviews
 */

import {
  buildAeroAuthHeaders,
  fetchAeroDomainApi,
  fetchAeroDomainJson,
} from '@/lib/apiClient'
import type {
  ReviewPlusGatekeepingResult,
  ReviewPlusFinding,
  ReviewPlusMaterialItem,
  ReviewPlusParserType,
  ReviewPlusReport,
  ReviewPlusTaskDetail,
  ReviewPlusTaskSummary,
} from './types'

const REVIEW_PLUS_PREFIX = '/api/v1/review-plus/reviews'

async function fetchReviewPlusPath(path: string, init?: RequestInit): Promise<Response> {
  return fetchAeroDomainApi(`${REVIEW_PLUS_PREFIX}${path}`, init)
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  return fetchAeroDomainJson<T>(`${REVIEW_PLUS_PREFIX}${path}`, init)
}

export async function createReviewPlus(body: { name: string }): Promise<ReviewPlusTaskDetail> {
  return apiFetch<ReviewPlusTaskDetail>('', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function listReviewPlus(params?: {
  page?: number
  size?: number
  status?: string
}): Promise<{ items: ReviewPlusTaskSummary[]; total: number }> {
  const qs = new URLSearchParams()
  if (params?.page) qs.set('page', String(params.page))
  if (params?.size) qs.set('size', String(params.size))
  if (params?.status) qs.set('status', params.status)
  const q = qs.toString()
  const res = await fetchReviewPlusPath(q ? `?${q}` : '')
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API error ${res.status}: ${text}`)
  }
  const json = await res.json()
  const data = json.data as { items?: ReviewPlusTaskSummary[]; total?: number } | ReviewPlusTaskSummary[] | undefined
  if (Array.isArray(data)) {
    return { items: data, total: Number(json.pagination?.total ?? json.total ?? data.length) }
  }
  const items = data?.items || []
  return {
    items,
    total: Number(json.pagination?.total ?? json.total ?? data?.total ?? items.length),
  }
}

export async function getReviewPlusDetail(reviewId: string): Promise<ReviewPlusTaskDetail> {
  return apiFetch<ReviewPlusTaskDetail>(`/${reviewId}`)
}

export async function classifyReviewPlusMaterials(reviewId: string): Promise<ReviewPlusTaskDetail> {
  return apiFetch<ReviewPlusTaskDetail>(`/${reviewId}/classify`, { method: 'POST' })
}

export async function parseReviewPlusMaterials(
  reviewId: string,
  options?: { forceReparse?: boolean },
): Promise<{
  review_plus_id: string
  status: string
  parse_artifact: Record<string, unknown>
  batch_summary: Record<string, unknown>
  materials: ReviewPlusMaterialItem[]
}> {
  return apiFetch(`/${reviewId}/parse`, {
    method: 'POST',
    body: JSON.stringify({ force_reparse: Boolean(options?.forceReparse) }),
  })
}

export async function uploadReviewPlusMaterials(
  reviewId: string,
  files: File[],
  parserType: ReviewPlusParserType = 'auto',
): Promise<{ review_plus_id: string; status: string; materials: ReviewPlusMaterialItem[] }> {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  formData.append('parser_type', parserType)

  const res = await fetchReviewPlusPath(`/${reviewId}/upload`, {
    method: 'POST',
    headers: buildAeroAuthHeaders(false),
    body: formData,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`上传失败 ${res.status}: ${text}`)
  }
  const json = await res.json()
  return json.data
}

export async function reparseReviewPlusMaterial(
  reviewId: string,
  materialName: string,
  parserType: ReviewPlusParserType,
): Promise<{ status: string; material: ReviewPlusMaterialItem | null; gatekeeping_result?: ReviewPlusGatekeepingResult }> {
  return apiFetch(`/${reviewId}/materials/${encodeURIComponent(materialName)}/reparse`, {
    method: 'POST',
    body: JSON.stringify({ parser_type: parserType }),
  })
}

export async function updateReviewPlusMaterialRole(
  reviewId: string,
  materialName: string,
  body: { role: string; document_version?: string; baseline_id?: string },
): Promise<{ status: string; material: ReviewPlusMaterialItem }> {
  return apiFetch(`/${reviewId}/materials/${encodeURIComponent(materialName)}/role`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function getReviewPlusGatekeeping(reviewId: string): Promise<ReviewPlusGatekeepingResult> {
  return apiFetch<ReviewPlusGatekeepingResult>(`/${reviewId}/gatekeeping`)
}

export async function recheckReviewPlusGatekeeping(reviewId: string): Promise<ReviewPlusGatekeepingResult> {
  return apiFetch<ReviewPlusGatekeepingResult>(`/${reviewId}/gatekeeping/recheck`, { method: 'POST' })
}

export async function startReviewPlus(reviewId: string): Promise<ReviewPlusTaskDetail> {
  return apiFetch<ReviewPlusTaskDetail>(`/${reviewId}/start`, { method: 'POST' })
}

export async function continueReviewPlus(reviewId: string): Promise<ReviewPlusTaskDetail> {
  try {
    return await apiFetch<ReviewPlusTaskDetail>(`/${reviewId}/continue`, { method: 'POST' })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (message.includes('404') && /not\s*found/i.test(message)) {
      return apiFetch<ReviewPlusTaskDetail>(`/${reviewId}/start`, { method: 'POST' })
    }
    throw error
  }
}

export async function restartReviewPlus(reviewId: string): Promise<ReviewPlusTaskDetail> {
  return apiFetch<ReviewPlusTaskDetail>(`/${reviewId}/restart`, { method: 'POST' })
}

export async function getReviewPlusFindings(reviewId: string): Promise<ReviewPlusFinding[]> {
  return apiFetch<ReviewPlusFinding[]>(`/${reviewId}/findings`)
}

export async function getReviewPlusReport(reviewId: string): Promise<ReviewPlusReport | null> {
  return apiFetch<ReviewPlusReport | null>(`/${reviewId}/report`)
}

export async function getReviewPlusReportMarkdown(reviewId: string): Promise<string> {
  const res = await fetchReviewPlusPath(`/${reviewId}/report.md`, {
    headers: buildAeroAuthHeaders(false),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`获取报告失败 ${res.status}: ${text}`)
  }
  return res.text()
}

export async function getReviewPlusCrossDocumentItems(
  reviewId: string,
): Promise<Array<Record<string, unknown>>> {
  return apiFetch<Array<Record<string, unknown>>>(`/${reviewId}/cross-document-review-items`)
}

export async function getReviewPlusTraceability(reviewId: string): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/${reviewId}/traceability`)
}

export async function confirmReviewPlusTraceLink(
  reviewId: string,
  linkId: string,
  body: { rationale?: string; user?: string } = {},
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(
    `/${reviewId}/traceability/links/${encodeURIComponent(linkId)}/confirm`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  )
}

export async function rejectReviewPlusTraceLink(
  reviewId: string,
  linkId: string,
  body: { rationale: string; user?: string },
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(
    `/${reviewId}/traceability/links/${encodeURIComponent(linkId)}/reject`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  )
}

export async function getReviewPlusEvents(reviewId: string): Promise<Array<Record<string, unknown>>> {
  return apiFetch<Array<Record<string, unknown>>>(`/${reviewId}/events`)
}

export async function deleteReviewPlus(
  reviewId: string,
  options?: { force?: boolean },
): Promise<{ review_plus_id: string; deleted: boolean; force?: boolean; removed_files?: string[] }> {
  const qs = new URLSearchParams()
  if (options?.force) qs.set('force', 'true')
  return apiFetch(`/${reviewId}${qs.toString() ? `?${qs.toString()}` : ''}`, {
    method: 'DELETE',
  })
}
