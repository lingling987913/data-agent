import type { MaterialClassification } from '@/features/super-agent/types'

/** 将 parse-preview 中的 classification 合并进向导顶层 state（解析完成后始终执行）。 */
export function mergePostParseClassification(
  base: MaterialClassification | null | undefined,
  fromPreview: MaterialClassification | null | undefined,
): MaterialClassification | null {
  if (!fromPreview) return base ?? null
  if (!base) return fromPreview

  const postParse = fromPreview.post_parse_route ?? base.post_parse_route

  return {
    ...base,
    ...fromPreview,
    initial_recommended_route:
      fromPreview.initial_recommended_route
      ?? base.initial_recommended_route
      ?? postParse?.initial_route
      ?? base.recommended_route,
    final_recommended_route:
      fromPreview.final_recommended_route
      ?? postParse?.effective_route
      ?? postParse?.suggested_route
      ?? base.final_recommended_route,
    route_decision_source: fromPreview.route_decision_source ?? base.route_decision_source,
    post_parse_route: postParse,
    post_parse_reason: fromPreview.post_parse_reason ?? base.post_parse_reason,
    recommended_route: fromPreview.recommended_route ?? base.recommended_route,
    parse_plan: fromPreview.parse_plan ?? base.parse_plan,
    review_plan: fromPreview.review_plan ?? base.review_plan,
    material_roles: fromPreview.material_roles?.length ? fromPreview.material_roles : base.material_roles,
    slot_completeness: fromPreview.slot_completeness ?? base.slot_completeness,
    missing_slots: fromPreview.missing_slots ?? base.missing_slots,
    review_plus_ready:
      typeof fromPreview.review_plus_ready === 'boolean'
        ? fromPreview.review_plus_ready
        : base.review_plus_ready,
    adaptive_router: fromPreview.adaptive_router ?? base.adaptive_router,
    user_overrides: fromPreview.user_overrides ?? base.user_overrides,
  }
}
