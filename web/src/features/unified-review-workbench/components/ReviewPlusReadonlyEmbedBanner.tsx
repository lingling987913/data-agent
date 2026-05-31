'use client'

import Link from 'next/link'
import { buildReviewPlusLegacyWorkbenchHref } from '@/features/unified-review-workbench/tabNavigation'

export function ReviewPlusReadonlyEmbedBanner({
  reviewId,
  tab,
  title,
  description,
}: {
  reviewId: string
  tab: 'materials' | 'flow'
  title: string
  description: string
}) {
  return (
    <section className="rounded-xl border border-primaryAccent/20 bg-primaryAccent/5 px-4 py-3 text-[11px]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium text-primary">{title}</p>
          <p className="mt-1 leading-relaxed text-muted">{description}</p>
          <p className="mt-1 text-[10px] text-muted">当前为只读嵌入视图，写操作需在完整 V2 工作台执行。</p>
        </div>
        <Link
          href={buildReviewPlusLegacyWorkbenchHref(reviewId, { tab })}
          className="shrink-0 rounded-lg bg-brand px-3 py-1.5 text-[10px] font-medium text-white hover:opacity-90"
        >
          在完整 V2 中继续
        </Link>
      </div>
    </section>
  )
}

export default ReviewPlusReadonlyEmbedBanner
