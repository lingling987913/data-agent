'use client'

import { useCallback, useEffect, useState } from 'react'
import { getUnifiedWorkbenchResource } from '@/features/unified-review-workbench/api'

export function useGncResource<T>(reviewId: string, resource: string, enabled: boolean) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    if (!enabled || !reviewId) return
    setLoading(true)
    setError('')
    try {
      const payload = await getUnifiedWorkbenchResource<T>('gnc', reviewId, resource)
      setData(payload)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [enabled, reviewId, resource])

  useEffect(() => {
    void reload()
  }, [reload])

  return { data, loading, error, reload }
}
