'use client'

import { Suspense } from 'react'
import ReviewPlusV2WorkbenchPage from '@/features/review-plus-v2/components/ReviewPlusV2WorkbenchPage'

export default function ReviewPlusV2Route() {
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center p-8 text-sm text-muted">加载中...</div>}>
      <ReviewPlusV2WorkbenchPage />
    </Suspense>
  )
}
