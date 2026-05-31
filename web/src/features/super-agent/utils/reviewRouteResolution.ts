import type { MaterialClassification, SuperAgentRoute } from '@/features/super-agent/types'
import { routeFromClassification } from '@/features/super-agent/utils/routeFromClassification'

/** UI card ids for the three execution routes (+ legacy specialized alias). */
export type ReviewModeCard = 'smart' | 'standard' | 'special'

export type ReviewModeCardId = ReviewModeCard | 'specialized'

/** Card selection → backend execution route (1:1 after parse). */
export function mapReviewModeCardToRoute(card: ReviewModeCard): SuperAgentRoute {
  if (card === 'standard') return 'review_plus'
  if (card === 'special') return 'gnc_review_only'
  return 'smart'
}

/** Map post-parse / classify recommendation to the card that should be highlighted. */
export function recommendedReviewModeCard(
  classification: MaterialClassification,
): ReviewModeCard | undefined {
  const route =
    classification.final_recommended_route
    || classification.post_parse_route?.effective_route
    || classification.post_parse_route?.suggested_route
    || classification.recommended_route
  if (!route) return undefined
  const normalized = routeFromClassification(route, classification)
  if (normalized === 'review_plus') return 'standard'
  if (normalized === 'gnc_review_only' || normalized === 'gnc_review') return 'special'
  return 'smart'
}

export function resolveEffectiveRoute(
  reviewModeCard: ReviewModeCard,
  requestedRoute: SuperAgentRoute,
  classification: MaterialClassification | null,
  hasParseArtifact: boolean,
): SuperAgentRoute {
  if (hasParseArtifact) {
    return mapReviewModeCardToRoute(reviewModeCard)
  }
  if (reviewModeCard === 'standard' || reviewModeCard === 'special') {
    return mapReviewModeCardToRoute(reviewModeCard)
  }
  if (requestedRoute !== 'auto') {
    return requestedRoute
  }
  if (classification?.recommended_route) {
    return routeFromClassification(classification.recommended_route, classification)
  }
  return 'auto'
}

export function resolveReviewStartRoute(
  reviewModeCard: ReviewModeCard,
  requestedRoute: SuperAgentRoute,
  _classification: MaterialClassification | null,
  hasParseArtifact: boolean,
): SuperAgentRoute {
  if (hasParseArtifact) {
    return mapReviewModeCardToRoute(reviewModeCard)
  }
  return resolveCheckpointRoute(reviewModeCard, requestedRoute)
}

/** Pre-parse checkpoint / wizard persist: card overrides dropdown except smart card. */
export function resolveCheckpointRoute(
  reviewModeCard: ReviewModeCard,
  requestedRoute: SuperAgentRoute,
): SuperAgentRoute {
  if (reviewModeCard === 'standard' || reviewModeCard === 'special') {
    return mapReviewModeCardToRoute(reviewModeCard)
  }
  return requestedRoute
}

export function routeForReviewModeCardChange(card: ReviewModeCard): SuperAgentRoute {
  return mapReviewModeCardToRoute(card)
}
