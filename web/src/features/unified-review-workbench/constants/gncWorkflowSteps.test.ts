import { describe, expect, it } from 'vitest'
import {
  formatDurationMs,
  GNC_WORKFLOW_STEP_DEFS,
  resolveGncStepLabel,
} from '@/features/unified-review-workbench/constants/gncWorkflowSteps'

describe('gncWorkflowSteps', () => {
  it('covers ten GNC workflow steps', () => {
    expect(GNC_WORKFLOW_STEP_DEFS).toHaveLength(10)
    expect(GNC_WORKFLOW_STEP_DEFS.map((step) => step.stepKey)).toEqual([
      'review_intake',
      'document_structuring',
      'quality_screening',
      'evidence_pool_building',
      'knowledge_preparation',
      'committee_review',
      'editorial_synthesis',
      'chief_adjudication',
      'human_arbitration',
      'review_closure',
    ])
  })

  it('resolves step labels and duration formatting', () => {
    expect(resolveGncStepLabel('committee_review')).toBe('委员会审查')
    expect(formatDurationMs(null)).toBe('—')
    expect(formatDurationMs(850)).toBe('850 ms')
    expect(formatDurationMs(2500)).toBe('2.5 s')
    expect(formatDurationMs(125000)).toBe('2 m 5 s')
  })
})
