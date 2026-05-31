import { describe, expect, it } from 'vitest'
import {
  normalizeSuperAgentTabKey,
  normalizeSuperAgentVisibleTabs,
  resolveSuperAgentTabLabel,
} from '@/features/unified-review-workbench/utils/superAgentTabAlias'

describe('superAgentTabAlias', () => {
  it('maps legacy deep-link tabs to six business tabs', () => {
    expect(normalizeSuperAgentTabKey('flow')).toBe('routes')
    expect(normalizeSuperAgentTabKey('committee')).toBe('routes')
    expect(normalizeSuperAgentTabKey('events')).toBe('routes')
    expect(normalizeSuperAgentTabKey('decision')).toBe('closure')
    expect(normalizeSuperAgentTabKey('report')).toBe('closure')
    expect(normalizeSuperAgentTabKey('evidences')).toBe('findings')
    expect(normalizeSuperAgentTabKey('check_items')).toBe('findings')
  })

  it('keeps canonical super agent tabs', () => {
    expect(normalizeSuperAgentTabKey('overview')).toBe('overview')
    expect(normalizeSuperAgentTabKey('quality')).toBe('quality')
  })

  it('orders visible tabs in business tab sequence', () => {
    expect(
      normalizeSuperAgentVisibleTabs([
        'quality',
        'closure',
        'findings',
        'routes',
        'materials',
        'overview',
      ]),
    ).toEqual(['overview', 'materials', 'routes', 'findings', 'closure', 'quality'])
  })

  it('resolves Chinese labels for business tabs', () => {
    expect(resolveSuperAgentTabLabel('check_items')).toBe('发现与证据')
    expect(resolveSuperAgentTabLabel('routes')).toBe('审查路线')
  })
})
