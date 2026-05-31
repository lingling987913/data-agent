import { describe, expect, it } from 'vitest'
import {
  AC_COMMITTEE_PARALLEL_PHASES,
  AD_COMMITTEE_PARALLEL_PHASES,
  AD_SUBFLOW_STAGE_DEFS,
  AC_SUBFLOW_STAGE_DEFS,
  buildGncCommitteeSubflowLanes,
  getActiveStagesByPhase,
  getCommitteePhasePlan,
  normalizeSubflowStageStatus,
  resolveReviewScopeEnabledGroups,
  subflowStageStatusLabel,
  summarizeSubflowLane,
} from '@/features/unified-review-workbench/utils/gncCommitteeSubFlows'

function mockAdGroupResult(overrides: Record<string, unknown> = {}) {
  return {
    conclusion: {
      verdict: 'conditionally_approved',
      summary: 'AD 组完成 7 环节',
      stage_rule_judgments: {
        algorithm: [{ rule_id: 'AD-ALG-01', judgment: 'not_satisfied' }],
      },
    },
    stage_results: {
      req_err: { status: 'completed', finding_count: 0, rule_judgment_count: 2, blocking_flags: [] },
      algorithm: {
        status: 'blocked',
        finding_count: 1,
        rule_judgment_count: 3,
        blocking_flags: ['algorithm:not_checked_rules'],
        summary: '滤波器参数缺依据',
      },
    },
    unit_results: [
      {
        unit_key: 'ad_determination_algorithm_unit',
        stage_key: 'algorithm',
        status: 'blocked',
        blocking_flags: ['algorithm:not_checked_rules'],
        rule_results: [{ rule_id: 'AD-ALG-01' }, { rule_id: 'AD-ALG-02' }, { rule_id: 'AD-ALG-03' }],
        findings: [{ finding_id: 'F-AD-1' }],
      },
    ],
    blocking_flags: ['algorithm:not_checked_rules'],
    ...overrides,
  }
}

function mockAcGroupResult(overrides: Record<string, unknown> = {}) {
  return {
    conclusion: { verdict: 'approved', summary: 'AC 组通过' },
    stage_results: {
      control_law: { status: 'completed', finding_count: 0, rule_judgment_count: 4, blocking_flags: [] },
      control_params: { status: 'completed', finding_count: 0, rule_judgment_count: 2, blocking_flags: [] },
    },
    skipped_stages: ['thruster_layout'],
    unit_results: [],
    blocking_flags: [],
    ...overrides,
  }
}

describe('gncCommitteeSubFlows', () => {
  it('returns empty lanes when committee is null, undefined, or empty object', () => {
    expect(buildGncCommitteeSubflowLanes(null)).toEqual([])
    expect(buildGncCommitteeSubflowLanes(undefined)).toEqual([])
    expect(buildGncCommitteeSubflowLanes({})).toEqual([])
  })

  it('maps review_scope to enabled AD/AC groups', () => {
    expect(resolveReviewScopeEnabledGroups('ad_only')).toEqual({ adEnabled: true, acEnabled: false })
    expect(resolveReviewScopeEnabledGroups('ac_only')).toEqual({ adEnabled: false, acEnabled: true })
    expect(resolveReviewScopeEnabledGroups('ad_ac')).toEqual({ adEnabled: true, acEnabled: true })
  })

  it('builds AD and AC lanes with stage metrics for ad_ac scope', () => {
    const lanes = buildGncCommitteeSubflowLanes({
      review_scope: 'ad_ac',
      ad_group_result: mockAdGroupResult(),
      ac_group_result: mockAcGroupResult(),
    })

    expect(lanes).toHaveLength(2)
    expect(lanes[0].groupKey).toBe('ad_group')
    expect(lanes[0].enabled).toBe(true)
    expect(lanes[0].stages).toHaveLength(AD_SUBFLOW_STAGE_DEFS.length)

    const algorithm = lanes[0].stages.find((stage) => stage.stageKey === 'algorithm')
    expect(algorithm?.status).toBe('blocked')
    expect(algorithm?.findingCount).toBe(1)
    expect(algorithm?.ruleJudgmentCount).toBe(3)
    expect(algorithm?.blockingFlags).toContain('algorithm:not_checked_rules')

    const acSkipped = lanes[1].stages.find((stage) => stage.stageKey === 'thruster_layout')
    expect(acSkipped?.status).toBe('skipped')
    expect(acSkipped?.skipReason).toContain('未启用')
  })

  it('marks disabled group lanes as skipped for ad_only and ac_only', () => {
    const adOnly = buildGncCommitteeSubflowLanes({
      review_scope: 'ad_only',
      ad_group_result: mockAdGroupResult(),
      ac_group_result: mockAcGroupResult(),
    })
    expect(adOnly[0].enabled).toBe(true)
    expect(adOnly[1].enabled).toBe(false)
    expect(adOnly[1].stages.every((stage) => stage.status === 'skipped')).toBe(true)
    expect(adOnly[1].skipReason).toContain('review_scope')

    const acOnly = buildGncCommitteeSubflowLanes({
      review_scope: 'ac_only',
      ad_group_result: mockAdGroupResult(),
      ac_group_result: mockAcGroupResult(),
    })
    expect(acOnly[0].enabled).toBe(false)
    expect(acOnly[1].enabled).toBe(true)
    expect(acOnly[0].stages.every((stage) => stage.status === 'skipped')).toBe(true)
  })

  it('normalizes stage statuses and labels', () => {
    expect(normalizeSubflowStageStatus('completed')).toBe('completed')
    expect(normalizeSubflowStageStatus('blocked')).toBe('blocked')
    expect(normalizeSubflowStageStatus('placeholder')).toBe('not_checked')
    expect(subflowStageStatusLabel('not_checked')).toBe('未检')
  })

  it('summarizes lane progress', () => {
    const lanes = buildGncCommitteeSubflowLanes({
      review_scope: 'ad_ac',
      ad_group_result: mockAdGroupResult(),
      ac_group_result: mockAcGroupResult(),
    })
    const summary = summarizeSubflowLane(lanes[0])
    expect(summary).toContain('环节完成')
    expect(summary).toContain('发现')
  })

  it('prefers backend subflow_lanes projection when present', () => {
    const lanes = buildGncCommitteeSubflowLanes({
      review_scope: 'ad_ac',
      subflow_lanes: [
        {
          group_key: 'ad_group',
          group_label: 'AD 姿态确定',
          enabled: true,
          blocking_flags: [],
          stages: [
            {
              stage_key: 'algorithm',
              stage_label: '算法',
              unit_key: 'ad_determination_algorithm_unit',
              status: 'completed',
              finding_count: 0,
              rule_judgment_count: 1,
              blocking_flags: [],
            },
          ],
        },
        {
          group_key: 'ac_group',
          group_label: 'AC 姿态控制',
          enabled: true,
          blocking_flags: [],
          stages: [{ stage_key: 'control_law', stage_label: '控制律设计', unit_key: 'ac_control_law_unit', status: 'pending', finding_count: 0, rule_judgment_count: 0, blocking_flags: [] }],
        },
      ],
    })
    expect(lanes[0].stages).toHaveLength(1)
    expect(lanes[0].stages[0].stageKey).toBe('algorithm')
    expect(lanes[1].stages[0].stageKey).toBe('control_law')
  })

  it('covers full AC stage catalog', () => {
    const lanes = buildGncCommitteeSubflowLanes({ review_scope: 'ac_only', ac_group_result: mockAcGroupResult() })
    expect(lanes[1].stages).toHaveLength(AC_SUBFLOW_STAGE_DEFS.length)
  })

  it('keeps committee phase plans aligned with stage defs', () => {
    const adStageKeys = AD_SUBFLOW_STAGE_DEFS.map((def) => def.stageKey)
    const acStageKeys = AC_SUBFLOW_STAGE_DEFS.map((def) => def.stageKey)

    expect(AD_COMMITTEE_PARALLEL_PHASES.flat()).toEqual(adStageKeys)
    expect(AC_COMMITTEE_PARALLEL_PHASES.flat()).toEqual(acStageKeys)
    expect(getCommitteePhasePlan('ad_group')).toBe(AD_COMMITTEE_PARALLEL_PHASES)
    expect(getCommitteePhasePlan('ac_group')).toBe(AC_COMMITTEE_PARALLEL_PHASES)
  })

  it('groups active stages by backend phase plan', () => {
    expect(getActiveStagesByPhase('ad_group', adStageKeysFromDefs())).toEqual([
      ['req_err'],
      ['timing', 'install'],
      ['algorithm'],
      ['simulation'],
      ['consistency'],
      ['report'],
    ])

    expect(getActiveStagesByPhase('ac_group', [
      'req_err',
      'control_law',
      'maneuver_law',
      'unloading_law',
      'report',
    ])).toEqual([
      ['req_err'],
      ['control_law'],
      ['maneuver_law', 'unloading_law'],
      ['report'],
    ])
  })
})

function adStageKeysFromDefs() {
  return AD_SUBFLOW_STAGE_DEFS.map((def) => def.stageKey)
}
