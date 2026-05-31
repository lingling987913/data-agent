import type { ReviewPlusCheckItem, ReviewPlusFinding } from '@/features/review-plus-v2/types'

export function buildReviewPlusCheckItemIndexMap(
  items: Array<Pick<ReviewPlusCheckItem, 'check_item_id'>>,
): Map<string, number> {
  const map = new Map<string, number>()
  items.forEach((item, index) => {
    const id = String(item.check_item_id || '').trim()
    if (id) map.set(id, index + 1)
  })
  return map
}

export function resolveReviewPlusCheckItemTitle(
  item: Pick<ReviewPlusCheckItem, 'title' | 'check_item_id'>,
  index?: number,
): string {
  const title = String(item.title || '').trim()
  if (title) return title
  if (typeof index === 'number' && index >= 1) return `检查项${index}`
  return '检查项'
}

export function resolveReviewPlusFindingTitle(
  finding: Pick<ReviewPlusFinding, 'title'>,
  item: Pick<ReviewPlusCheckItem, 'title' | 'check_item_id'>,
  index?: number,
): string {
  const findingTitle = String(finding.title || '').trim()
  if (findingTitle) return findingTitle
  return resolveReviewPlusCheckItemTitle(item, index)
}
