import { Suspense } from 'react'
import ComprehensiveReviewPage from '@/features/comprehensive-review/components/ComprehensiveReviewPage'

export default function ComprehensiveReviewRoute() {
  return (
    <Suspense fallback={null}>
      <ComprehensiveReviewPage />
    </Suspense>
  )
}
