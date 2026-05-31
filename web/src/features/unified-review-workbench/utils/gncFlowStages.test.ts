import { describe, expect, it } from 'vitest'
import {
  aggregateGncFlowStages,
  assertGncStageCoverage,
  computeGncFlowStageStatus,
  GNC_FLOW_STAGE_DEFS,
  resolveConditionalStepNote,
  resolveGncFlowCurrentStageLabel,
  resolveStageConditionalNote,
} from '@/features/unified-review-workbench/utils/gncFlowStages'
import { canOpenRelatedTab } from '@/features/unified-review-workbench/utils/gncFlowStepDetail'
import type { GncFlowStepProjection } from '@/features/unified-review-workbench/constants/gncWorkflowSteps'

function mockStep(
  stepKey: string,
  status: string,
  overrides: Partial<GncFlowStepProjection> = {},
): GncFlowStepProjection {
  return {
    step_key: stepKey,
    status,
    ...overrides,
  }
}

function mockTenSteps(
  overrides: Partial<Record<string, Partial<GncFlowStepProjection>>> = {},
): GncFlowStepProjection[] {
  return [
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
  ].map((stepKey) => mockStep(stepKey, 'pending', overrides[stepKey]))
}

describe('gncFlowStages', () => {
  it('maps ten backend steps into six user-facing stages', () => {
    expect(GNC_FLOW_STAGE_DEFS).toHaveLength(6)
    expect(assertGncStageCoverage).not.toThrow()

    const stages = aggregateGncFlowStages(mockTenSteps())
    expect(stages).toHaveLength(6)
    expect(stages.map((stage) => stage.label)).toEqual([
      '材料接收与任务建立',
      '文档解析与证据准备',
      '专家组审查（AD/AC/规则）',
      '问题合稿与 RID 台账',
      '总师裁定与仲裁',
      '报告归档 / 闭环',
    ])
    expect(stages.flatMap((stage) => stage.stepKeys)).toHaveLength(10)
    expect(stages[0].stepKeys).toEqual(['review_intake'])
    expect(stages[1].stepKeys).toEqual([
      'document_structuring',
      'quality_screening',
      'evidence_pool_building',
      'knowledge_preparation',
    ])
  })

  it('computes stage status from underlying steps', () => {
    const intakeGateDef = GNC_FLOW_STAGE_DEFS[0]
    const pendingViews = intakeGateDef.stepKeys.map((stepKey, index) => ({
      step: mockStep(stepKey, 'pending'),
      stepIndex: index,
    }))
    expect(computeGncFlowStageStatus(pendingViews, intakeGateDef)).toBe('pending')

    const runningViews = [
      { step: mockStep('review_intake', 'running', { is_current: true }), stepIndex: 0 },
    ]
    expect(computeGncFlowStageStatus(runningViews, intakeGateDef)).toBe('running')

    const failedViews = [
      { step: mockStep('review_intake', 'failed', { error: '材料接收失败' }), stepIndex: 0 },
    ]
    expect(computeGncFlowStageStatus(failedViews, intakeGateDef)).toBe('failed')

    const completedViews = intakeGateDef.stepKeys.map((stepKey, index) => ({
      step: mockStep(stepKey, 'completed', { completed: true }),
      stepIndex: index,
    }))
    expect(computeGncFlowStageStatus(completedViews, intakeGateDef)).toBe('completed')

    const docEvidenceDef = GNC_FLOW_STAGE_DEFS[1]
    const screeningRunningViews = [
      { step: mockStep('document_structuring', 'completed', { completed: true }), stepIndex: 1 },
      { step: mockStep('quality_screening', 'running', { is_current: true }), stepIndex: 2 },
    ]
    expect(computeGncFlowStageStatus(screeningRunningViews, docEvidenceDef)).toBe('running')
  })

  it('marks human_arbitration as optional when arbitration is not required', () => {
    expect(resolveConditionalStepNote('human_arbitration', mockStep('human_arbitration', 'pending'), false))
      .toBe('无需仲裁')
    expect(resolveConditionalStepNote('human_arbitration', mockStep('human_arbitration', 'pending'), true))
      .toBe('按需触发 · 待仲裁')
    expect(resolveConditionalStepNote('human_arbitration', mockStep('human_arbitration', 'running', { is_current: true }), true))
      .toBe('仲裁进行中')

    const chiefStageDef = GNC_FLOW_STAGE_DEFS[4]
    const stageSteps = [
      {
        step: mockStep('chief_adjudication', 'completed', { completed: true }),
        stepIndex: 7,
      },
      {
        step: mockStep('human_arbitration', 'pending'),
        stepIndex: 8,
        conditionalNote: '无需仲裁',
      },
    ]
    expect(resolveStageConditionalNote(chiefStageDef, stageSteps, false)).toBe('无需仲裁')
    expect(computeGncFlowStageStatus(stageSteps, chiefStageDef, false)).toBe('completed')
  })

  it('marks document_evidence_prep as current when document_structuring is current', () => {
    const steps = mockTenSteps({
      review_intake: { status: 'completed', completed: true },
      document_structuring: { status: 'running', is_current: true },
      quality_screening: { status: 'pending' },
    })
    const stages = aggregateGncFlowStages(steps)

    expect(stages[0].isCurrent).toBe(false)
    expect(stages[1].isCurrent).toBe(true)
    expect(stages.filter((stage) => stage.isCurrent)).toHaveLength(1)
    expect(resolveGncFlowCurrentStageLabel(stages)).toBe('文档解析与证据准备')
  })

  it('marks document_evidence_prep as current when quality_screening is current', () => {
    const steps = mockTenSteps({
      review_intake: { status: 'completed', completed: true },
      document_structuring: { status: 'completed', completed: true },
      quality_screening: { status: 'running', is_current: true },
    })
    const stages = aggregateGncFlowStages(steps)

    expect(stages[0].isCurrent).toBe(false)
    expect(stages[1].isCurrent).toBe(true)
    expect(stages.filter((stage) => stage.isCurrent)).toHaveLength(1)
    expect(resolveGncFlowCurrentStageLabel(stages)).toBe('文档解析与证据准备')
  })

  it('does not mark material_intake_gate current when only later steps have pending status', () => {
    const steps = mockTenSteps({
      review_intake: { status: 'completed', completed: true },
      document_structuring: { status: 'running', is_current: true },
      quality_screening: { status: 'pending' },
    })
    const stages = aggregateGncFlowStages(steps)

    expect(stages[0].status).toBe('completed')
    expect(stages[0].isCurrent).toBe(false)
  })

  it('completes chief stage when arbitration is not required and human_arbitration is pending', () => {
    const steps = mockTenSteps({
      chief_adjudication: { status: 'completed', completed: true },
      human_arbitration: { status: 'pending' },
    })
    const stages = aggregateGncFlowStages(steps, { requiresArbitration: false })
    const chiefStage = stages[4]

    expect(chiefStage.status).toBe('completed')
    expect(chiefStage.conditionalNote).toBe('无需仲裁')
    expect(chiefStage.isCurrent).toBe(false)
  })

  it('keeps chief stage running when arbitration is required and human_arbitration is pending', () => {
    const steps = mockTenSteps({
      chief_adjudication: { status: 'completed', completed: true },
      human_arbitration: { status: 'pending' },
    })
    const stages = aggregateGncFlowStages(steps, { requiresArbitration: true })
    const chiefStage = stages[4]

    expect(chiefStage.status).toBe('running')
    expect(chiefStage.conditionalNote).toBe('按需触发 · 待仲裁')
  })

  it('sorts stage steps by global stepIndex ascending', () => {
    const steps = mockTenSteps()
    const docStage = aggregateGncFlowStages(steps)[1]

    expect(docStage.steps.map((view) => view.step.step_key)).toEqual([
      'document_structuring',
      'quality_screening',
      'evidence_pool_building',
      'knowledge_preparation',
    ])
    expect(docStage.steps.map((view) => view.stepIndex)).toEqual([1, 2, 3, 4])
  })

  it('aggregates duration, error, and current stage label', () => {
    const steps = mockTenSteps({
      review_intake: { status: 'completed', completed: true, duration_ms: 1000 },
      document_structuring: { status: 'completed', completed: true, duration_ms: 2000 },
      quality_screening: { status: 'running', is_current: true, duration_ms: 500 },
      committee_review: { status: 'failed', error: '委员会超时' },
    })
    const stages = aggregateGncFlowStages(steps, { requiresArbitration: false })

    expect(stages[0].durationMs).toBe(1000)
    expect(stages[0].isCurrent).toBe(false)
    expect(stages[1].durationMs).toBe(2500)
    expect(stages[1].isCurrent).toBe(true)
    expect(stages[2].status).toBe('failed')
    expect(stages[2].error).toBe('委员会超时')
    expect(stages[4].conditionalNote).toBe('无需仲裁')
    expect(resolveGncFlowCurrentStageLabel(stages)).toBe('文档解析与证据准备')
  })

  it('flow tab tab guard keeps blocking invisible related tabs', () => {
    const visible = ['overview', 'flow', 'decision', 'rid']
    expect(canOpenRelatedTab('decision', visible)).toBe(true)
    expect(canOpenRelatedTab('committee', visible)).toBe(false)
    expect(canOpenRelatedTab('arbitration', visible)).toBe(false)
    expect(canOpenRelatedTab('overview', visible)).toBe(false)
  })
})
