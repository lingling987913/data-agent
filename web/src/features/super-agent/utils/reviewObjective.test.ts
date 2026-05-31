import { describe, expect, it } from 'vitest'
import {
  DEFAULT_REVIEW_OBJECTIVE,
  DRAFT_REVIEW_OBJECTIVE,
  isPersistableReviewObjective,
  resolveReviewObjective,
} from './reviewObjective'

describe('resolveReviewObjective', () => {
  it('prefers textarea value over run and fallback', () => {
    expect(resolveReviewObjective('审查验收数据一致性', DEFAULT_REVIEW_OBJECTIVE, '分类理由')).toBe(
      '审查验收数据一致性',
    )
  })

  it('falls back to run objective when textarea empty', () => {
    expect(resolveReviewObjective('', '审查接口一致性', '分类理由')).toBe('审查接口一致性')
  })

  it('skips draft placeholder run objective', () => {
    expect(resolveReviewObjective('', DRAFT_REVIEW_OBJECTIVE, '分类理由')).toBe('分类理由')
  })

  it('uses default when nothing else is available', () => {
    expect(resolveReviewObjective('', '', '')).toBe(DEFAULT_REVIEW_OBJECTIVE)
  })
})

describe('isPersistableReviewObjective', () => {
  it('accepts custom objectives', () => {
    expect(isPersistableReviewObjective('审查验收数据一致性')).toBe(true)
  })

  it('rejects default and draft placeholders', () => {
    expect(isPersistableReviewObjective(DEFAULT_REVIEW_OBJECTIVE)).toBe(false)
    expect(isPersistableReviewObjective(DRAFT_REVIEW_OBJECTIVE)).toBe(false)
    expect(isPersistableReviewObjective('')).toBe(false)
  })
})
