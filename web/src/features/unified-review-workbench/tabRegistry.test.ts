import { describe, expect, it } from 'vitest'
import { filterTabsForReviewType } from '@/features/unified-review-workbench/tabRegistry'

describe('filterTabsForReviewType', () => {
  it('orders super_agent tabs with overview first in business sequence', () => {
    expect(
      filterTabsForReviewType(
        ['quality', 'closure', 'findings', 'routes', 'materials', 'overview'],
        'super_agent',
      ),
    ).toEqual(['overview', 'materials', 'routes', 'findings', 'closure', 'quality'])
  })

  it('maps legacy super_agent tab keys and dedupes while ordering', () => {
    expect(
      filterTabsForReviewType(
        ['check_items', 'flow', 'overview', 'decision', 'events', 'materials'],
        'super_agent',
      ),
    ).toEqual(['overview', 'materials', 'routes', 'findings', 'closure'])
  })

  it('preserves gnc visible tab order from the API', () => {
    const gncTabs = ['overview', 'flow', 'materials', 'findings', 'rid', 'decision']
    expect(filterTabsForReviewType(gncTabs, 'gnc')).toEqual(gncTabs)
  })
})
