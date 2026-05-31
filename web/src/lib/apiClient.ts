const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || ''

export function buildAuthHeaders(includeJsonContentType = true): Record<string, string> {
  const token = process.env.NEXT_PUBLIC_API_TOKEN || 'dev-token-change-me'
  return {
    ...(includeJsonContentType ? { 'Content-Type': 'application/json' } : {}),
    Authorization: `Bearer ${token}`,
    'X-API-Key': token,
  }
}

export async function fetchApi(path: string, init?: RequestInit): Promise<Response> {
  const url = `${API_BASE}${path}`
  return fetch(url, {
    ...init,
    headers: {
      ...buildAuthHeaders(false),
      ...(init?.headers as Record<string, string> | undefined),
    },
  })
}

export async function fetchApiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchApi(path, {
    ...init,
    headers: {
      ...buildAuthHeaders(true),
      ...(init?.headers as Record<string, string> | undefined),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API error ${res.status}: ${text}`)
  }
  const json = await res.json()
  return json.data as T
}

/** @deprecated use buildAuthHeaders */
export const buildAeroAuthHeaders = buildAuthHeaders
/** @deprecated use fetchApi */
export const fetchAeroDomainApi = fetchApi
/** @deprecated use fetchApiJson */
export const fetchAeroDomainJson = fetchApiJson
