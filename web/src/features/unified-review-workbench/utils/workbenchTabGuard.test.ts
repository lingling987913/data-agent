import { describe, expect, it } from 'vitest'
import {
  buildWorkbenchTabHref,
  guardWorkbenchOpenTab,
  InvalidUrlTabHintTracker,
  INVALID_URL_TAB_SANITIZE_HINT,
  isOpenableWorkbenchTab,
  resolveInvalidUrlTabSanitizeHint,
  shouldSanitizeWorkbenchUrlTab,
} from '@/features/unified-review-workbench/utils/workbenchTabGuard'

const GNC_VISIBLE = ['overview', 'flow', 'materials', 'findings', 'rid', 'decision']

describe('workbenchTabGuard', () => {
  it('isOpenableWorkbenchTab respects review type registry', () => {
    expect(isOpenableWorkbenchTab(GNC_VISIBLE, 'gnc', 'rid')).toBe(true)
    expect(isOpenableWorkbenchTab(GNC_VISIBLE, 'gnc', 'coverage')).toBe(false)
    expect(isOpenableWorkbenchTab(['overview', 'coverage'], 'review_plus', 'coverage')).toBe(true)
  })

  it('guardWorkbenchOpenTab blocks invisible tabs', () => {
    expect(guardWorkbenchOpenTab(GNC_VISIBLE, 'gnc', 'rid')).toEqual({ allowed: true })
    expect(guardWorkbenchOpenTab(GNC_VISIBLE, 'gnc', 'coverage')).toEqual({
      allowed: false,
      reason: 'not_visible',
    })
    expect(guardWorkbenchOpenTab(undefined, 'gnc', 'overview')).toEqual({
      allowed: false,
      reason: 'no_detail',
    })
  })

  it('shouldSanitizeWorkbenchUrlTab only replaces invalid url tabs', () => {
    expect(shouldSanitizeWorkbenchUrlTab('rid', 'rid', GNC_VISIBLE, 'gnc')).toBe(false)
    expect(shouldSanitizeWorkbenchUrlTab('not-a-tab', 'overview', GNC_VISIBLE, 'gnc')).toBe(true)
    expect(shouldSanitizeWorkbenchUrlTab('', 'overview', GNC_VISIBLE, 'gnc')).toBe(false)
    expect(shouldSanitizeWorkbenchUrlTab('coverage', 'overview', GNC_VISIBLE, 'gnc')).toBe(true)
  })

  it('buildWorkbenchTabHref preserves other query params', () => {
    const href = buildWorkbenchTabHref('/workbench', 'foo=bar&tab=invalid', 'overview')
    expect(href).toBe('/workbench?foo=bar&tab=overview')
  })

  it('resolveInvalidUrlTabSanitizeHint returns hint only for invalid url tabs', () => {
    expect(resolveInvalidUrlTabSanitizeHint('coverage', 'overview', GNC_VISIBLE, 'gnc')).toBe(
      INVALID_URL_TAB_SANITIZE_HINT,
    )
    expect(resolveInvalidUrlTabSanitizeHint('overview', 'overview', GNC_VISIBLE, 'gnc')).toBeNull()
    expect(resolveInvalidUrlTabSanitizeHint('', 'overview', GNC_VISIBLE, 'gnc')).toBeNull()
  })

  it('InvalidUrlTabHintTracker notifies once per invalid tab until reset', () => {
    const tracker = new InvalidUrlTabHintTracker()
    expect(tracker.shouldNotify('coverage')).toBe(true)
    expect(tracker.shouldNotify('coverage')).toBe(false)
    expect(tracker.shouldNotify('not-a-tab')).toBe(true)
    tracker.reset()
    expect(tracker.shouldNotify('coverage')).toBe(true)
  })
})
