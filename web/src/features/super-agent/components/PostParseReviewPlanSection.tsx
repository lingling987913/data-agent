'use client'

import AdaptiveRouterCard from '@/features/super-agent/components/AdaptiveRouterCard'
import PostParseRouteSummary from '@/features/super-agent/components/PostParseRouteSummary'
import ReviewModeCardPicker, { type ReviewModeCardId } from '@/features/super-agent/components/ReviewModeCardPicker'
import type { MaterialClassification, SuperAgentRoute } from '@/features/super-agent/types'
import { recommendedReviewModeCard } from '@/features/super-agent/utils/reviewRouteResolution'

export default function PostParseReviewPlanSection({
  classification,
  reviewModeCard,
  requestedRoute,
  onReviewModeCardChange,
  onAdaptiveRouterOverride,
}: {
  classification: MaterialClassification
  reviewModeCard: ReviewModeCardId
  requestedRoute: SuperAgentRoute
  onReviewModeCardChange: (card: ReviewModeCardId) => void
  onAdaptiveRouterOverride?: (patch: {
    domain_id?: string
    route?: string
    requested_route: SuperAgentRoute
    classification: MaterialClassification
  }) => void
}) {
  const recommendedCard = recommendedReviewModeCard(classification)

  return (
    <section
      className="mt-6 space-y-3 border-t border-border/15 pt-6"
      data-testid="super-agent-post-parse-review-plan"
    >
      <div>
        <h3 className="text-[12px] font-semibold text-primary">审查链路判定</h3>
        <p className="mt-0.5 text-[11px] text-muted">
          基于解析内容推荐审查链路，确认或改选后开始审查。
        </p>
      </div>

      <PostParseRouteSummary classification={classification} requestedRoute={requestedRoute} />

      <ReviewModeCardPicker
        reviewModeCard={reviewModeCard}
        onChange={onReviewModeCardChange}
        recommendedCard={recommendedCard}
        title="确认审查模式"
        testId="super-agent-post-parse-review-mode-cards"
      />

      {classification.adaptive_router && onAdaptiveRouterOverride ? (
        <AdaptiveRouterCard
          classification={classification}
          requestedRoute={requestedRoute}
          onApplyOverride={onAdaptiveRouterOverride}
          testId="super-agent-post-parse-adaptive-router"
          className="mt-0 border-border/15"
        />
      ) : null}
    </section>
  )
}
