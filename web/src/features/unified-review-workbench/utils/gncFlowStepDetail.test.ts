import { describe, expect, it } from 'vitest'
import {
  buildGncFlowStepDetail,
  canOpenRelatedTab,
  resolveGncFlowStepRelatedTab,
} from '@/features/unified-review-workbench/utils/gncFlowStepDetail'

describe('gncFlowStepDetail', () => {
  it('canOpenRelatedTab respects visible_tabs and excludes overview/flow', () => {
    const visible = ['overview', 'flow', 'decision', 'rid']
    expect(canOpenRelatedTab('decision', visible)).toBe(true)
    expect(canOpenRelatedTab('rid', visible)).toBe(true)
    expect(canOpenRelatedTab('committee', visible)).toBe(false)
    expect(canOpenRelatedTab('overview', visible)).toBe(false)
    expect(canOpenRelatedTab('flow', visible)).toBe(false)
  })

  it('resolveGncFlowStepRelatedTab falls back to overview', () => {
    expect(resolveGncFlowStepRelatedTab({ step_key: 'x', status: 'pending' })).toBe('overview')
    expect(resolveGncFlowStepRelatedTab({
      step_key: 'committee_review',
      status: 'completed',
      related_tab: 'committee',
    })).toBe('committee')
  })

  it('buildGncFlowStepDetail maps status, duration and metrics', () => {
    const detail = buildGncFlowStepDetail({
      step_key: 'chief_adjudication',
      label: '总师审定',
      status: 'completed',
      related_tab: 'decision',
      duration_ms: 1500,
      subtitle: '有条件通过',
      metrics: { finding_count: 3 },
      is_current: false,
    }, 7)
    expect(detail.stepKey).toBe('chief_adjudication')
    expect(detail.statusLabel).toBe('已完成')
    expect(detail.durationLabel).toBe('1.5 s')
    expect(detail.relatedTab).toBe('decision')
    expect(detail.summary).toBe('有条件通过')
    expect(detail.metricsLines[0]).toContain('finding_count')
    expect(detail.stepIndex).toBe(7)
  })
})
