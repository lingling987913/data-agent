import { describe, expect, it } from 'vitest'
import {
  buildWorkbenchNavigateHref,
  readWorkbenchBucketParam,
  shouldClearBucketOnTab,
} from '@/features/unified-review-workbench/utils/workbenchFilterQuery'

describe('workbenchFilterQuery', () => {
  it('reads and writes bucket query for findings deep link', () => {
    const params = new URLSearchParams('tab=findings&bucket=manual_review')
    expect(readWorkbenchBucketParam(params)).toBe('manual_review')
    const href = buildWorkbenchNavigateHref({
      pathname: '/super-agent',
      searchParams: 'runid=abc',
      tab: 'findings',
      bucket: 'verified',
      hint: '已筛选',
    })
    expect(href).toContain('tab=findings')
    expect(href).toContain('bucket=verified')
    expect(href).toContain('hint=')
    expect(href).toContain('runid=abc')
  })

  it('clears bucket when leaving findings tab', () => {
    expect(shouldClearBucketOnTab('materials')).toBe(true)
    expect(shouldClearBucketOnTab('findings')).toBe(false)
    const href = buildWorkbenchNavigateHref({
      pathname: '/super-agent',
      searchParams: 'tab=findings&bucket=severe_error',
      tab: 'materials',
      bucket: null,
    })
    expect(href).toContain('tab=materials')
    expect(href).not.toContain('bucket=')
  })
})
