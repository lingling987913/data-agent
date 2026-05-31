'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import { getSuperAgentRun } from '@/features/super-agent/api'
import UnifiedReviewWorkbenchShell from '@/features/unified-review-workbench/components/UnifiedReviewWorkbenchShell'
import { parseReviewTypeParam } from '@/features/unified-review-workbench/phaseResolver'
import type { SuperAgentRun } from '@/features/super-agent/types'

function SuperAgentWorkbenchResolver({ runId }: { runId: string }) {
  const [run, setRun] = useState<SuperAgentRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    getSuperAgentRun(runId)
      .then((payload) => {
        if (!cancelled) setRun(payload)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '加载 Super Agent Run 失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [runId])

  const resolved = useMemo(() => {
    if (!run) return null
    return { reviewType: 'super_agent' as const, reviewId: run.run_id }
  }, [run])

  if (loading) {
    return <div className="flex min-h-[320px] items-center justify-center text-[12px] text-muted">加载 Super Agent 统一工作台…</div>
  }

  if (error || !resolved) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16 text-center">
        <h1 className="text-base font-semibold text-primary">统一审查工作台</h1>
        <p className="mt-2 text-[12px] leading-relaxed text-destructive">
          {error || '该 Super Agent Run 尚未产出可打开的审查工作台。'}
        </p>
        <Link href="/super-agent" className="mt-6 inline-block text-[11px] text-primaryAccent hover:underline">
          返回 Super Agent
        </Link>
      </div>
    )
  }

  return (
    <UnifiedReviewWorkbenchShell
      reviewType={resolved.reviewType}
      reviewId={resolved.reviewId}
    />
  )
}

export default function UnifiedReviewWorkbenchPage() {
  const searchParams = useSearchParams()
  const reviewType = parseReviewTypeParam(searchParams.get('reviewType'))
  const reviewId = (searchParams.get('reviewId') || '').trim()
  const runId = (searchParams.get('runId') || '').trim()

  if (runId && (!reviewType || !reviewId)) {
    return <SuperAgentWorkbenchResolver runId={runId} />
  }

  if (!reviewType || !reviewId) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16 text-center">
        <h1 className="text-base font-semibold text-primary">统一审查工作台</h1>
        <p className="mt-2 text-[12px] leading-relaxed text-muted">
          请通过 URL 参数打开：
          <code className="mt-2 block rounded bg-background px-2 py-1 text-[11px]">
            /review/workbench?reviewType=gnc|review_plus|super_agent&amp;reviewId=...
          </code>
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3 text-[11px]">
          <Link href="/super-agent" className="text-primaryAccent hover:underline">Super Agent</Link>
          <Link href="/review-plus-v2" className="text-primaryAccent hover:underline">Review-Plus V2</Link>
        </div>
      </div>
    )
  }

  return (
    <UnifiedReviewWorkbenchShell
      reviewType={reviewType}
      reviewId={reviewId}
    />
  )
}
