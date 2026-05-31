'use client'

import { Suspense } from 'react'
import UnifiedReviewWorkbenchPage from '@/features/unified-review-workbench/components/UnifiedReviewWorkbenchPage'

export default function UnifiedReviewWorkbenchRoute() {
  return (
    <Suspense
      fallback={(
        <div className="flex h-full min-h-[320px] items-center justify-center p-8 text-sm text-muted">
          加载统一审查工作台…
        </div>
      )}
    >
      <UnifiedReviewWorkbenchPage />
    </Suspense>
  )
}
