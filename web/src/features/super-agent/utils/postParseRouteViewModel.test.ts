import { describe, expect, it } from 'vitest'
import { resolvePostParseRouteViewModel } from '@/features/super-agent/utils/postParseRouteViewModel'
import type { MaterialClassification } from '@/features/super-agent/types'

function baseClassification(overrides: Partial<MaterialClassification> = {}): MaterialClassification {
  return {
    doc_type: '设计报告',
    domain: '综合',
    recommended_route: 'smart',
    reason: 'initial',
    initial_recommended_route: 'smart',
    final_recommended_route: 'gnc_review_only',
    route_decision_source: 'post_parse',
    post_parse_route: {
      source: 'post_parse',
      suggested_route: 'gnc_review_only',
      effective_route: 'gnc_review_only',
      confidence: 0.88,
      reasons: ['解析后正文出现 GNC/姿态/轨控等强信号，推荐 GNC 专项审查。'],
      changed_from_initial: true,
      initial_route: 'smart',
      user_override_active: false,
      parse_incomplete: false,
    },
    ...overrides,
  }
}

describe('resolvePostParseRouteViewModel', () => {
  it('shows final review mode after parse', () => {
    const model = resolvePostParseRouteViewModel(baseClassification())
    expect(model.visible).toBe(true)
    expect(model.finalRouteLabel).toBe('GNC 专项')
    expect(model.initialRouteLabel).toBe('通用审查')
    expect(model.changed).toBe(true)
    expect(model.confidencePercent).toBe(88)
  })

  it('shows user override warning when effective route differs from suggestion', () => {
    const model = resolvePostParseRouteViewModel(
      baseClassification({
        post_parse_route: {
          source: 'post_parse',
          suggested_route: 'gnc_review_only',
          effective_route: 'smart',
          confidence: 0.88,
          reasons: ['解析后正文出现 GNC 信号'],
          changed_from_initial: true,
          initial_route: 'smart',
          user_override_active: true,
          parse_incomplete: false,
        },
      }),
      'smart',
    )
    expect(model.showUserOverrideWarning).toBe(true)
    expect(model.userOverrideMessage).toContain('已采用人工指定模式')
  })

  it('returns hidden model when post-parse route is unavailable', () => {
    const model = resolvePostParseRouteViewModel({
      doc_type: '设计报告',
      domain: '综合',
      recommended_route: 'smart',
      reason: 'initial',
    })
    expect(model.visible).toBe(false)
  })

  it('shows model after parse when parseComplete is set', () => {
    const model = resolvePostParseRouteViewModel(
      {
        doc_type: '设计报告',
        domain: '综合',
        recommended_route: 'gnc_review_only',
        reason: 'parsed',
        post_parse_route: {
          suggested_route: 'gnc_review_only',
          effective_route: 'gnc_review_only',
          initial_route: 'smart',
          changed_from_initial: true,
        },
      },
      'auto',
      { parseComplete: true },
    )
    expect(model.visible).toBe(true)
    expect(model.finalRouteLabel).toBe('GNC 专项')
  })
})
