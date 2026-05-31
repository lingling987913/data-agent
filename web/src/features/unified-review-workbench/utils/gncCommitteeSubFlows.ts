import { resolveVerdictLabel } from '@/features/unified-review-workbench/utils/zhWorkbenchText'

export type GncSubflowStageStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'blocked'
  | 'not_checked'
  | 'failed'
  | 'skipped'

export interface GncSubflowStageProjection {
  stageKey: string
  stageLabel: string
  unitKey: string
  status: GncSubflowStageStatus
  skipReason?: string
  findingCount: number
  ruleJudgmentCount: number
  blockingFlags: string[]
  summary?: string
}

export interface GncSubflowLaneProjection {
  groupKey: 'ad_group' | 'ac_group'
  groupLabel: string
  enabled: boolean
  skipReason?: string
  verdict?: string
  summary?: string
  blockingFlags: string[]
  stages: GncSubflowStageProjection[]
}

export interface GncCommitteeSubflowInput {
  review_scope?: string
  subflow_lanes?: Array<Record<string, unknown>>
  ad_group_result?: Record<string, unknown>
  ac_group_result?: Record<string, unknown>
}

export const AD_SUBFLOW_STAGE_DEFS = [
  { stageKey: 'req_err', unitKey: 'ad_requirement_error_unit', stageLabel: '需求误差' },
  { stageKey: 'timing', unitKey: 'ad_sampling_timing_unit', stageLabel: '时序/采样' },
  { stageKey: 'install', unitKey: 'ad_mounting_pointing_unit', stageLabel: '安装/指向' },
  { stageKey: 'algorithm', unitKey: 'ad_determination_algorithm_unit', stageLabel: '算法' },
  { stageKey: 'simulation', unitKey: 'ad_simulation_analysis_unit', stageLabel: '仿真' },
  { stageKey: 'consistency', unitKey: 'ad_cross_consistency_unit', stageLabel: '一致性' },
  { stageKey: 'report', unitKey: 'ad_report_completeness_unit', stageLabel: '报告完整性' },
] as const

export const AC_SUBFLOW_STAGE_DEFS = [
  { stageKey: 'req_err', unitKey: 'ac_requirement_error_unit', stageLabel: '需求误差' },
  { stageKey: 'thruster_layout', unitKey: 'ac_thruster_layout_unit', stageLabel: '推力器布局' },
  { stageKey: 'other_actuator_layout', unitKey: 'ac_actuator_layout_unit', stageLabel: '执行机构布局' },
  { stageKey: 'control_law', unitKey: 'ac_control_law_unit', stageLabel: '控制律设计' },
  { stageKey: 'control_params', unitKey: 'ac_control_param_unit', stageLabel: '控制参数' },
  { stageKey: 'maneuver_law', unitKey: 'ac_maneuver_control_unit', stageLabel: '机动控制' },
  { stageKey: 'unloading_law', unitKey: 'ac_momentum_unload_unit', stageLabel: '动量卸载' },
  { stageKey: 'simulation', unitKey: 'ac_control_simulation_unit', stageLabel: '仿真' },
  { stageKey: 'consistency', unitKey: 'ac_cross_consistency_unit', stageLabel: '一致性' },
  { stageKey: 'report', unitKey: 'ac_report_completeness_unit', stageLabel: '报告完整性' },
] as const

export type GncCommitteeGroupKey = 'ad_group' | 'ac_group'

/** 与 ad_review_sub_workflow.py `_AD_STAGE_PLAN` 对齐：phase 内串行，多 stage 的 phase 并行。 */
export const AD_COMMITTEE_PARALLEL_PHASES: readonly (readonly string[])[] = [
  ['req_err'],
  ['timing', 'install'],
  ['algorithm'],
  ['simulation'],
  ['consistency'],
  ['report'],
]

/** 与 ac_review_sub_workflow.py `_build_ac_stage_plan` 对齐（未启用环节由调用方过滤）。 */
export const AC_COMMITTEE_PARALLEL_PHASES: readonly (readonly string[])[] = [
  ['req_err'],
  ['thruster_layout', 'other_actuator_layout'],
  ['control_law'],
  ['control_params'],
  ['maneuver_law', 'unloading_law'],
  ['simulation'],
  ['consistency'],
  ['report'],
]

export function getCommitteePhasePlan(groupKey: GncCommitteeGroupKey): readonly (readonly string[])[] {
  return groupKey === 'ad_group' ? AD_COMMITTEE_PARALLEL_PHASES : AC_COMMITTEE_PARALLEL_PHASES
}

/** 按后端 phase 计划分组，仅保留当前启用的 stage；空 phase 跳过。 */
export function getActiveStagesByPhase(
  groupKey: GncCommitteeGroupKey,
  activeStageKeys: readonly string[],
): string[][] {
  const activeSet = new Set(activeStageKeys)
  return getCommitteePhasePlan(groupKey)
    .map((phase) => phase.filter((stageKey) => activeSet.has(stageKey)))
    .filter((phase) => phase.length > 0)
}

const SCOPE_SKIP_REASON = '本轮未启用（由 review_scope 跳过）'
const TEMPLATE_SKIP_REASON = '模板/证据未启用'

export function resolveReviewScopeEnabledGroups(reviewScope?: string): {
  adEnabled: boolean
  acEnabled: boolean
} {
  const scope = String(reviewScope || 'ad_ac').trim() || 'ad_ac'
  return {
    adEnabled: scope === 'ad_only' || scope === 'ad_ac',
    acEnabled: scope === 'ac_only' || scope === 'ad_ac',
  }
}

function normalizeSubflowVerdict(raw?: string): string | undefined {
  const text = String(raw || '').trim()
  if (!text) return undefined
  return resolveVerdictLabel(text, text)
}

export function normalizeSubflowStageStatus(raw?: string): GncSubflowStageStatus {
  const status = String(raw || 'pending').trim().toLowerCase()
  if (status === 'completed' || status === 'ok') return 'completed'
  if (status === 'running') return 'running'
  if (status === 'blocked') return 'blocked'
  if (status === 'failed') return 'failed'
  if (status === 'skipped') return 'skipped'
  if (status === 'placeholder' || status === 'not_checked') return 'not_checked'
  return 'pending'
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

function extractStageMetrics(
  stageKey: string,
  groupResult: Record<string, unknown>,
): {
  status: GncSubflowStageStatus
  skipReason?: string
  findingCount: number
  ruleJudgmentCount: number
  blockingFlags: string[]
  summary?: string
} {
  const stageResults = asRecord(groupResult.stage_results)
  const conclusion = asRecord(groupResult.conclusion)
  const stageRuleJudgments = asRecord(conclusion.stage_rule_judgments)
  const stagePayload = asRecord(stageResults[stageKey])

  const unitResults = Array.isArray(groupResult.unit_results) ? groupResult.unit_results : []
  const unitPayload = unitResults
    .map((item) => asRecord(item))
    .find((item) => String(item.stage_key || item.stage || '') === stageKey)

  if (Object.keys(stagePayload).length) {
    return {
      status: normalizeSubflowStageStatus(String(stagePayload.status || 'pending')),
      findingCount: Number(stagePayload.finding_count || 0),
      ruleJudgmentCount: Number(stagePayload.rule_judgment_count || 0),
      blockingFlags: asStringList(stagePayload.blocking_flags),
      summary: String(stagePayload.summary || '').trim() || undefined,
    }
  }

  if (unitPayload) {
    const findings = Array.isArray(unitPayload.findings) ? unitPayload.findings : []
    const ruleResults = Array.isArray(unitPayload.rule_results) ? unitPayload.rule_results : []
    return {
      status: normalizeSubflowStageStatus(String(unitPayload.status || 'pending')),
      findingCount: findings.length,
      ruleJudgmentCount: ruleResults.length,
      blockingFlags: asStringList(unitPayload.blocking_flags),
      summary: String(unitPayload.summary || '').trim() || undefined,
    }
  }

  const judgments = stageRuleJudgments[stageKey]
  return {
    status: 'pending',
    findingCount: 0,
    ruleJudgmentCount: Array.isArray(judgments) ? judgments.length : 0,
    blockingFlags: [],
  }
}

function buildLaneFromGroupResult(
  groupKey: 'ad_group' | 'ac_group',
  groupLabel: string,
  stageDefs: readonly { stageKey: string; unitKey: string; stageLabel: string }[],
  groupResult: Record<string, unknown> | undefined,
  enabled: boolean,
): GncSubflowLaneProjection {
  const payload = groupResult || {}
  const skippedStages = new Set(asStringList(payload.skipped_stages))

  const stages: GncSubflowStageProjection[] = stageDefs.map((def) => {
    if (!enabled) {
      return {
        stageKey: def.stageKey,
        stageLabel: def.stageLabel,
        unitKey: def.unitKey,
        status: 'skipped',
        skipReason: SCOPE_SKIP_REASON,
        findingCount: 0,
        ruleJudgmentCount: 0,
        blockingFlags: [],
      }
    }
    if (skippedStages.has(def.stageKey)) {
      return {
        stageKey: def.stageKey,
        stageLabel: def.stageLabel,
        unitKey: def.unitKey,
        status: 'skipped',
        skipReason: TEMPLATE_SKIP_REASON,
        findingCount: 0,
        ruleJudgmentCount: 0,
        blockingFlags: [],
      }
    }

    const metrics = extractStageMetrics(def.stageKey, payload)
    return {
      stageKey: def.stageKey,
      stageLabel: def.stageLabel,
      unitKey: def.unitKey,
      ...metrics,
    }
  })

  const backendStages = Array.isArray(payload.stages)
    ? payload.stages.map((item) => asRecord(item))
    : []
  if (backendStages.length) {
    for (const stage of stages) {
      const backend = backendStages.find((item) => String(item.stage_key || '') === stage.stageKey)
      if (!backend) continue
      stage.status = normalizeSubflowStageStatus(String(backend.status || stage.status))
      stage.skipReason = String(backend.skip_reason || stage.skipReason || '').trim() || undefined
      stage.findingCount = Number(backend.finding_count ?? stage.findingCount)
      stage.ruleJudgmentCount = Number(backend.rule_judgment_count ?? stage.ruleJudgmentCount)
      stage.blockingFlags = asStringList(backend.blocking_flags).length
        ? asStringList(backend.blocking_flags)
        : stage.blockingFlags
      stage.summary = String(backend.summary || stage.summary || '').trim() || undefined
    }
  }

  const conclusion = asRecord(payload.conclusion)
  return {
    groupKey,
    groupLabel: String(payload.group_label || groupLabel),
    enabled,
    skipReason: enabled ? undefined : SCOPE_SKIP_REASON,
    verdict: normalizeSubflowVerdict(String(payload.verdict || conclusion.verdict || '')),
    summary: String(payload.summary || conclusion.summary || '').trim() || undefined,
    blockingFlags: asStringList(payload.blocking_flags),
    stages,
  }
}

function laneFromBackendPayload(payload: Record<string, unknown>): GncSubflowLaneProjection | null {
  const groupKey = String(payload.group_key || '')
  if (groupKey !== 'ad_group' && groupKey !== 'ac_group') return null
  const stages = Array.isArray(payload.stages)
    ? payload.stages.map((item) => {
        const stage = asRecord(item)
        return {
          stageKey: String(stage.stage_key || ''),
          stageLabel: String(stage.stage_label || stage.stage_key || ''),
          unitKey: String(stage.unit_key || ''),
          status: normalizeSubflowStageStatus(String(stage.status || 'pending')),
          skipReason: String(stage.skip_reason || '').trim() || undefined,
          findingCount: Number(stage.finding_count || 0),
          ruleJudgmentCount: Number(stage.rule_judgment_count || 0),
          blockingFlags: asStringList(stage.blocking_flags),
          summary: String(stage.summary || '').trim() || undefined,
        } satisfies GncSubflowStageProjection
      }).filter((stage) => stage.stageKey)
    : []

  return {
    groupKey,
    groupLabel: String(payload.group_label || (groupKey === 'ad_group' ? 'AD 姿态确定' : 'AC 姿态控制')),
    enabled: Boolean(payload.enabled),
    skipReason: String(payload.skip_reason || '').trim() || undefined,
    verdict: normalizeSubflowVerdict(String(payload.verdict || '')),
    summary: String(payload.summary || '').trim() || undefined,
    blockingFlags: asStringList(payload.blocking_flags),
    stages,
  }
}

function hasSubstantiveCommitteeData(committee: GncCommitteeSubflowInput): boolean {
  if (String(committee.review_scope || '').trim()) return true
  if (Array.isArray(committee.subflow_lanes) && committee.subflow_lanes.length > 0) return true
  const adGroup = committee.ad_group_result
  if (adGroup && typeof adGroup === 'object' && Object.keys(adGroup).length > 0) return true
  const acGroup = committee.ac_group_result
  if (acGroup && typeof acGroup === 'object' && Object.keys(acGroup).length > 0) return true
  return false
}

export function buildGncCommitteeSubflowLanes(
  committee: GncCommitteeSubflowInput | null | undefined,
): GncSubflowLaneProjection[] {
  if (!committee) {
    return []
  }

  const backendLanes = Array.isArray(committee.subflow_lanes)
    ? committee.subflow_lanes.map((item) => laneFromBackendPayload(asRecord(item))).filter(Boolean) as GncSubflowLaneProjection[]
    : []

  if (backendLanes.length === 2) {
    return backendLanes
  }

  if (!hasSubstantiveCommitteeData(committee)) {
    return []
  }

  const { adEnabled, acEnabled } = resolveReviewScopeEnabledGroups(committee.review_scope)
  return [
    buildLaneFromGroupResult(
      'ad_group',
      'AD 姿态确定',
      AD_SUBFLOW_STAGE_DEFS,
      committee.ad_group_result,
      adEnabled,
    ),
    buildLaneFromGroupResult(
      'ac_group',
      'AC 姿态控制',
      AC_SUBFLOW_STAGE_DEFS,
      committee.ac_group_result,
      acEnabled,
    ),
  ]
}

export function subflowStageStatusLabel(status: GncSubflowStageStatus): string {
  switch (status) {
    case 'completed':
      return '已完成'
    case 'running':
      return '进行中'
    case 'blocked':
      return '阻塞'
    case 'failed':
      return '失败'
    case 'not_checked':
      return '未检'
    case 'skipped':
      return '已跳过'
    default:
      return '待执行'
  }
}

export function summarizeSubflowLane(lane: GncSubflowLaneProjection): string {
  if (!lane.enabled) return lane.skipReason || SCOPE_SKIP_REASON
  const activeStages = lane.stages.filter((stage) => stage.status !== 'skipped')
  const completed = activeStages.filter((stage) => stage.status === 'completed').length
  const blocked = activeStages.filter((stage) => stage.blockingFlags.length > 0).length
  const findings = activeStages.reduce((sum, stage) => sum + stage.findingCount, 0)
  return `${completed}/${activeStages.length || lane.stages.length} 环节完成 · ${findings} 条发现 · ${blocked} 个阻塞环节`
}
