'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import ReviewPlusV2WorkbenchHome from '@/features/review-plus-v2/components/ReviewPlusV2WorkbenchHome'
import ReviewPlusV2WorkbenchDetail from '@/features/review-plus-v2/components/ReviewPlusV2WorkbenchDetail'
import { buildUnifiedReviewWorkbenchHref } from '@/features/unified-review-workbench/tabNavigation'

export default function ReviewPlusV2WorkbenchPage() {
  const searchParams = useSearchParams()
  const reviewId = searchParams.get('reviewId') || ''
  const initialTab = searchParams.get('tab') || ''
  const initialAction = searchParams.get('action') || ''

  if (!reviewId) {
    return <ReviewPlusV2WorkbenchHome />
  }

  const unifiedHref = buildUnifiedReviewWorkbenchHref('review_plus', reviewId, { tab: initialTab || undefined })

  return (
    <>
      <div className="border-b border-border/10 bg-background/80 px-4 py-1.5 text-center text-[10px] text-muted">
        也可在
        {' '}
        <Link href={unifiedHref} className="text-primaryAccent hover:underline">
          统一审查工作台
        </Link>
        {' '}
        打开本任务（与 V2 数据同源）。
      </div>
      <ReviewPlusV2WorkbenchDetail
        reviewId={reviewId}
        initialTab={initialTab}
        initialAction={initialAction}
      />
    </>
  )
}
