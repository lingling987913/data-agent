import type { WorkflowGraph, WorkflowGraphNode, WorkflowStepStatus } from '@aqua/workflow-core'
import { STEP_STATUS_LABELS } from '@aqua/workflow-core'
import { REVIEW_PLUS_PIPELINE_STEPS } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import {
  buildReviewPlusWorkflowGraph,
  resolveActiveWorkflowStepKey,
} from '@/features/review-plus-v2/utils/reviewPlusWorkflowGraph'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { buildReviewPlusStepDetail } from '@/features/review-plus-v2/utils/reviewPlusStepDetail'
import type { ReviewPlusPipelineStepKey } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { countPendingCoverageHitl } from '@/features/review-plus-v2/utils/aeroDesignerWorkbenchUtils'
import {
  formatAgentIdLabel,
  formatTraceOutputSummary,
} from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'
import type { MaterialClassification, SuperAgentRun, SuperAgentSkillTrace } from '@/features/super-agent/types'
import type { SuperAgentRunPauseContext } from '@/features/super-agent/utils/superAgentResumeState'
import {
  filterBusinessLines,
  sanitizeBusinessReportText,
} from '@/features/super-agent/utils/diagnosticsSanitizer'
import { resolveBusinessExportMarkdown } from '@/features/review-plus-shared/utils/businessReportMarkdown'
import { resolveAdaptiveRouterDiagnostics } from '@/features/super-agent/utils/adaptiveRouterDiagnostics'
import { resolveSmartCommitteeDiagnostics } from '@/features/super-agent/utils/smartCommitteeDiagnostics'
import { formatElapsedMs, ROUTE_LABELS, SUPER_AGENT_PROCESSING_TERMS } from '@/lib/aeroTerminology'
import {
  GNC_WORKFLOW_STEP_DEFS,
} from '@/features/unified-review-workbench/constants/gncWorkflowSteps'
import {
  AC_SUBFLOW_STAGE_DEFS,
  AD_SUBFLOW_STAGE_DEFS,
  buildGncCommitteeSubflowLanes,
  getActiveStagesByPhase,
  resolveReviewScopeEnabledGroups,
  subflowStageStatusLabel,
  summarizeSubflowLane,
  type GncCommitteeSubflowInput,
  type GncSubflowLaneProjection,
  type GncSubflowStageStatus,
} from '@/features/unified-review-workbench/utils/gncCommitteeSubFlows'
import {
  buildGncReviewProcessModel,
  buildGncStageSubtitleFromModel,
} from '@/features/review-process-model/adapters/gncReviewProcessAdapter'
import {
  buildReviewPlusReviewProcessModel,
  buildReviewPlusStageSubtitleFromModel,
} from '@/features/review-process-model/adapters/reviewPlusProcessAdapter'
import {
  buildSmartReviewProcessModel,
  buildSmartStageSubtitleFromModel,
} from '@/features/review-process-model/adapters/smartReviewProcessAdapter'
import {
  buildProcessLaneFromModel,
  findProcessStageIndexByKey,
  resolveProcessStageDeepTasks,
  type ProcessLaneSpec,
} from '@/features/review-process-model/superAgentLaneAdapter'
import type { ReviewProcessModel } from '@/features/review-process-model/types'

const PAUSED_STEP_STATUS: WorkflowStepStatus = 'interrupted'

export function applyRunPauseToStepStatus(
  status: WorkflowStepStatus,
  pauseContext: SuperAgentRunPauseContext,
): WorkflowStepStatus {
  if (status !== 'running') return status
  if (pauseContext === 'active' || pauseContext === 'resuming') return status
  if (pauseContext === 'failed') return 'failed'
  return PAUSED_STEP_STATUS
}

export function isPausedStepStatus(
  status: WorkflowStepStatus,
  pauseContext: SuperAgentRunPauseContext,
): boolean {
  if (pauseContext === 'active' || pauseContext === 'resuming') return false
  return status === PAUSED_STEP_STATUS
}

export function stepStatusDisplayLabel(
  status: WorkflowStepStatus,
  pauseContext: SuperAgentRunPauseContext,
): string {
  if (status === 'running' && pauseContext === 'resuming') return '正在续跑'
  if (status === PAUSED_STEP_STATUS && pauseContext === 'stale') return '等待续跑'
  return STEP_STATUS_LABELS[status] || status
}

function applyPauseToFlowNode<T extends { status: WorkflowStepStatus }>(
  node: T,
  pauseContext: SuperAgentRunPauseContext,
): T {
  return { ...node, status: applyRunPauseToStepStatus(node.status, pauseContext) }
}

function applyPauseToParallelFlow(
  flow: SuperAgentParallelFlowModel,
  pauseContext: SuperAgentRunPauseContext,
): SuperAgentParallelFlowModel {
  if (pauseContext === 'active') return flow
  return {
    ...flow,
    mainBefore: flow.mainBefore.map((node) => applyPauseToFlowNode(node, pauseContext)),
    dispatch: applyPauseToFlowNode(flow.dispatch, pauseContext),
    gate: flow.gate ? applyPauseToFlowNode(flow.gate, pauseContext) : undefined,
    lanes: flow.lanes.map((lane) => ({
      ...lane,
      status: applyRunPauseToStepStatus(lane.status, pauseContext),
      nodes: lane.nodes.map((node) => applyPauseToFlowNode(node, pauseContext)),
    })),
    merge: applyPauseToFlowNode(flow.merge, pauseContext),
    conclusion: applyPauseToFlowNode(flow.conclusion, pauseContext),
  }
}

export type SuperAgentPipelineStepKey =
  | 'upload'
  | 'identify'
  | 'plan'
  | 'launch'
  | 'archive'
  | 'delegate_review'
  | 'synthesize'

export interface SuperAgentPipelineStep {
  step_key: SuperAgentPipelineStepKey
  label: string
  description: string
  skill_ids?: string[]
}

export const SUPER_AGENT_PIPELINE_STEPS: SuperAgentPipelineStep[] = [
  {
    step_key: 'upload',
    label: '上传材料',
    description: '接收用户上传的审查材料（L0 元数据）',
  },
  {
    step_key: 'identify',
    label: '任务判定',
    description: 'L1 轻量分类与路由决策',
  },
  {
    step_key: 'plan',
    label: '解析计划',
    description: 'L2 按 route 选择 parser 与解析深度',
  },
  {
    step_key: 'archive',
    label: '材料解析',
    description: 'L3 单次解析并缓存到 run context',
    skill_ids: ['bootstrap_review_plus_task', 'structure_materials'],
  },
  {
    step_key: 'delegate_review',
    label: '任务执行',
    description: 'L4 按 route 执行 review-plus / GNC / structure',
    skill_ids: ['run_review_plus', 'run_gnc_review', 'structure_materials'],
  },
  {
    step_key: 'launch',
    label: '编排启动',
    description: '进入 Super Agent 统一编排',
  },
  {
    step_key: 'synthesize',
    label: '质量评测',
    description: 'L5 五维质量评分、trace 汇总与报告',
  },
]

export type ProcessingChatRole = 'system' | 'assistant' | 'tool' | 'conclusion'

export interface ProcessingChatMessage {
  id: string
  role: ProcessingChatRole
  title: string
  body?: string
  status?: WorkflowStepStatus
  elapsedMs?: number
  chips?: string[]
  at?: string
}

export interface SuperAgentParallelFlowNode {
  id: string
  label: string
  subtitle: string
  status: WorkflowStepStatus
  badge?: string
  processItemId?: string
}

export interface SuperAgentParallelFlowLane {
  id: string
  title: string
  subtitle: string
  status: WorkflowStepStatus
  nodes: SuperAgentParallelFlowNode[]
  processItemId?: string
}

export interface SuperAgentParallelFlowModel {
  mainBefore: SuperAgentParallelFlowNode[]
  dispatch: SuperAgentParallelFlowNode
  gate?: SuperAgentParallelFlowNode
  lanes: SuperAgentParallelFlowLane[]
  merge: SuperAgentParallelFlowNode
  conclusion: SuperAgentParallelFlowNode
}

export interface SuperAgentProcessItem {
  id: string
  title: string
  summary: string
  status: WorkflowStepStatus
  relation: '串行' | '并行' | '汇合' | '结论'
  tags: string[]
  details: string[]
  findings: string[]
  children?: SuperAgentProcessItem[]
}

export interface SuperAgentFlowNodeContext {
  nodeId: string
  label: string
  subtitle: string
  status: WorkflowStepStatus
  processItemId?: string
}

export interface SuperAgentLlmTraceRecord {
  id: string
  agentName: string
  toolName?: string
  status: string
  elapsedMs?: number
  timestamp?: string
  inputLines: string[]
  outputLines: string[]
  findings: string[]
  warnings: string[]
  evidenceRefs: string[]
}

export type SuperAgentMainFlowStepKey =
  | 'upload'
  | 'identify'
  | 'parse'
  | 'structure'
  | 'review'
  | 'arbitration'
  | 'quality'

export type SuperAgentNodeLevel = 'main' | 'sub'

export type SuperAgentFlowNodeDetailSectionKind =
  | 'summary'
  | 'inputs'
  | 'outputs'
  | 'review'
  | 'diagnostics'
  | 'actions'

export interface SuperAgentFlowNodeDetailSection {
  kind: SuperAgentFlowNodeDetailSectionKind
  title: string
  lines: string[]
}

export interface SuperAgentFlowNodeDetail {
  nodeId: string
  label: string
  status: WorkflowStepStatus
  nodeLevel: SuperAgentNodeLevel
  parentId?: string
  artifactKind?: string
  sections: SuperAgentFlowNodeDetailSection[]
}

export interface SuperAgentNodeDetailPanelSection {
  title: string
  lines: string[]
}

export interface SuperAgentNodeDetailPanelModel {
  businessSummary: string[]
  reviewSections: SuperAgentNodeDetailPanelSection[]
  phaseSections: SuperAgentNodeDetailPanelSection[]
  diagnosticSections: SuperAgentNodeDetailPanelSection[]
}

export interface SuperAgentMainFlowStepMeta {
  stepKey: SuperAgentMainFlowStepKey
  nodeId: string
  label: string
  expandable: boolean
  artifactKind: string
}

export const SUPER_AGENT_MAIN_FLOW_STEPS: SuperAgentMainFlowStepMeta[] = [
  { stepKey: 'upload', nodeId: 'node_upload', label: '上传材料', expandable: false, artifactKind: 'material_upload' },
  { stepKey: 'identify', nodeId: 'node_identify', label: '识别与路由', expandable: true, artifactKind: 'route_decision' },
  { stepKey: 'parse', nodeId: 'node_parse', label: '文档解析', expandable: true, artifactKind: 'document_ir' },
  { stepKey: 'structure', nodeId: 'node_structure', label: '材料结构化', expandable: true, artifactKind: 'structured_bundle' },
  { stepKey: 'review', nodeId: 'node_review', label: '审查执行', expandable: true, artifactKind: 'review_execution' },
  { stepKey: 'arbitration', nodeId: 'node_arbitration', label: '总师综合评判', expandable: true, artifactKind: 'arbiter_summary' },
  { stepKey: 'quality', nodeId: 'node_quality', label: '质量评估与报告', expandable: true, artifactKind: 'quality_report' },
]

export const SUPER_AGENT_MAIN_FLOW_STEP_KEYS: SuperAgentMainFlowStepKey[] = SUPER_AGENT_MAIN_FLOW_STEPS.map(
  (step) => step.stepKey,
)

export type ReviewExecutionMode = 'smart_committee' | 'review_plus' | 'gnc' | 'hybrid' | 'structure_only'

export interface MainProcessNodeSpec {
  stepKey: SuperAgentMainFlowStepKey
  nodeId: string
  label: string
  subtitle: string
  status: WorkflowStepStatus
  expandable: boolean
  artifactKind: string
}

export interface SubProcessNodeSpec {
  subKey: string
  nodeId: string
  parentNodeId: string
  label: string
  subtitle: string
  status: WorkflowStepStatus
  badge?: string
}

const FLOW_SUBTITLE_MAX = 56

/** 文档审查过程画布主链：不含上传/路由/解析等前置步骤 */
export const REVIEW_PROCESS_CANVAS_MAIN_CHAIN_STEP_KEYS: SuperAgentPipelineStepKey[] = ['launch']

export { WORKFLOW_DAG_EDGE_TYPE } from '@aqua/workflow-core'

export interface LaneDeepParallelTask {
  id: string
  label: string
  status: WorkflowStepStatus
  summary: string
}

const REVIEW_PREP_HIDDEN_STEP_KEYS = new Set<SuperAgentPipelineStepKey>(['upload', 'identify', 'plan', 'archive'])

export function reviewProcessHiddenPrepNodeIds(): string[] {
  return [...REVIEW_PREP_HIDDEN_STEP_KEYS].map((key) => `node_${key}`)
}

const DEFAULT_LANE_DEEP_TASKS: Array<{ id: string; label: string; summary: string }> = [
  { id: 'clause-check', label: '条款核验', summary: '对照标准条款核验符合性' },
  { id: 'evidence-check', label: '证据核验', summary: '核验证据引用与覆盖完整性' },
  { id: 'cross-check', label: '交叉核验', summary: '交叉比对多源材料一致性' },
]

export { GNC_WORKFLOW_STEP_DEFS }

export const GNC_WORKFLOW_STEPS = GNC_WORKFLOW_STEP_DEFS

/** User-facing committee stage index in the six-stage GNC flow. */
export const GNC_COMMITTEE_STAGE_INDEX = 2

/** @deprecated Use GNC_COMMITTEE_STAGE_INDEX — kept for tests referencing canvas step index. */
export const GNC_COMMITTEE_COMMITTEE_STEP_INDEX = GNC_COMMITTEE_STAGE_INDEX

export const GNC_COMMITTEE_EXPERT_DEFS = [
  { id: 'quality_engineer', label: '质量审查专家', summary: '材料可审查性与模板符合性核查' },
  { id: 'fdir_specialist', label: 'FDIR 专家', summary: '故障检测隔离与恢复设计审查' },
  { id: 'interface_specialist', label: '接口一致性专家', summary: '分系统接口与数据一致性审查' },
  { id: 'simulation_specialist', label: '仿真验证专家', summary: '仿真方案与验证充分性审查' },
] as const

export const GNC_AD_UNIT_DEFS = AD_SUBFLOW_STAGE_DEFS.map((def) => ({
  id: def.stageKey,
  label: def.stageLabel,
}))

export const GNC_AC_UNIT_DEFS = AC_SUBFLOW_STAGE_DEFS.map((def) => ({
  id: def.stageKey,
  label: def.stageLabel,
}))

export const GNC_COMMITTEE_OBSERVER_DEFS = [
  { id: 'review_editor', label: '合稿师旁听', summary: '合稿归并预备与发现整理' },
  { id: 'gnc_chief_reviewer', label: '总师旁听', summary: '总师审定预备与重大风险关注' },
] as const

export const GNC_HYBRID_EXTENSION_DEFS = [
  {
    stepKey: 'gnc_committee_review',
    nodeId: 'gnc-hybrid-committee-review',
    label: 'GNC 委员会扩展审查',
    summary: '质量 / FDIR / 接口 / 仿真委员会并行扩展',
  },
  {
    stepKey: 'gnc_cross_document_consistency',
    nodeId: 'gnc-hybrid-cross-doc',
    label: 'GNC 跨文档一致性',
    summary: '多文档指标 / 单位 / 分解一致性核验',
  },
] as const

interface GncWorkflowContext {
  result: Record<string, unknown>
  stepOutputs: Record<string, Record<string, unknown>>
  skillStatus: WorkflowStepStatus
  hasStarted: boolean
}

function parseGncStepSummary(summary: unknown): Record<string, unknown> {
  if (summary && typeof summary === 'object') return asRecord(summary)
  if (typeof summary !== 'string' || !summary.trim()) return {}
  try {
    return asRecord(JSON.parse(summary))
  } catch {
    return { summary: compactText(summary, 120) }
  }
}

function mergeGncCommitteeStepOutputs(
  ...sources: Array<Record<string, unknown> | undefined>
): Record<string, unknown> {
  const merged: Record<string, unknown> = {}
  const disciplineReviews: Record<string, unknown> = {}
  let adGroup = asRecord(undefined)
  let acGroup = asRecord(undefined)

  for (const source of sources) {
    const record = asRecord(source)
    if (!Object.keys(record).length) continue
    Object.assign(merged, record)
    const nestedDiscipline = asRecord(record.discipline_reviews)
    Object.assign(disciplineReviews, nestedDiscipline)
    adGroup = pickRicherGroupPayload(adGroup, asRecord(record.ad_group_result))
    acGroup = pickRicherGroupPayload(acGroup, asRecord(record.ac_group_result))
    adGroup = pickRicherGroupPayload(adGroup, asRecord(nestedDiscipline.ad_group))
    acGroup = pickRicherGroupPayload(acGroup, asRecord(nestedDiscipline.ac_group))
  }

  if (Object.keys(disciplineReviews).length) merged.discipline_reviews = disciplineReviews
  if (Object.keys(adGroup).length) merged.ad_group_result = adGroup
  if (Object.keys(acGroup).length) merged.ac_group_result = acGroup
  return merged
}

function pickRicherGroupPayload(
  current: Record<string, unknown>,
  candidate: Record<string, unknown>,
): Record<string, unknown> {
  if (!Object.keys(candidate).length) return current
  if (!Object.keys(current).length) return candidate
  const currentScore = gncGroupPayloadRichness(current)
  const candidateScore = gncGroupPayloadRichness(candidate)
  return candidateScore >= currentScore ? candidate : current
}

function gncGroupPayloadRichness(payload: Record<string, unknown>): number {
  return (
    Object.keys(asRecord(payload.stage_results)).length * 4
    + (Array.isArray(payload.unit_results) ? payload.unit_results.length : 0) * 3
    + (Array.isArray(payload.stages) ? payload.stages.length : 0) * 2
    + Object.keys(asRecord(payload.conclusion)).length
    + (Object.keys(payload).length > 0 ? 1 : 0)
  )
}

function resolveGncCommitteeTraceOutputs(result: Record<string, unknown>): Record<string, unknown> {
  let merged = asRecord(undefined)
  for (const trace of asArray(result.traces)) {
    const record = asRecord(trace)
    if (textValue(record.step) !== 'committee_review') continue
    merged = mergeGncCommitteeStepOutputs(merged, parseGncStepSummary(record.summary))
  }
  return merged
}

function buildGncWorkflowContext(run: SuperAgentRun): GncWorkflowContext {
  const result = asRecord(run.gnc_review_result)
  const stepOutputs: Record<string, Record<string, unknown>> = {}
  const committeeTrace = resolveGncCommitteeTraceOutputs(result)

  for (const trace of asArray(result.traces)) {
    const record = asRecord(trace)
    const stepKey = textValue(record.step)
    if (!stepKey) continue
    const parsed = parseGncStepSummary(record.summary)
    if (stepKey === 'committee_review') {
      stepOutputs.committee_review = mergeGncCommitteeStepOutputs(stepOutputs.committee_review, parsed)
      continue
    }
    stepOutputs[stepKey] = parsed
  }

  for (const stepDef of GNC_WORKFLOW_STEP_DEFS) {
    const direct = asRecord(result[stepDef.stepKey])
    if (!Object.keys(direct).length) continue
    if (stepDef.stepKey === 'committee_review') {
      stepOutputs.committee_review = mergeGncCommitteeStepOutputs(
        committeeTrace,
        stepOutputs.committee_review,
        direct,
      )
      continue
    }
    stepOutputs[stepDef.stepKey] = direct
  }

  if (!Object.keys(stepOutputs.committee_review || {}).length) {
    stepOutputs.committee_review = mergeGncCommitteeStepOutputs(committeeTrace)
  }

  if (Object.keys(asRecord(result.discipline_reviews)).length) {
    stepOutputs.committee_review = mergeGncCommitteeStepOutputs(
      stepOutputs.committee_review,
      {
        discipline_reviews: result.discipline_reviews,
        findings: result.findings,
        conflicts: result.conflicts,
        review_scope: result.review_scope,
        subflow_lanes: result.subflow_lanes,
        ad_group_result: result.ad_group_result,
        ac_group_result: result.ac_group_result,
      },
    )
  }
  if (Object.keys(asRecord(result.chief_decision)).length && !stepOutputs.chief_adjudication) {
    stepOutputs.chief_adjudication = { chief_decision: result.chief_decision }
  }
  if (Object.keys(asRecord(result.editorial_synthesis)).length && !stepOutputs.editorial_synthesis) {
    stepOutputs.editorial_synthesis = { editorial_synthesis: result.editorial_synthesis }
  }
  if (Object.keys(asRecord(result.arbitration)).length && !stepOutputs.human_arbitration) {
    stepOutputs.human_arbitration = asRecord(result.arbitration)
  }

  return {
    result,
    stepOutputs,
    skillStatus: traceNodeStatus(run, 'run_gnc_review'),
    hasStarted: hasTrace(run, 'run_gnc_review'),
  }
}

function resolveGncWorkflowStepStatuses(ctx: GncWorkflowContext): WorkflowStepStatus[] {
  const { stepOutputs, skillStatus, hasStarted, result } = ctx
  const stepKeys = GNC_WORKFLOW_STEP_DEFS.map((item) => item.stepKey)

  const resolveSingle = (stepKey: string, index: number): WorkflowStepStatus => {
    const output = stepOutputs[stepKey]
    if (stepKey === 'human_arbitration') {
      const arbitration = asRecord(output || result.arbitration)
      const status = textValue(arbitration.arbitration_status)
      if (status === 'not_required') return 'skipped'
      if (status === 'pending' || arbitration.requires_arbitration === true) return 'awaiting_confirm'
      if (Object.keys(arbitration).length) return 'completed'
    }
    if (Object.keys(output || {}).length) return 'completed'
    return 'pending'
  }

  if (skillStatus === 'failed' || result.status === 'failed') {
    let failedIndex = stepKeys.findIndex((key) => !Object.keys(stepOutputs[key] || {}).length)
    if (failedIndex < 0) failedIndex = stepKeys.length - 1
    return stepKeys.map((key, index) => {
      if (index < failedIndex && Object.keys(stepOutputs[key] || {}).length) return 'completed'
      if (index === failedIndex) return 'failed'
      return 'pending'
    })
  }

  if (skillStatus === 'completed' || result.status === 'completed') {
    return stepKeys.map((key, index) => resolveSingle(key, index))
  }

  if (!hasStarted && skillStatus === 'pending') {
    return stepKeys.map(() => 'pending')
  }

  const completedCount = stepKeys.filter((key) => Object.keys(stepOutputs[key] || {}).length).length
  const runningIndex = Math.min(completedCount, stepKeys.length - 1)
  return stepKeys.map((key, index) => {
    if (Object.keys(stepOutputs[key] || {}).length) return 'completed'
    if (index === runningIndex && (skillStatus === 'running' || hasStarted)) return 'running'
    return 'pending'
  })
}

function mapGncFlowStatusToWorkflow(status: string): WorkflowStepStatus {
  if (status === 'completed') return 'completed'
  if (status === 'running') return 'running'
  if (status === 'failed') return 'failed'
  if (status === 'skipped') return 'skipped'
  if (status === 'awaiting_confirm') return 'awaiting_confirm'
  if (status === 'blocked') return 'blocked'
  return 'pending'
}

function resolveGncRequiresArbitration(ctx: GncWorkflowContext): boolean | undefined {
  const arbitration = asRecord(ctx.result.arbitration)
  if (textValue(arbitration.arbitration_status) === 'not_required') return false
  if (arbitration.requires_arbitration === true || ctx.result.requires_arbitration === true) return true
  if (arbitration.requires_arbitration === false || ctx.result.requires_arbitration === false) return false
  return undefined
}

function isGncReviewRouteActive(run: SuperAgentRun): boolean {
  return hasRoute(run, ['gnc_review', 'gnc_review_only', 'hybrid']) || hasTrace(run, 'run_gnc_review')
}

/** Backend defaults review_scope to ad_ac; use when gnc_review_result has not synced yet. */
function resolveGncCommitteeReviewScope(run: SuperAgentRun, result: Record<string, unknown>): string | undefined {
  const explicit = textValue(result.review_scope)
  if (explicit) return explicit
  if (!isGncReviewRouteActive(run)) return undefined
  return 'ad_ac'
}

function extractGncCommitteeInput(run: SuperAgentRun): GncCommitteeSubflowInput {
  const ctx = buildGncWorkflowContext(run)
  const reviewScope = resolveGncCommitteeReviewScope(run, ctx.result)
  const committeeOutput = mergeGncCommitteeStepOutputs(
    asRecord(ctx.stepOutputs.committee_review),
    resolveGncCommitteeTraceOutputs(ctx.result),
    {
      review_scope: reviewScope,
      subflow_lanes: ctx.result.subflow_lanes,
      ad_group_result: ctx.result.ad_group_result,
      ac_group_result: ctx.result.ac_group_result,
      discipline_reviews: ctx.result.discipline_reviews,
    },
  )
  return {
    review_scope: textValue(committeeOutput.review_scope) || reviewScope || undefined,
    subflow_lanes: asArray(committeeOutput.subflow_lanes) as Array<Record<string, unknown>>,
    ad_group_result: asRecord(committeeOutput.ad_group_result),
    ac_group_result: asRecord(committeeOutput.ac_group_result),
  }
}

export function resolveGncInitialExpandedTeamLeadIds(run: SuperAgentRun): string[] {
  const lanes = buildGncCommitteeSubflowLanes(extractGncCommitteeInput(run))
  if (!lanes.length) return []

  const ids = new Set<string>(['node_lane_gnc'])
  lanes.forEach((lane) => {
    if (lane.enabled || lane.stages.some((stage) => stage.status !== 'skipped')) {
      ids.add(gncCommitteeGroupTeamLeadId(lane.groupKey))
    }
  })
  return [...ids]
}

function buildGncReviewProcessModelFromRun(run: SuperAgentRun): ReviewProcessModel {
  const ctx = buildGncWorkflowContext(run)
  const statuses = resolveGncWorkflowStepStatuses(ctx)
  const stepSubtitles = Object.fromEntries(
    GNC_WORKFLOW_STEP_DEFS.map((def, index) => [
      def.stepKey,
      buildGncStepSubtitle(run, def.stepKey, statuses[index] || 'pending'),
    ]),
  )
  return buildGncReviewProcessModel({
    stepStatuses: statuses,
    stepSubtitles,
    requiresArbitration: resolveGncRequiresArbitration(ctx),
    committee: extractGncCommitteeInput(run),
    title: 'GNC 审查',
    subtitle: textValue(ctx.result.status) || undefined,
  })
}

function buildReviewPlusProcessModelFromRun(
  run: SuperAgentRun,
  task?: ReviewPlusTaskDetail | null,
): ReviewProcessModel {
  const graph = task ? buildReviewPlusWorkflowGraph(task) : null
  const stepStatuses = Object.fromEntries(
    REVIEW_PLUS_PIPELINE_STEPS.map((step) => [
      step.step_key,
      graph?.nodes.find((node) => node.step_key === step.step_key)?.status || 'pending',
    ]),
  )
  const stepSubtitles = Object.fromEntries(
    REVIEW_PLUS_PIPELINE_STEPS.map((step) => [step.step_key, step.description]),
  )
  return buildReviewPlusReviewProcessModel({
    stepStatuses,
    stepSubtitles,
    sourceReviewId: run.source_review_id || undefined,
    findingCount: Number(run.review_plus_result?.finding_count || 0),
    title: '文件组审查',
    subtitle: task?.status || undefined,
  })
}

function buildSmartReviewProcessModelFromRun(run: SuperAgentRun): ReviewProcessModel {
  const expertTasks = collectExpertTaskSources(run, run.classification)
  const formatGateRecord = resolveFormatGateTaskRecord(run, run.classification)
  const prepareStatus = resolveReviewPrepareStatus(run)
  const committeeStatus = committeeStatusFromRun(run)
  const laneStatuses = expertTasks.map(
    (task) => resolveReviewOutcomeStatus(task.status, task.findingCount, task.maxSeverity).displayStatus,
  )
  const mergeStatus = resolveSmartCommitteeMergeStatus(run, laneStatuses, run.classification)
  const synthesizeStatus = run.status === 'completed' || run.status === 'limited'
    ? 'completed'
    : run.status === 'failed'
      ? 'failed'
      : mergeStatus === 'completed' || mergeStatus === 'awaiting_confirm'
        ? 'running'
        : 'pending'

  return buildSmartReviewProcessModel({
    prepareStatus,
    formatGateStatus: formatGateRecord ? resolveFormatGateStatus(formatGateRecord) : undefined,
    formatGateSubtitle: formatGateRecord
      ? resolveFormatGateOutputSummary(formatGateRecord, run, run.classification)
      : undefined,
    committeeStatus,
    mergeStatus,
    synthesizeStatus,
    expertCount: expertTasks.length,
    expertTasks: expertTasks.map((task) => ({
      taskId: task.taskId,
      title: task.title,
      subtitle: task.objective || task.specialist,
      status: resolveReviewOutcomeStatus(task.status, task.findingCount, task.maxSeverity).displayStatus,
      findingCount: task.findingCount,
    })),
    title: '智能审查',
    subtitle: '智能调度与专家并行审查',
  })
}

function processModelToSubFlow(model: ReviewProcessModel): SubFlowNodeSpec[] {
  return model.stages.map((stage) => ({
    subKey: stage.stageKey,
    label: stage.label,
    subtitle: stage.subtitle || stage.summary || stage.description,
    status: mapGncFlowStatusToWorkflow(stage.status),
    badge: stage.badge,
  }))
}

function processLaneSpecToParallelLane(spec: ProcessLaneSpec): SuperAgentParallelFlowLane {
  return finalizeSequentialLane({
    id: spec.id,
    title: spec.title,
    subtitle: spec.subtitle,
    status: aggregateLaneStatus(spec.nodes.map((node) => node.status)),
    nodes: spec.nodes.map((node) => ({
      id: node.id,
      label: node.label,
      subtitle: node.subtitle,
      status: node.status,
      badge: node.badge,
      processItemId: node.processItemId,
    })),
    processItemId: spec.processItemId,
  })
}

function buildGncUnitCoverageLines(run: SuperAgentRun): string[] {
  const committee = extractGncCommitteeInput(run)
  const lanes = buildGncCommitteeSubflowLanes(committee)
  if (lanes.length) {
    return lanes.flatMap((lane) => {
      const activeStages = lane.stages.filter((stage) => stage.status !== 'skipped')
      if (!lane.enabled) {
        return [`${lane.groupLabel}：${lane.skipReason || summarizeSubflowLane(lane)}`]
      }
      const header = `${lane.groupLabel}（${activeStages.length || lane.stages.length} 环节）`
      const lines = activeStages.map((stage) => {
        const suffix = stage.findingCount ? ` · ${stage.findingCount} 条发现` : ''
        return `${stage.stageLabel}：${subflowStageStatusLabel(stage.status)}${suffix}`
      })
      return lines.length ? [header, ...lines] : [header, summarizeSubflowLane(lane)]
    })
  }

  const { adEnabled, acEnabled } = resolveReviewScopeEnabledGroups(committee.review_scope)
  const lines = ['AD/AC 子流程：尚未产生审查结果（送审后将按 review_scope 启用）']
  if (adEnabled) {
    lines.push(`AD 姿态确定（${AD_SUBFLOW_STAGE_DEFS.length} 环节）`)
    lines.push(...AD_SUBFLOW_STAGE_DEFS.map((def) => `${def.stageLabel}：待执行`))
  }
  if (acEnabled) {
    lines.push(`AC 姿态控制（${AC_SUBFLOW_STAGE_DEFS.length} 环节）`)
    lines.push(...AC_SUBFLOW_STAGE_DEFS.map((def) => `${def.stageLabel}：待执行`))
  }
  return lines
}

function buildGncStepSubtitle(
  run: SuperAgentRun,
  stepKey: string,
  status: WorkflowStepStatus,
): string {
  const ctx = buildGncWorkflowContext(run)
  const output = asRecord(ctx.stepOutputs[stepKey])
  const findings = asArray(ctx.result.findings)
  const conflicts = asArray(ctx.result.conflicts || ctx.result.cross_document_conflicts)

  switch (stepKey) {
    case 'review_intake':
      return output.review_id ? `审查 ${textValue(output.review_id)}` : '接收送审材料与审查范围'
    case 'document_structuring':
      return output.section_count != null
        ? `${output.section_count} 章节 · ${output.evidence_count ?? asArray(output.evidence_pool).length} 条证据`
        : '章节树与审查依据池构建'
    case 'quality_screening':
      return textValue(output.gate_status || output.status) || '质量师判定可审查状态'
    case 'evidence_pool_building':
      return `${asArray(output.evidences || output.evidence_pool).length || findings.length || 0} 条审查依据`
    case 'knowledge_preparation':
      return '规范条款 · 历史问题 · 术语库检索'
    case 'committee_review': {
      const committee = extractGncCommitteeInput(run)
      const lanes = buildGncCommitteeSubflowLanes(committee)
      const laneSummary = lanes
        .filter((lane) => lane.enabled)
        .map((lane) => {
          const activeStages = lane.stages.filter((stage) => stage.status !== 'skipped')
          const findingsInLane = activeStages.reduce((sum, stage) => sum + stage.findingCount, 0)
          const unitCount = activeStages.length || lane.stages.length
          return findingsInLane
            ? `${lane.groupLabel} · ${findingsInLane} 条发现`
            : `${lane.groupLabel}（${unitCount} 环节）`
        })
      if (laneSummary.length) return laneSummary.join(' · ')
      const findingCount = findings.length || asArray(output.findings).length
      if (findingCount) return `${findingCount} 条发现 · AD/AC 专业组`
      if (status === 'running') return 'AD 姿态确定 · AC 姿态控制 审查中'
      return 'AD 姿态确定 · AC 姿态控制'
    }
    case 'editorial_synthesis':
      return textValue(asRecord(output.editorial_synthesis).summary) || '审查意见单与纪要草案'
    case 'chief_adjudication': {
      const decision = asRecord(output.chief_decision || ctx.result.chief_decision)
      return textValue(decision.overall_recommendation || decision.summary) || '总师综合裁定'
    }
    case 'human_arbitration': {
      const arbitration = asRecord(output || ctx.result.arbitration)
      if (arbitration.arbitration_status === 'not_required') return '无需人工仲裁'
      return asArray(arbitration.arbitration_items).length
        ? `${asArray(arbitration.arbitration_items).length} 项待确认`
        : '重大分歧人工确认'
    }
    case 'review_closure':
      return textValue(ctx.result.status) || (status === 'completed' ? '审查闭环归档' : '生成闭环报告')
    default:
      return ''
  }
}

export function resolveGncCommitteeDeepParallelTasks(run: SuperAgentRun): LaneDeepParallelTask[] {
  const model = buildGncReviewProcessModelFromRun(run)
  const committeeIndex = findProcessStageIndexByKey(model, 'committee_review')
  return resolveProcessStageDeepTasks('gnc', committeeIndex, model)
}

function buildGncHybridExtensionNodes(run: SuperAgentRun): SuperAgentParallelFlowNode[] {
  if (resolveReviewExecutionMode(run) !== 'hybrid') return []
  const ctx = buildGncWorkflowContext(run)
  return GNC_HYBRID_EXTENSION_DEFS.map((def) => {
    const output = asRecord(ctx.result[def.stepKey])
    const explicitStatus = textValue(output.status)
    const hasBackendOutput = Object.keys(output).length > 0
    const status: WorkflowStepStatus = explicitStatus === 'failed'
      ? 'failed'
      : explicitStatus === 'running'
        ? 'running'
        : explicitStatus === 'completed' || hasBackendOutput
          ? 'completed'
          : 'pending'
    const outputSummary = compactText(output.summary || output.description || output.finding_count, 80)
    return {
      id: def.nodeId,
      label: def.label,
      subtitle: hasBackendOutput
        ? (outputSummary || '扩展审查节点已返回结果')
        : `规划中（${def.stepKey} 将在混合审查路径下按需执行）`,
      status,
      badge: 'HYBRID',
      processItemId: 'lane-gnc',
    }
  })
}

function formatGncStepLabel(stepKey: string): string {
  const workflowStep = GNC_WORKFLOW_STEP_DEFS.find((step) => step.stepKey === stepKey)
  if (workflowStep) return workflowStep.label
  const hybridStep = GNC_HYBRID_EXTENSION_DEFS.find((step) => step.stepKey === stepKey)
  if (hybridStep) return hybridStep.label
  return compactText(stepKey, 40) || 'GNC 审查步骤'
}

function formatGncTraceSummary(summary: unknown): string {
  const parsed = parseGncStepSummary(summary)
  return formatDetailValue(parsed) || compactText(summary, 100)
}

function buildGncReviewOutputLines(run: SuperAgentRun): string[] {
  const ctx = buildGncWorkflowContext(run)
  const findings = asArray(ctx.result.findings).slice(0, 6).map((item) => formatFindingItem(item))
  const conflicts = asArray(ctx.result.conflicts).slice(0, 4).map((item) => formatFindingItem(item))
  const chief = asRecord(ctx.result.chief_decision)
  const lines = [
    findings.length ? `审查发现 ${asArray(ctx.result.findings).length} 条` : '',
    ...findings,
    conflicts.length ? `冲突 ${asArray(ctx.result.conflicts).length} 组` : '',
    ...conflicts,
    Object.keys(chief).length ? `总师裁定：${compactText(chief.overall_recommendation || chief.summary, 100)}` : '',
  ]
  return filterBusinessLines(lines)
}

export interface SuperAgentProcessingViewModel {
  progress: number
  currentStage: string
  processItems: SuperAgentProcessItem[]
  flowGraph: SuperAgentParallelFlowModel
  workflowGraph: WorkflowGraph
  /** GNC committee 有数据时默认展开的专业组 team_lead（含 lane 外层） */
  initialExpandedTeamLeadIds: string[]
}

export interface ReviewBusinessStatusModel {
  headline: string
  currentStage: string
  progress: number
  delegateSummary: string
  waitingHint: string
  latestFindings: string[]
}

export function buildReviewBusinessStatus(
  viewModel: Pick<SuperAgentProcessingViewModel, 'progress' | 'currentStage' | 'processItems' | 'flowGraph'>,
  run: SuperAgentRun,
  warnings: string[] = [],
): ReviewBusinessStatusModel {
  const delegateItem = viewModel.processItems.find((item) => item.id === 'delegate')
  const mergeItem = viewModel.processItems.find((item) => item.id === 'merge')
  const laneCount = viewModel.flowGraph.lanes.length
  const laneDone = viewModel.flowGraph.lanes.filter(
    (lane) => lane.status === 'completed' || lane.status === 'awaiting_confirm',
  ).length

  const delegateSummary = delegateItem?.summary
    || (laneCount ? `已分派 ${laneCount} 个专项，已回传 ${laneDone}/${laneCount}` : '等待专项分派')

  const latestFindings = [
    ...(mergeItem?.findings || []).slice(0, 2),
    ...(delegateItem?.findings || []).slice(0, 2),
    ...warnings.slice(0, 2),
  ].filter(Boolean).slice(0, 3)

  let headline = '审查进行中'
  if (run.status === 'failed') headline = '审查执行失败'
  else if (run.status === 'interrupted') headline = '审查已中断'
  else if (run.status === 'completed' || run.status === 'limited') headline = '审查已完成'

  const waitingHint =
    run.status === 'running'
      ? `当前：${viewModel.currentStage}。${delegateSummary}`
      : compactText(run.error, 160)

  return {
    headline,
    currentStage: viewModel.currentStage,
    progress: viewModel.progress,
    delegateSummary,
    waitingHint,
    latestFindings,
  }
}

export interface SuperAgentParsedMaterialSummary {
  id: string
  name: string
  fileType: string
  parser: string
  parseStatus: string
  role: string
  roleConfidence?: number
  documentVersion?: string
  baselineId?: string
  summary: string
  metrics: string[]
  warnings: string[]
}

export type SuperAgentReviewItemStatus = 'passed' | 'attention' | 'failed'

export interface SuperAgentReviewItemSummary {
  id: string
  status: SuperAgentReviewItemStatus
  title: string
  requirement: string
  conclusion: string
  recommendation: string
  source: string
  evidenceRefs: string[]
  sourceQuote: string
}

export interface SuperAgentResultExplainability {
  materials: SuperAgentParsedMaterialSummary[]
  reviewItems: SuperAgentReviewItemSummary[]
  chiefReviewItems: SuperAgentReviewItemSummary[]
  conclusionSummary: string
  conclusionBasis: string
  riskItems: string[]
  sourceMaterials: string[]
  checkedScope: string[]
}

const REVIEW_PLUS_EVENT_LABELS: Record<string, string> = {
  material_classification_started: '开始型号资料分类识别',
  material_classification_completed: '型号资料分类识别完成',
  scenario_detection_completed: '审查场景识别完成',
  document_structuring_started: '开始型号资料结构化',
  document_structuring_completed: '型号资料结构化完成',
  chief_orchestration_completed: '送审预审完成',
  rule_extraction_started: '开始标准条款抽取',
  rule_extraction_completed: '标准条款抽取完成',
  rule_section_mapping_started: '开始条款-资料映射',
  rule_section_mapping_completed: '条款-资料映射完成',
  item_review_started: '开始符合性判读',
  item_review_completed: '符合性判读完成',
  traceability_building_started: '开始追溯链构建',
  traceability_completed: '追溯链构建完成',
  cross_document_review_completed: '跨文档一致性审查完成',
  chief_comprehensive_review_completed: '总审查员综合判断完成',
  report_composition_started: '开始审查报告编制',
  report_composition_completed: '审查报告编制完成',
  workflow_failed: '流程异常',
}

const REVIEW_ITEM_STATUS_LABELS: Record<SuperAgentReviewItemStatus, string> = {
  passed: '通过',
  attention: '需关注',
  failed: '不符合',
}

const JUDGMENT_TO_STATUS: Record<string, SuperAgentReviewItemStatus> = {
  satisfied: 'passed',
  not_applicable: 'passed',
  insufficient_evidence: 'attention',
  not_checked: 'attention',
  not_satisfied: 'failed',
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function textValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

function numberValue(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function countSections(sectionTree: Record<string, unknown>): number {
  const sections = asArray(sectionTree.sections)
  if (sections.length) return sections.length
  return numberValue(sectionTree.section_count)
}

function countEvidences(evidencePool: Record<string, unknown>): number {
  const evidences = asArray(evidencePool.evidences)
  if (evidences.length) return evidences.length
  return numberValue(evidencePool.evidence_count)
}

function summarizeNamedRecords(value: unknown, limit = 3): string[] {
  return asArray(value).slice(0, limit).map((item, index) => {
    const record = asRecord(item)
    return compactText(
      record.title
        || record.heading
        || record.name
        || record.section_title
        || record.text
        || record.content
        || `条目 ${index + 1}`,
      90,
    )
  }).filter(Boolean)
}

function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    review_rule: '审查规则',
    checklist: '检查单',
    task_book: '任务书',
    subject_report: '被审报告',
    subject_document: '待审文档',
    supporting_attachment: '支撑附件',
    unknown: '未识别',
  }
  return labels[role] || role || '未识别'
}

function compactText(value: unknown, max = 120): string {
  if (value !== null && typeof value === 'object') {
    const formatted = formatDetailValue(value)
    if (formatted && !formatted.includes('[object Object]')) return formatted.length > max ? `${formatted.slice(0, max)}...` : formatted
  }
  const text = textValue(value).replace(/\s+/g, ' ').trim()
  if (text === '[object Object]') return ''
  return text.length > max ? `${text.slice(0, max)}...` : text
}

const SUMMARY_FIELD_LABELS: Record<string, string> = {
  material_count: '材料',
  evidence_count: '证据',
  check_item_count: '检查项',
  section_count: '章节',
  finding_count: '发现',
  objective: '任务目标',
  specialist_id: '专家',
  domain_id: '领域',
  assignment_reason: '分配理由',
  primary_path: '主路径',
  gate_summary: '门禁摘要',
  summary: '摘要',
}

const EXECUTION_MODE_LABELS: Record<string, string> = {
  generic_llm_harness: '通用 LLM 专家审查',
  deterministic: '确定性审查',
  planned: '待执行',
  unknown: '未知',
  harness: 'Harness 审查',
}

export function formatExecutionModeLabel(mode: string): string {
  const trimmed = textValue(mode).trim()
  if (!trimmed) return ''
  return EXECUTION_MODE_LABELS[trimmed] || trimmed
}

function formatEvidenceRefLabel(ref: unknown): string {
  if (typeof ref === 'string') return compactText(ref, 80)
  const record = asRecord(ref)
  return compactText(
    record.evidence_id
      || record.ref
      || record.id
      || record.label
      || record.title,
    80,
  )
}

export function formatFindingItem(item: unknown): string {
  if (item === null || item === undefined) return ''
  if (typeof item === 'string') return compactText(item, 200)
  if (typeof item !== 'object') return compactText(item, 200)

  const record = asRecord(item)
  const title = compactText(
    record.title
      || record.summary
      || record.message
      || record.description
      || record.text,
    120,
  )
  const severity = record.severity ? `严重度：${textValue(record.severity)}` : ''
  const evidenceRefs = asArray(record.evidence_refs)
    .map(formatEvidenceRefLabel)
    .filter(Boolean)
  const evidenceLabel = evidenceRefs.length ? `证据引用：${evidenceRefs.slice(0, 3).join('、')}` : ''
  const parts = [title, severity, evidenceLabel].filter(Boolean)
  if (parts.length) return parts.join(' · ')
  return formatDetailValue(item, { preferDiagnostics: true })
}

function formatSummaryCountParts(record: Record<string, unknown>): string[] {
  const parts: string[] = []
  const countFields = [
    ['material_count', '份材料'],
    ['evidence_count', '条证据'],
    ['check_item_count', '条检查项'],
    ['section_count', '个章节'],
    ['finding_count', '条发现'],
  ] as const
  for (const [key, suffix] of countFields) {
    const value = record[key]
    if (value != null && value !== '') parts.push(`${value} ${suffix}`)
  }
  return parts
}

export function formatSummaryRecord(value: unknown, maxFields = 6): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return compactText(value, 200)
  if (typeof value !== 'object') return compactText(value, 200)

  const record = asRecord(value)
  const primary = record.summary || record.description || record.title || record.message
  if (typeof primary === 'string' && primary.trim()) return compactText(primary, 200)

  const lines: string[] = []
  if (record.objective) lines.push(`任务目标：${compactText(record.objective, 80)}`)

  const countParts = formatSummaryCountParts(record)
  const bootstrap = asRecord(record.bootstrap_summary)
  if (!countParts.length) countParts.push(...formatSummaryCountParts(bootstrap))
  if (countParts.length) lines.push(countParts.join(' / '))

  const labeledEntries = Object.entries(record)
    .filter(([key, entryValue]) => (
      entryValue != null
      && entryValue !== ''
      && !['bootstrap_summary', 'objective', 'summary', 'description', 'title', 'message'].includes(key)
      && !key.endsWith('_count')
    ))
    .slice(0, maxFields)
    .map(([key, entryValue]) => {
      const label = SUMMARY_FIELD_LABELS[key] || key
      if (typeof entryValue === 'object') return ''
      return `${label}：${compactText(entryValue, 80)}`
    })
    .filter(Boolean)
  lines.push(...labeledEntries)

  return filterBusinessLines(lines).join(' · ')
}

export function formatDetailValue(
  value: unknown,
  options?: { preferDiagnostics?: boolean },
): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') {
    const text = compactText(value, 240)
    return text === '[object Object]' ? '' : text
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const items = value.map((item) => formatFindingItem(item)).filter(Boolean)
    if (items.length) return items.slice(0, 4).join('；')
    return `${value.length} 项`
  }
  if (typeof value === 'object') {
    const summary = formatSummaryRecord(value)
    if (summary) return summary
    if (options?.preferDiagnostics) {
      try {
        return compactText(JSON.stringify(value, null, 0), 160)
      } catch {
        return ''
      }
    }
    return ''
  }
  const text = compactText(value, 240)
  return text === '[object Object]' ? '' : text
}

function sanitizeDetailLines(lines: string[]): string[] {
  return filterBusinessLines(
    lines
      .map((line) => formatDetailValue(line))
      .filter((line) => Boolean(line) && !line.includes('[object Object]')),
  )
}

function resolveFormatGateLabel(gate: Record<string, unknown>): string {
  const title = textValue(gate.title)
  if (title.includes('送审') || title.includes('材料门禁')) return '送审材料门禁'
  if (title.includes('格式') || String(gate.kind || '') === 'format_gate') return '格式预审'
  return '格式预审'
}

function resolveFormatGateStatus(gate: Record<string, unknown> | null): WorkflowStepStatus {
  if (!gate) return 'pending'
  return mapTaskBoardStatus(String(gate.status || 'pending'))
}

type FormatGateVerdict = 'passed' | 'needs_supplement' | 'blocked' | 'warning' | 'pending' | 'running'

interface FormatGateOutputContext {
  gateStatus: WorkflowStepStatus
  verdict: FormatGateVerdict
  verdictLabel: string
  checkCount: number
  evidenceCount: number
  missingItems: unknown[]
  findingLines: string[]
  warnings: string[]
  summary: string
}

function readBootstrapSummaryRecord(
  run: SuperAgentRun,
  classification?: MaterialClassification | null,
): Record<string, unknown> {
  const review = asRecord(run.review_plus_result)
  const fromReview = asRecord(review.bootstrap_summary)
  if (Object.keys(fromReview).length) return fromReview
  const fromClassification = asRecord(classification?.bootstrap_summary)
  if (Object.keys(fromClassification).length) return fromClassification
  const docReview = asRecord(run.phase_artifacts?.document_review)
  return asRecord(docReview.bootstrap_summary)
}

function resolveFormatGateOutputContext(
  gate: Record<string, unknown>,
  run: SuperAgentRun,
  classification?: MaterialClassification | null,
): FormatGateOutputContext {
  const resolvedClassification = classification || run.classification
  const gateOutput = asRecord(gate.output_summary)
  const gateInput = asRecord(gate.input_summary)
  const inputBootstrap = asRecord(gateInput.bootstrap_summary)
  const reviewOutput = asRecord(gateOutput.review)
  const reviewSummary = asRecord(reviewOutput.summary)
  const nestedSummary = asRecord(gateOutput.summary)
  const bootstrap = readBootstrapSummaryRecord(run, resolvedClassification)
  const committeeTrace = skillTraceById(run.skill_traces || [], 'smart_review_committee')
  const traceBootstrap = asRecord(asRecord(committeeTrace?.output_summary).bootstrap_summary)
  const boardMeta = asRecord(asRecord(asRecord(run.review_plus_result).smart_task_board).metadata)
  const boardBootstrap = asRecord(boardMeta.bootstrap_summary)
  const stats = run.structured_bundle?.stats || {}

  const checkCount = Number(
    gateOutput.check_item_count
    ?? gateOutput.check_count
    ?? gateOutput.checked_count
    ?? reviewSummary.check_item_count
    ?? nestedSummary.check_item_count
    ?? gateInput.check_item_count
    ?? inputBootstrap.synthetic_check_item_count
    ?? bootstrap.synthetic_check_item_count
    ?? traceBootstrap.synthetic_check_item_count
    ?? boardBootstrap.synthetic_check_item_count
    ?? stats.check_item_count
    ?? 0,
  )
  const evidenceCount = Number(
    gateOutput.evidence_count
    ?? reviewSummary.evidence_count
    ?? nestedSummary.evidence_count
    ?? gateInput.evidence_count
    ?? gateInput.material_count
    ?? inputBootstrap.source_evidence_ref_count
    ?? bootstrap.source_evidence_ref_count
    ?? traceBootstrap.source_evidence_ref_count
    ?? boardBootstrap.source_evidence_ref_count
    ?? stats.evidence_count
    ?? 0,
  )

  let missingItems = asArray(
    gateOutput.missing_items ?? gateOutput.missing ?? gateOutput.missing_slots,
  )

  const findingLines = collectFindingLines(
    gateOutput.findings,
    gate.findings,
    reviewOutput.findings,
  )
  const warnings = filterBusinessLines(
    asArray(gateOutput.warnings ?? reviewOutput.warnings).map((item) => formatDetailValue(item)),
  )

  const gateStatus = mapTaskBoardStatus(String(gate.status || gateOutput.status || 'pending'))
  const gateStatusText = String(gateOutput.gate_status || reviewOutput.gate_status || '').toLowerCase()
  const passed = gateOutput.passed ?? gateOutput.gate_passed ?? (
    gateStatusText === 'passed'
      ? true
      : gateStatusText === 'blocked'
        ? false
        : undefined
  )
  if (!missingItems.length && passed !== true && gateStatusText !== 'passed') {
    missingItems = asArray(resolvedClassification?.missing_slots)
  }
  const blocked = gateStatus === 'failed'
    || gateStatus === 'blocked'
    || passed === false
    || gateStatusText === 'blocked'

  let verdict: FormatGateVerdict
  if (gateStatus === 'running') verdict = 'running'
  else if (blocked) verdict = 'blocked'
  else if (passed === true || gateStatusText === 'passed') verdict = 'passed'
  else if (gateStatus === 'pending') {
    if (missingItems.length) verdict = 'needs_supplement'
    else if (checkCount || evidenceCount || findingLines.length || warnings.length) verdict = 'warning'
    else verdict = 'pending'
  }
  else if (
    missingItems.length
    || gateStatusText === 'limited'
    || warnings.length
    || findingLines.length
  ) {
    verdict = missingItems.length || gateStatusText === 'limited' ? 'needs_supplement' : 'warning'
  } else if (gateStatus === 'completed') {
    verdict = 'passed'
  } else {
    verdict = 'pending'
  }

  const verdictLabels: Record<FormatGateVerdict, string> = {
    passed: '预审通过',
    needs_supplement: '需补充',
    blocked: '阻断',
    warning: '需补充',
    pending: '待预审',
    running: '预审进行中',
  }

  const summary = compactText(
    typeof gateOutput.summary === 'string'
      ? gateOutput.summary
      : typeof gateOutput.gate_summary === 'string'
        ? gateOutput.gate_summary
        : reviewSummary.message
        ?? nestedSummary.message
        ?? gate.summary
        ?? bootstrap.synthetic_context_label,
    180,
  )

  return {
    gateStatus,
    verdict,
    verdictLabel: verdictLabels[verdict],
    checkCount,
    evidenceCount,
    missingItems,
    findingLines,
    warnings,
    summary,
  }
}

function buildFormatGateBusinessLines(
  ctx: FormatGateOutputContext,
  formatGate: Record<string, unknown>,
): string[] {
  return filterBusinessLines([
    `预审结果：${ctx.verdictLabel}`,
    ctx.checkCount ? `检查项 ${ctx.checkCount} 个` : '',
    ctx.evidenceCount ? `证据 ${ctx.evidenceCount} 条` : '',
    ctx.missingItems.length ? `缺失项 ${ctx.missingItems.length} 个` : '',
    ctx.findingLines.length ? `问题 ${ctx.findingLines.length} 项` : '',
    ctx.warnings.length ? `警告 ${ctx.warnings.length} 项` : '',
    `门禁项：${resolveFormatGateLabel(formatGate)}`,
    `状态：${stepStatusDisplayLabel(ctx.gateStatus, 'active')}`,
    ctx.summary,
  ])
}

function buildFormatGateOutputLines(ctx: FormatGateOutputContext): string[] {
  return filterBusinessLines([
    `结论：${ctx.verdictLabel}`,
    ctx.checkCount ? `检查项 ${ctx.checkCount} 个` : '',
    ctx.evidenceCount ? `证据 ${ctx.evidenceCount} 条` : '',
    ctx.findingLines.length ? `问题 ${ctx.findingLines.length} 项` : '',
    ctx.missingItems.length ? `缺失 ${ctx.missingItems.length} 项` : '',
    ctx.warnings.length ? `警告 ${ctx.warnings.length} 项` : '',
    ...ctx.missingItems.slice(0, 3).map((item) => formatDetailValue(item)),
    ...ctx.findingLines.slice(0, 3),
    ...ctx.warnings.slice(0, 3),
  ])
}

function buildFormatGateFallbackDetail(
  nodeId: string,
  run: SuperAgentRun,
  classification?: MaterialClassification | null,
): SuperAgentFlowNodeDetail {
  const stats = run.structured_bundle?.stats || {}
  const missingItems = asArray(classification?.missing_slots || run.classification?.missing_slots)
  const checkCount = Number(stats.check_item_count || run.structured_bundle?.check_items?.length || 0)
  const evidenceCount = Number(stats.evidence_count || 0)
  const committeeStatus = committeeStatusFromRun(run)
  const gateStatus: WorkflowStepStatus = committeeStatus === 'running' ? 'running' : 'pending'
  const hasMaterialStats = checkCount > 0 || evidenceCount > 0
  const verdictLabel = missingItems.length
    ? '需补充'
    : hasMaterialStats
      ? '预审通过'
      : '待预审'
  const summaryLine = missingItems.length
    ? `等待格式预审结果，已识别 ${missingItems.length} 项材料缺失`
    : hasMaterialStats
      ? '已完成材料可审查性检查，未发现阻断项'
      : '等待格式预审结果'

  const sections: SuperAgentFlowNodeDetailSection[] = [{
    kind: 'summary',
    title: '业务摘要',
    lines: filterBusinessLines([
      `预审结果：${verdictLabel}`,
      checkCount ? `检查项 ${checkCount} 个` : '',
      evidenceCount ? `证据 ${evidenceCount} 条` : '',
      missingItems.length ? `缺失项 ${missingItems.length} 个` : '',
      summaryLine,
    ]),
  }, {
    kind: 'outputs',
    title: '预审输出',
    lines: filterBusinessLines([
      `结论：${verdictLabel}`,
      checkCount ? `检查项 ${checkCount} 个` : '',
      evidenceCount ? `证据 ${evidenceCount} 条` : '',
      missingItems.length ? `缺失 ${missingItems.length} 项` : '',
      ...missingItems.slice(0, 3).map((item) => formatDetailValue(item)),
    ]),
  }]

  return {
    nodeId,
    label: '格式预审',
    status: gateStatus,
    nodeLevel: 'main',
    sections,
  }
}

function summarizeFindingSeverityDistribution(run: SuperAgentRun): string {
  const review = asRecord(run.review_plus_result)
  const counts: Record<ReviewSeverityLevel, number> = {
    none: 0,
    info: 0,
    minor: 0,
    major: 0,
    critical: 0,
  }
  asArray(review.specialist_reviews).forEach((item) => {
    asArray(asRecord(item).findings).forEach((finding) => {
      const record = asRecord(finding)
      const severity = normalizeReviewSeverity(record.severity || record.level || record.priority)
      if (severity !== 'none') counts[severity] += 1
    })
  })
  const parts: string[] = []
  if (counts.critical) parts.push(`严重 ${counts.critical}`)
  if (counts.major) parts.push(`高 ${counts.major}`)
  if (counts.minor) parts.push(`低 ${counts.minor}`)
  if (counts.info) parts.push(`提示 ${counts.info}`)
  return parts.length ? `严重度：${parts.join(' · ')}` : ''
}

function resolveExpertStatusWithGate(
  expertStatus: WorkflowStepStatus,
  gateStatus: WorkflowStepStatus,
): WorkflowStepStatus {
  if (gateStatus === 'failed' || gateStatus === 'blocked') {
    return 'blocked'
  }
  if (gateStatus === 'pending' || gateStatus === 'running' || gateStatus === 'interrupted') {
    if (
      expertStatus === 'completed'
      || expertStatus === 'running'
      || expertStatus === 'awaiting_confirm'
    ) {
      return 'pending'
    }
  }
  return expertStatus
}

function resolveEffectiveGateDownstreamStatus(
  gate: Record<string, unknown> | null,
  run: SuperAgentRun,
  classification?: MaterialClassification | null,
): WorkflowStepStatus {
  if (!gate) return 'completed'
  const ctx = resolveFormatGateOutputContext(gate, run, classification)
  const taskStatus = resolveFormatGateStatus(gate)
  if (taskStatus === 'failed' || taskStatus === 'blocked') return taskStatus
  if (ctx.verdict === 'blocked') return 'blocked'
  if (taskStatus === 'running') return 'running'
  if (taskStatus === 'pending') return 'pending'
  return taskStatus
}

const SMART_DEPENDENCY_WAIT_MESSAGES = {
  upstream: '等待前置节点完成',
  gateBlocked: '前置门禁未通过，暂停执行',
  experts: '等待专家审查完成后汇总',
  merge: '等待总师综合评判完成后生成报告',
} as const

function isSmartDependencyTerminal(status: WorkflowStepStatus): boolean {
  return status === 'completed' || status === 'skipped' || status === 'awaiting_confirm'
}

function isSmartDependencyBlocking(status: WorkflowStepStatus): boolean {
  return status === 'failed' || status === 'blocked'
}

function isSmartDependencyIncomplete(status: WorkflowStepStatus): boolean {
  return status === 'pending' || status === 'running' || status === 'interrupted'
}

export function capNodeStatusByDependencies(
  nodeStatus: WorkflowStepStatus,
  dependencyStatuses: WorkflowStepStatus[],
): WorkflowStepStatus {
  if (!dependencyStatuses.length) return nodeStatus

  if (dependencyStatuses.some(isSmartDependencyBlocking)) {
    if (nodeStatus === 'failed' || nodeStatus === 'blocked') return nodeStatus
    return 'blocked'
  }

  if (dependencyStatuses.some(isSmartDependencyIncomplete)) {
    if (nodeStatus === 'completed' || nodeStatus === 'awaiting_confirm') return 'pending'
    if (nodeStatus === 'running' && dependencyStatuses.some((status) => status === 'pending')) {
      return 'pending'
    }
  }

  return nodeStatus
}

function appendSmartDependencyWaitSubtitle(
  subtitle: string,
  waitMessage: string,
): string {
  if (subtitle.includes(waitMessage)) return subtitle
  const base = compactText(subtitle, 80)
  return flowSubtitle(base ? `${waitMessage} · ${base}` : waitMessage) || waitMessage
}

export type ReviewSeverityLevel = 'critical' | 'major' | 'minor' | 'info' | 'none'

export interface ReviewOutcomeStatus {
  executionStatus: WorkflowStepStatus
  displayStatus: WorkflowStepStatus
  outcomeLabel: string
  findingCount: number
  maxSeverity: ReviewSeverityLevel
}

const REVIEW_SEVERITY_RANK: Record<ReviewSeverityLevel, number> = {
  none: 0,
  info: 1,
  minor: 2,
  major: 3,
  critical: 4,
}

function normalizeReviewSeverity(value: unknown): ReviewSeverityLevel {
  const text = textValue(value).toLowerCase()
  if (!text) return 'none'
  if (text.includes('critical') || text.includes('严重') || text === 'high' || text === 'error') return 'critical'
  if (text.includes('major') || text.includes('高')) return 'major'
  if (text.includes('minor') || text.includes('低') || text.includes('warning') || text.includes('中')) return 'minor'
  if (text.includes('info')) return 'info'
  return 'minor'
}

function mergeReviewSeverity(current: ReviewSeverityLevel, next: ReviewSeverityLevel): ReviewSeverityLevel {
  return REVIEW_SEVERITY_RANK[next] > REVIEW_SEVERITY_RANK[current] ? next : current
}

function extractFindingRecords(...sources: unknown[]): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = []
  sources.forEach((source) => {
    if (!Array.isArray(source)) return
    source.forEach((item) => {
      if (typeof item === 'string' && item.trim()) records.push({ title: item })
      else if (item && typeof item === 'object') records.push(asRecord(item))
    })
  })
  return records
}

function countExpertFindings(
  task: Record<string, unknown>,
  output: Record<string, unknown>,
  nested: Record<string, unknown>,
): { findingCount: number; maxSeverity: ReviewSeverityLevel } {
  const reviewOutput = asRecord(output.review)
  const explicitCount = Number(
    task.findings_count
    ?? output.findings_count
    ?? output.finding_count
    ?? nested.findings_count
    ?? nested.finding_count
    ?? reviewOutput.findings_count
    ?? reviewOutput.finding_count
    ?? 0,
  )
  const records = extractFindingRecords(
    task.findings,
    output.findings,
    nested === reviewOutput ? [] : nested.findings,
    reviewOutput.findings,
  )
  const findingCount = explicitCount > 0 ? explicitCount : records.length
  let maxSeverity: ReviewSeverityLevel = 'none'
  records.forEach((record) => {
    maxSeverity = mergeReviewSeverity(
      maxSeverity,
      normalizeReviewSeverity(record.severity || record.level || record.priority),
    )
  })
  if (findingCount > 0 && maxSeverity === 'none') maxSeverity = 'minor'
  return { findingCount, maxSeverity }
}

export function resolveReviewOutcomeStatus(
  executionStatus: WorkflowStepStatus,
  findingCount: number,
  maxSeverity: ReviewSeverityLevel = findingCount > 0 ? 'minor' : 'none',
): ReviewOutcomeStatus {
  if (executionStatus === 'failed' || executionStatus === 'blocked') {
    return {
      executionStatus,
      displayStatus: executionStatus,
      outcomeLabel: executionStatus === 'blocked' ? '未放行' : '执行失败',
      findingCount,
      maxSeverity,
    }
  }
  if (executionStatus === 'running') {
    return {
      executionStatus,
      displayStatus: 'running',
      outcomeLabel: '审查进行中',
      findingCount,
      maxSeverity,
    }
  }
  if (executionStatus === 'pending' || executionStatus === 'skipped' || executionStatus === 'interrupted') {
    return {
      executionStatus,
      displayStatus: executionStatus,
      outcomeLabel: stepStatusDisplayLabel(executionStatus, 'active'),
      findingCount,
      maxSeverity,
    }
  }
  if (findingCount <= 0) {
    return {
      executionStatus,
      displayStatus: 'completed',
      outcomeLabel: '审查完成，暂无发现',
      findingCount: 0,
      maxSeverity: 'none',
    }
  }
  const displayStatus: WorkflowStepStatus = maxSeverity === 'critical' ? 'failed' : 'awaiting_confirm'
  const outcomeLabel = maxSeverity === 'critical'
    ? `发现 ${findingCount} 项 · 含严重问题`
    : maxSeverity === 'major'
      ? `发现 ${findingCount} 项 · 需关注`
      : `发现 ${findingCount} 项`
  return {
    executionStatus,
    displayStatus,
    outcomeLabel,
    findingCount,
    maxSeverity,
  }
}

function resolveFormatGateOutputSummary(
  gate: Record<string, unknown>,
  run: SuperAgentRun,
  classification?: MaterialClassification | null,
): string {
  const ctx = resolveFormatGateOutputContext(gate, run, classification)
  if (ctx.verdict === 'running') return flowSubtitle('预审进行中') || '预审进行中'
  if (ctx.verdict === 'pending' && !ctx.checkCount && !ctx.evidenceCount && !ctx.missingItems.length) {
    return flowSubtitle('等待格式预审') || '等待格式预审'
  }

  const parts: string[] = []
  if (ctx.verdict !== 'warning' || ctx.missingItems.length) {
    parts.push(ctx.verdictLabel)
  } else {
    parts.push('待预审')
  }
  if (ctx.checkCount) parts.push(`${ctx.checkCount} 条检查项`)
  if (ctx.evidenceCount) parts.push(`${ctx.evidenceCount} 条证据`)
  if (ctx.missingItems.length && ctx.verdict !== 'blocked') {
    parts.push(`${ctx.missingItems.length} 项缺失`)
  }
  if (ctx.findingLines.length && ctx.verdict !== 'passed') {
    parts.push(`${ctx.findingLines.length} 项问题`)
  }

  const summary = parts.join(' · ')
  if (summary !== ctx.verdictLabel) return flowSubtitle(summary) || summary
  if (ctx.summary) return flowSubtitle(compactText(ctx.summary, 80)) || compactText(ctx.summary, 80)
  return flowSubtitle('检查材料完整性与可审查性') || '检查材料完整性与可审查性'
}

function resolveSmartDispatchOutputSummary(
  run: SuperAgentRun,
  expertCount: number,
  formatGateRecord: Record<string, unknown> | null,
): string {
  const phase = resolveSmartDispatchPlanPhase(run, expertCount)
  const parts = [
    expertCount ? `已选 ${expertCount} 位专家` : '待选择专家',
    phase ? `阶段：${phase}` : '',
  ]
  if (formatGateRecord) {
    const gateStatus = mapTaskBoardStatus(String(formatGateRecord.status || 'pending'))
    parts.push(`门禁：${stepStatusDisplayLabel(gateStatus, 'active')}`)
  }
  const route = run.route_decision?.route || run.classification?.recommended_route
  if (route) parts.push(`路径：${ROUTE_LABELS[route] || route}`)
  return flowSubtitle(parts.filter(Boolean).join(' · ')) || parts.filter(Boolean).join(' · ')
}

function resolveSmartMergeOutputSummary(run: SuperAgentRun, classification?: MaterialClassification): string {
  const smartDiag = resolveSmartCommitteeDiagnostics(run, classification)
  const findingCount = Number(run.review_plus_result?.finding_count || 0)
  const review = asRecord(run.review_plus_result)
  const arbiterSummary = asRecord(review.arbiter_summary)
  const conflictCount = Number(review.conflict_count || Object.keys(asRecord(arbiterSummary.conflicts)).length || 0)
  if (smartDiag.arbiterConsensusSummary) {
    return flowSubtitle(compactText(smartDiag.arbiterConsensusSummary, 56))
      || compactText(smartDiag.arbiterConsensusSummary, 56)
  }
  if (findingCount) {
    return flowSubtitle(`已汇总 ${findingCount} 条发现${conflictCount ? ` · 冲突 ${conflictCount} 组` : ''}`)
      || `已汇总 ${findingCount} 条发现`
  }
  return flowSubtitle('按证据覆盖、发现严重度、专家置信度加权汇总') || '等待专家回传'
}

function resolveSmartSynthesizeOutputSummary(run: SuperAgentRun): string {
  const findingCount = Number(run.review_plus_result?.finding_count || 0)
  const overall = run.quality_report?.overall_score
  const smartDiag = resolveSmartCommitteeDiagnostics(run, run.classification)
  const citation = smartDiag.citationCoverage
  const review = asRecord(run.review_plus_result)
  const evidenceCoverage = review.evidence_coverage != null
    ? Number(review.evidence_coverage)
    : run.quality_report?.evidence_quality_score
  if (run.status === 'completed' || run.status === 'limited') {
    const parts = [run.status === 'limited' ? 'limited 报告' : '报告已生成']
    if (overall != null) parts.push(`质量 ${Math.round(Number(overall) * 100)}%`)
    if (citation != null) parts.push(`引用 ${Math.round(citation * 100)}%`)
    if (evidenceCoverage != null) parts.push(`证据 ${Math.round(Number(evidenceCoverage) * 100)}%`)
    if (findingCount) parts.push(`${findingCount} 条问题`)
    return flowSubtitle(parts.join(' · ')) || parts.join(' · ')
  }
  return flowSubtitle('等待质量复核与报告生成') || '等待质量复核与报告生成'
}

function hasSmartCommitteeExpertLanes(lanes: SuperAgentParallelFlowLane[]): boolean {
  return lanes.some((lane) => (
    lane.id !== 'discovering'
    && lane.nodes.some((node) => !node.id.endsWith('-discovering'))
  ))
}

function formatExpertInputSummary(
  task: Record<string, unknown>,
  run: SuperAgentRun,
  output: Record<string, unknown>,
  nested: Record<string, unknown>,
): string {
  const raw = task.input_summary ?? output.input_summary ?? nested.input_summary
  const formatted = formatSummaryRecord(raw)
  const stats = run.structured_bundle?.stats || {}
  const countParts = [
    stats.material_count || run.materials?.length
      ? `${stats.material_count || run.materials?.length || 0} 份材料`
      : '',
    stats.evidence_count ? `${stats.evidence_count} 条证据` : '',
    stats.check_item_count || run.structured_bundle?.check_items?.length
      ? `${stats.check_item_count || run.structured_bundle?.check_items?.length || 0} 条检查项`
      : '',
  ].filter(Boolean)
  const countLine = countParts.join(' / ')
  if (formatted && countLine && !formatted.includes('材料') && !formatted.includes('证据')) {
    return `${formatted} · ${countLine}`
  }
  if (formatted) return formatted
  return countLine
}

function collectFindingLines(...sources: unknown[]): string[] {
  return filterBusinessLines(sources.flatMap((source) => {
    if (Array.isArray(source)) return source.map((item) => formatFindingItem(item))
    return [formatFindingItem(source)]
  }))
}

function markdownText(value: unknown): string {
  return textValue(value).replace(/\s+/g, ' ').trim()
}

function markdownBullet(label: string, value: unknown): string {
  const text = markdownText(value)
  return text ? `  - ${label}：${text}` : ''
}

function markdownList(values: string[], fallback: string): string[] {
  const lines = values.map((value) => markdownText(value)).filter(Boolean)
  return lines.length ? lines.map((value) => `- ${value}`) : [`- ${fallback}`]
}

function chunkBelongsToMaterial(chunk: Record<string, unknown>, materialName: string): boolean {
  const candidates = [
    chunk.document_name,
    chunk.material_name,
    chunk.source,
    chunk.file_name,
    chunk.filename,
    chunk.name,
  ].map(textValue)
  return candidates.some((candidate) => candidate === materialName || candidate.endsWith(`/${materialName}`))
}

function materialContentLength(material: Record<string, unknown>): number {
  const content = textValue(material.content)
  if (content) return content.length
  const preview = textValue(material.content_preview)
  return preview.length
}

function materialSummary(material: Record<string, unknown>, chunks: Record<string, unknown>[]): string {
  const explicitSummary = compactText(material.summary || material.abstract || material.content_preview, 140)
  if (explicitSummary) return explicitSummary
  const firstChunk = chunks.find((chunk) => chunkBelongsToMaterial(chunk, textValue(material.name)))
  const chunkText = compactText(firstChunk?.summary || firstChunk?.content || firstChunk?.text || firstChunk?.markdown, 140)
  if (chunkText) return chunkText
  return '已纳入本次审查材料包，暂无可展示的正文摘要。'
}

function gncResultFromRun(run: SuperAgentRun): Record<string, unknown> {
  return asRecord(run.gnc_review_result)
}

function reportFromRun(run: SuperAgentRun): Record<string, unknown> {
  const reviewPlusReport = asRecord(run.review_plus_result?.report)
  if (Object.keys(reviewPlusReport).length) return reviewPlusReport
  const gnc = gncResultFromRun(run)
  const editorial = asRecord(gnc.editorial_synthesis)
  const chief = asRecord(gnc.chief_decision)
  return {
    conclusion: textValue(editorial.conclusion_draft || chief.rationale || chief.summary),
    summary: textValue(editorial.minutes || gnc.report_markdown),
    findings: asArray(gnc.findings),
    residual_risks: asArray(editorial.residual_risks).length
      ? asArray(editorial.residual_risks)
      : asArray(chief.key_risks),
  }
}

function findingsFromRun(run: SuperAgentRun): Record<string, unknown>[] {
  const report = reportFromRun(run)
  const reportFindings = asArray(report.findings).map(asRecord)
  if (reportFindings.length) return reportFindings
  const reviewPlusFindings = asArray(run.review_plus_result?.findings).map(asRecord)
  if (reviewPlusFindings.length) return reviewPlusFindings
  return asArray(gncResultFromRun(run).findings).map(asRecord)
}

function coverageRowsFromRun(run: SuperAgentRun): Record<string, unknown>[] {
  const matrix = asRecord(run.review_plus_result?.coverage_matrix)
  return asArray(matrix.rows).map(asRecord)
}

function checkItemsFromRun(run: SuperAgentRun): Record<string, unknown>[] {
  return (run.structured_bundle?.check_items || []).map(asRecord)
}

function sourceForFinding(finding: Record<string, unknown>, checkItems: Record<string, unknown>[]): string {
  const explicit = textValue(finding.checklist_source_material_name || finding.source_material_name)
  if (explicit) return explicit
  const checkItemId = textValue(finding.check_item_id)
  const checkItem = checkItems.find((item) => textValue(item.check_item_id) === checkItemId)
  return textValue(checkItem?.source_material_name || checkItem?.source_role || '')
}

function reviewItemFromChiefConclusion(
  item: Record<string, unknown>,
  index: number,
): SuperAgentReviewItemSummary {
  const severity = textValue(item.severity).toLowerCase()
  const status: SuperAgentReviewItemStatus =
    severity === 'critical' || severity === 'major' ? 'failed' : 'attention'
  return {
    id: textValue(item.conclusion_id) || `chief-${index + 1}`,
    status,
    title: textValue(item.title || `工程结论 ${index + 1}`),
    requirement: textValue(item.risk_impact),
    conclusion: compactText(item.description, 220),
    recommendation: compactText(item.recommendation, 220),
    source: (asArray(item.involved_documents).map(textValue).filter(Boolean).join('、')
      || asArray(item.evidence_sources).map(textValue).filter(Boolean).join('；')),
    evidenceRefs: asArray(item.evidence_sources).map(textValue).filter(Boolean),
    sourceQuote: compactText(asArray(item.evidence_sources)[0], 220),
  }
}

function chiefReviewFromReport(report: Record<string, unknown>): SuperAgentReviewItemSummary[] {
  const chief = asRecord(report.chief_comprehensive_review)
  if (!Object.keys(chief).length) return []
  return asArray(chief.engineering_conclusions)
    .map(asRecord)
    .filter((item) => textValue(item.title) || textValue(item.description))
    .slice(0, 8)
    .map(reviewItemFromChiefConclusion)
}

function chiefConclusionSummary(report: Record<string, unknown>): string {
  const chief = asRecord(report.chief_comprehensive_review)
  if (!Object.keys(chief).length) return ''
  return compactText(chief.overall_assessment, 260)
}

function reviewItemFromFinding(
  finding: Record<string, unknown>,
  index: number,
  checkItems: Record<string, unknown>[],
): SuperAgentReviewItemSummary {
  const judgment = textValue(finding.judgment)
  const status = JUDGMENT_TO_STATUS[judgment] || 'attention'
  const checkItemId = textValue(finding.check_item_id)
  const checkItem = checkItems.find((item) => textValue(item.check_item_id) === checkItemId)
  const title = textValue(finding.title || checkItem?.title || checkItem?.requirement_text || `检查项 ${index + 1}`)
  const requirement = textValue(checkItem?.requirement_text || checkItem?.acceptance_criteria || finding.source_quote)
  return {
    id: textValue(finding.finding_id || checkItemId || `RI-${index + 1}`),
    status,
    title,
    requirement: compactText(requirement, 180),
    conclusion: compactText(finding.reasoning || REVIEW_ITEM_STATUS_LABELS[status], 220),
    recommendation: compactText(finding.recommendation, 180),
    source: sourceForFinding(finding, checkItems),
    evidenceRefs: asArray(finding.evidence_refs).map(textValue).filter(Boolean),
    sourceQuote: compactText(
      finding.source_quote || asArray(finding.source_quotes).map(textValue).find(Boolean),
      180,
    ),
  }
}

function reviewItemFromCoverageRow(row: Record<string, unknown>, index: number): SuperAgentReviewItemSummary {
  const rawStatus = textValue(row.judgment)
  const coverageStatus = textValue(row.coverage_status)
  const status = rawStatus === 'satisfied' || coverageStatus === 'closed'
    ? 'passed'
    : coverageStatus === 'missing' || rawStatus === 'not_satisfied'
      ? 'failed'
      : 'attention'
  return {
    id: textValue(row.check_item_id || `CR-${index + 1}`),
    status,
    title: textValue(row.check_item_title || `覆盖检查 ${index + 1}`),
    requirement: compactText(row.source_quote, 180),
    conclusion: compactText(asArray(row.risks).map(textValue).join('；') || REVIEW_ITEM_STATUS_LABELS[status], 220),
    recommendation: status === 'passed' ? '' : '补充任务书依据、报告章节印证或人工确认该检查项不适用。',
    source: textValue(row.checklist_source_material_name || row.checklist_source_role),
    evidenceRefs: [
      ...asArray(row.task_book_evidence_refs),
      ...asArray(row.subject_evidence_refs),
    ].map(textValue).filter(Boolean),
    sourceQuote: compactText(row.source_quote, 180),
  }
}

function skillTraceById(traces: SuperAgentSkillTrace[], skillId: string): SuperAgentSkillTrace | undefined {
  return traces.find((trace) => trace.skill_id === skillId)
}

function skillStatus(traces: SuperAgentSkillTrace[], skillIds: string[] | undefined): WorkflowStepStatus {
  if (!skillIds?.length) return 'pending'
  const matched = skillIds.map((id) => skillTraceById(traces, id)).filter(Boolean) as SuperAgentSkillTrace[]
  if (!matched.length) return 'pending'
  if (matched.some((trace) => trace.status === 'running')) return 'running'
  if (matched.some((trace) => trace.status === 'failed')) return 'failed'
  if (matched.every((trace) => trace.status === 'completed' || trace.status === 'skipped')) return 'completed'
  return 'pending'
}

function resolveActivePipelineSteps(run: SuperAgentRun): SuperAgentPipelineStepKey[] {
  return ['upload', 'identify', 'plan', 'archive', 'launch', 'delegate_review', 'synthesize']
}

function resolveStepStatus(
  stepKey: SuperAgentPipelineStepKey,
  run: SuperAgentRun,
  activeKeys: SuperAgentPipelineStepKey[],
  delegateStatus?: WorkflowStepStatus,
): WorkflowStepStatus {
  const traces = run.skill_traces || []
  const isRunning = run.status === 'running'
  const stepIndex = activeKeys.indexOf(stepKey)
  const directStatus = (key: SuperAgentPipelineStepKey): WorkflowStepStatus => {
    if (key === 'upload' || key === 'identify' || key === 'plan') return 'completed'
    if (key === 'launch') return isRunning || traces.length > 0 || run.route_decision ? 'completed' : 'pending'
    if (key === 'archive') {
      if (run.input_mode !== 'upload' && run.source_review_id) return 'completed'
      const parseStatus = skillStatus(traces, ['bootstrap_review_plus_task', 'structure_materials'])
      if (parseStatus !== 'pending') return parseStatus
      return isRunning ? 'running' : 'pending'
    }
    if (key === 'delegate_review') return delegateStatus || skillStatus(traces, ['run_review_plus', 'run_gnc_review', 'structure_materials'])
    if (key === 'synthesize') {
      if (run.status === 'completed' || run.status === 'limited') return 'completed'
      if (run.status === 'failed') return 'failed'
      if (run.quality_report?.parse_quality_score) return 'running'
      return 'pending'
    }
    return 'pending'
  }

  if (stepKey === 'upload' || stepKey === 'identify' || stepKey === 'plan') return 'completed'
  if (stepKey === 'launch') return isRunning || traces.length > 0 || run.route_decision ? 'completed' : 'pending'
  if (stepKey === 'archive') {
    if (run.input_mode !== 'upload' && run.source_review_id) return 'completed'
    const parseStatus = skillStatus(traces, ['bootstrap_review_plus_task', 'structure_materials'])
    if (parseStatus !== 'pending') return parseStatus
  }
  if (stepKey === 'delegate_review') {
    if (delegateStatus) return delegateStatus
  }
  if (stepKey === 'synthesize') {
    if (run.status === 'completed' || run.status === 'limited') return 'completed'
    if (run.status === 'failed') return 'failed'
    if (isRunning && run.quality_report?.parse_quality_score) return 'running'
    const priorDone = activeKeys.slice(0, -1).every((key) => {
      const status = directStatus(key)
      return status === 'completed' || status === 'skipped'
    })
    return isRunning && priorDone ? 'running' : 'pending'
  }

  const def = SUPER_AGENT_PIPELINE_STEPS.find((item) => item.step_key === stepKey)
  const traceStatus = stepKey === 'delegate_review'
    ? (delegateStatus || skillStatus(traces, def?.skill_ids))
    : skillStatus(traces, def?.skill_ids)
  if (traceStatus !== 'pending') return traceStatus

  if (!isRunning) return 'pending'

  const firstPendingIndex = activeKeys.findIndex((key) => {
    const status = directStatus(key)
    return status === 'pending' || status === 'running'
  })
  if (firstPendingIndex === stepIndex) return 'running'
  return 'pending'
}

function summarizeSkillTrace(trace: SuperAgentSkillTrace): string {
  const output = trace.output_summary || {}
  if (trace.skill_id === 'bootstrap_review_plus_task') {
    const count = Number(output.material_count || 0)
    return count ? `已入库 ${count} 份材料` : '材料入库完成'
  }
  if (trace.skill_id === 'structure_materials') {
    const materialCount = Number(output.material_count || 0)
    const sectionCount = Number(output.section_count || 0)
    if (materialCount || sectionCount) {
      return `解析 ${materialCount} 份材料，${sectionCount} 个章节`
    }
  }
  if (trace.skill_id === 'run_review_plus') {
    const findingCount = Number(output.finding_count || 0)
    return findingCount ? `生成 ${findingCount} 条审查记录` : 'Review-Plus 审查完成'
  }
  if (trace.skill_id === 'run_gnc_review') {
    return String(output.status || 'GNC 审查完成')
  }
  const keys = Object.keys(output)
  if (!keys.length) return '步骤执行完成'
  return keys.slice(0, 3).map((key) => `${key}: ${String(output[key]).slice(0, 40)}`).join(' · ')
}

function buildRouteMessage(run: SuperAgentRun): ProcessingChatMessage | null {
  const decision = run.route_decision
  if (!decision) return null
  const routeLabel = ROUTE_LABELS[decision.route] || decision.route
  return {
    id: 'route-decision',
    role: 'assistant',
    title: '路由决策',
    body: decision.reasons.join('；') || `已选择 ${routeLabel} 路径`,
    status: 'completed',
    chips: [routeLabel, ...(decision.required_tools || []).slice(0, 3)],
  }
}

function buildSkillMessages(traces: SuperAgentSkillTrace[]): ProcessingChatMessage[] {
  return traces.map((trace, index) => {
    const step = SUPER_AGENT_PIPELINE_STEPS.find((item) => item.skill_ids?.includes(trace.skill_id))
    const status: WorkflowStepStatus =
      trace.status === 'completed'
        ? 'completed'
        : trace.status === 'failed'
          ? 'failed'
          : trace.status === 'running'
            ? 'running'
            : 'pending'
    return {
      id: `skill-${trace.skill_id}-${index}`,
      role: 'tool',
      title: step?.label || trace.skill_id,
      body: summarizeSkillTrace(trace),
      status,
      elapsedMs: trace.elapsed_ms,
      chips: trace.warnings?.length ? trace.warnings.slice(0, 2) : undefined,
    }
  })
}

function buildReviewPlusSubMessages(task: ReviewPlusTaskDetail | null): ProcessingChatMessage[] {
  const messages: ProcessingChatMessage[] = []
  if (task?.status === 'running') {
    const stepLabel = resolveReviewPlusRunningStepLabel(task)
    if (stepLabel) {
      messages.push({
        id: 'rp-current-step',
        role: 'tool',
        title: '委托子流程 · 当前阶段',
        body: `${stepLabel}（Review-Plus 委托步骤可能需 20–40 分钟）`,
        status: 'running',
      })
    }
  }
  if (!task?.events?.length) return messages
  const seen = new Set<string>()
  for (const [index, event] of [...task.events].sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0)).entries()) {
    const type = String(event.type || '')
    if (!type || seen.has(type)) continue
    const label = REVIEW_PLUS_EVENT_LABELS[type]
    if (!label) continue
    seen.add(type)
    messages.push({
      id: `rp-event-${type}-${index}`,
      role: 'tool',
      title: `委托子流程 · ${label}`,
      body: String((event.payload as Record<string, unknown> | undefined)?.summary || ''),
      status: type.includes('failed') ? 'failed' : 'completed',
      at: String(event.created_at || ''),
    })
  }
  return messages
}

function buildConclusionMessage(run: SuperAgentRun): ProcessingChatMessage | null {
  if (run.status === 'running') return null
  if (run.status === 'failed') {
    return {
      id: 'conclusion-failed',
      role: 'conclusion',
      title: '审查失败',
      body: run.error || '执行过程中发生错误',
      status: 'failed',
    }
  }
  const findingCount = Number(run.review_plus_result?.finding_count || 0)
  const warnings = run.quality_report?.warnings || []
  const route = run.route_decision?.route || run.requested_route
  const routeLabel = ROUTE_LABELS[route] || route
  return {
    id: 'conclusion-done',
    role: 'conclusion',
    title: run.status === 'limited' ? '审查完成（需人工确认）' : '审查完成',
    body: findingCount
      ? `共生成 ${findingCount} 条审查记录，路由：${routeLabel}。`
      : `审查流程已结束，路由：${routeLabel}。`,
    status: run.status === 'limited' ? 'awaiting_confirm' : 'completed',
    chips: warnings.slice(0, 3),
  }
}

export function buildSuperAgentChatMessages(
  run: SuperAgentRun,
  options?: {
    classification?: MaterialClassification | null
    reviewPlusTask?: ReviewPlusTaskDetail | null
  },
): ProcessingChatMessage[] {
  const messages: ProcessingChatMessage[] = [
    {
      id: 'kickoff',
      role: 'system',
      title: '审查任务已启动',
      body: run.objective || '正在解析材料并执行审查流程…',
      status: run.status === 'running' ? 'running' : 'completed',
    },
  ]

  if (options?.classification) {
    messages.push({
      id: 'classification',
      role: 'assistant',
      title: '材料识别结果',
      body: `${options.classification.doc_type} · ${options.classification.domain}`,
      status: 'completed',
      chips: [options.classification.recommended_route, options.classification.reason].filter(Boolean),
    })
  }

  messages.push(...buildSkillMessages(run.skill_traces || []))

  const routeMessage = buildRouteMessage(run)
  if (routeMessage) {
    const bootstrapIndex = messages.findIndex((item) => item.id.startsWith('skill-bootstrap_review_plus_task'))
    if (bootstrapIndex >= 0) {
      messages.splice(bootstrapIndex + 1, 0, routeMessage)
    } else {
      const kickoffIndex = messages.findIndex((item) => item.id === 'kickoff')
      messages.splice(kickoffIndex + 1, 0, routeMessage)
    }
  }

  if (run.status === 'running') {
    const parallelFlow = buildSuperAgentParallelFlow(run, options?.reviewPlusTask)
    messages.push({
      id: 'parallel-dispatch',
      role: 'assistant',
      title: '正在分派专项审查',
      body: parallelFlow.lanes.map((lane) => `${lane.title}（${STEP_STATUS_LABELS[lane.status]}）`).join('；'),
      status: parallelFlow.dispatch.status,
      chips: ['并行子任务', `${parallelFlow.lanes.length} 个子任务`],
    })
    parallelFlow.lanes.forEach((lane) => {
      const runningNode = lane.nodes.find((node) => node.status === 'running')
      const failedNode = lane.nodes.find((node) => node.status === 'failed')
      const currentNode = failedNode || runningNode || [...lane.nodes].reverse().find((node) => node.status === 'completed') || lane.nodes[0]
      messages.push({
        id: `parallel-lane-${lane.id}`,
        role: 'tool',
        title: lane.title,
        body: currentNode ? `${currentNode.label}：${currentNode.subtitle}` : lane.subtitle,
        status: lane.status,
        chips: ['并行分支', lane.subtitle],
      })
    })
    messages.push({
      id: 'parallel-merge',
      role: 'assistant',
      title: '等待汇合总结',
      body: '所有并行子任务返回后，将进入综合结论生成。',
      status: parallelFlow.merge.status,
      chips: ['汇合总结', `${parallelFlow.lanes.filter((lane) => lane.status === 'completed').length}/${parallelFlow.lanes.length} 已返回`],
    })
  }

  if (run.status === 'running' && options?.reviewPlusTask) {
    messages.push(...buildReviewPlusSubMessages(options.reviewPlusTask))
  }

  const conclusion = buildConclusionMessage(run)
  if (conclusion) messages.push(conclusion)

  return messages
}

function flowSubtitle(value: unknown): string {
  const text = compactText(value, FLOW_SUBTITLE_MAX)
  if (!text) return ''
  if (/^[\{\[]/.test(text) || /\bexecution_mode_summary\b/i.test(text)) return ''
  return text
}

function subFlowNodeId(mainKey: SuperAgentMainFlowStepKey, subKey: string): string {
  return `node_sub_${mainKey}_${subKey}`
}

export function resolveDefaultExpandedMainNodeIds(run: SuperAgentRun): string[] {
  return []
}

export function countMainFlowStepNodes(graph: WorkflowGraph): number {
  return graph.nodes.filter((node) => node.node_type === 'step').length
}

interface SubFlowNodeSpec {
  subKey: string
  label: string
  subtitle: string
  status: WorkflowStepStatus
  badge?: string
}

export function resolveReviewExecutionMode(run: SuperAgentRun): ReviewExecutionMode {
  const primaryPath = smartPrimaryPath(run)
  if (primaryPath === 'structure_only' || hasRoute(run, ['structure_only'])) return 'structure_only'
  if (primaryPath === 'hybrid' || hasRoute(run, ['hybrid'])) return 'hybrid'
  if (isSmartCommitteeRun(run)) return 'smart_committee'
  if (hasRoute(run, ['gnc_review', 'gnc_review_only']) || hasTrace(run, 'run_gnc_review')) return 'gnc'
  return 'review_plus'
}

function resolveReviewExecutionRoute(run: SuperAgentRun): 'smart_committee' | 'review_plus' | 'gnc' {
  const mode = resolveReviewExecutionMode(run)
  if (mode === 'smart_committee') return 'smart_committee'
  if (mode === 'gnc') return 'gnc'
  return 'review_plus'
}

function mapTaskBoardStatus(status: string): WorkflowStepStatus {
  if (status === 'completed') return 'completed'
  if (status === 'running') return 'running'
  if (status === 'failed') return 'failed'
  if (status === 'blocked') return 'blocked'
  if (status === 'skipped') return 'skipped'
  if (status === 'limited') return 'awaiting_confirm'
  return 'pending'
}

function sanitizeSubFlowKey(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/g, '_').replace(/^_+|_+$/g, '') || 'task'
}

interface ExpertTaskSource {
  taskId: string
  title: string
  status: WorkflowStepStatus
  executionMode: string
  specialist?: string
  objective?: string
  inputSummary?: string
  evidenceSummary?: string
  findings: string[]
  findingCount: number
  maxSeverity: ReviewSeverityLevel
  warnings: string[]
  fallbackReason?: string
}

const SMART_COMMITTEE_EXCLUDED_TASK_KINDS = new Set(['format_gate', 'arbiter_summary'])
const SMART_COMMITTEE_EXCLUDED_AGENT_IDS = new Set(['smart_arbiter'])

function isSmartCommitteeExpertLaneRecord(record: Record<string, unknown>): boolean {
  const kind = String(record.kind || '')
  if (SMART_COMMITTEE_EXCLUDED_TASK_KINDS.has(kind)) return false
  const agentId = String(record.specialist_id || record.agent_id || '')
  if (SMART_COMMITTEE_EXCLUDED_AGENT_IDS.has(agentId)) return false
  const title = String(record.title || '')
  if (title.includes('总师') || title === '委员会汇总仲裁') return false
  return true
}

function enrichExpertTasksFromSpecialistReviews(
  tasks: ExpertTaskSource[],
  run: SuperAgentRun,
): ExpertTaskSource[] {
  const reviews = asArray(asRecord(run.review_plus_result).specialist_reviews).map((item) => asRecord(item))
  if (!reviews.length) return tasks

  return tasks.map((task) => {
    if (task.findingCount > 0) return task
    const match = reviews.find((review) => {
      const agentId = String(review.agent_id || '')
      const agentName = String(review.agent_name || '')
      const haystacks = [task.taskId, task.specialist || '', task.title]
      return (
        (agentId && haystacks.some((value) => value.includes(agentId)))
        || (agentName && task.title.includes(agentName))
      )
    })
    if (!match) return task

    const findings = asArray(match.findings)
    const findingCount = Number(match.finding_count || 0) || findings.length
    if (findingCount <= 0) return task

    let maxSeverity: ReviewSeverityLevel = 'none'
    findings.forEach((item) => {
      const record = typeof item === 'object' && item ? asRecord(item) : { title: String(item) }
      maxSeverity = mergeReviewSeverity(
        maxSeverity,
        normalizeReviewSeverity(record.severity || record.level || record.priority),
      )
    })
    if (maxSeverity === 'none') maxSeverity = 'minor'

    return {
      ...task,
      findingCount,
      maxSeverity,
      findings: task.findings.length
        ? task.findings
        : collectFindingLines(findings).slice(0, 6),
    }
  })
}

function collectExpertTaskSources(
  run: SuperAgentRun,
  classification?: MaterialClassification | null,
): ExpertTaskSource[] {
  const resolvedClassification = classification || run.classification
  const tasks = resolveSmartTaskBoardTasks(run, resolvedClassification)
  if (tasks.length) {
    return enrichExpertTasksFromSpecialistReviews(
      tasks.filter((task) => isSmartCommitteeExpertLaneRecord(task)).map((task, index) => {
      const output = asRecord(task.output_summary)
      const nested = asRecord(output.review)
      const { findingCount, maxSeverity } = countExpertFindings(task, output, nested)
      const executionMode = String(
        output.execution_mode
        || nested.execution_mode
        || asRecord(nested.summary).execution_mode
        || task.execution_mode
        || 'unknown',
      )
      return {
        taskId: String(task.task_id || task.specialist_id || task.agent_id || `task_${index}`),
        title: String(task.title || task.specialist_id || task.agent_id || '专家 Agent'),
        status: mapTaskBoardStatus(String(task.status || 'pending')),
        executionMode,
        specialist: String(task.specialist || task.specialist_id || task.agent_id || task.title || ''),
        objective: String(task.objective || task.title || ''),
        inputSummary: formatExpertInputSummary(task, run, output, nested),
        evidenceSummary: compactText(task.evidence_summary || output.evidence_summary || nested.evidence_summary, 180),
        findings: collectFindingLines(
          task.findings,
          output.findings,
          nested.findings,
          nested.review ? asRecord(nested.review).findings : [],
          output.review ? asRecord(output.review).findings : [],
        ).slice(0, 6),
        findingCount,
        maxSeverity,
        warnings: filterBusinessLines([
          ...asArray(task.warnings).map((item) => String(item)),
          ...asArray(output.warnings).map((item) => String(item)),
          ...asArray(nested.warnings).map((item) => String(item)),
        ]).slice(0, 6),
        fallbackReason: String(
          output.fallback_reason
          || nested.fallback_reason
          || output.harness_unavailable_reason
          || nested.harness_unavailable_reason
          || '',
        ),
      }
    }),
      run,
    )
  }

  const smartPlan = smartReviewPlanRecord(run)
  const planSpecs = asArray(smartPlan.task_specs).map((item) => asRecord(item))
  const adaptive = resolveAdaptiveRouterDiagnostics(resolvedClassification)
  const adaptiveSpecs = asArray(adaptive.payload?.task_specs).map((item) => asRecord(item))
  const taskSpecs = (planSpecs.length ? planSpecs : adaptiveSpecs).filter((spec) => (
    isSmartCommitteeExpertLaneRecord(spec)
  ))
  if (taskSpecs.length) {
    const committeeStatus = traceNodeStatus(run, 'smart_review_committee')
    const defaultStatus: WorkflowStepStatus = committeeStatus === 'completed'
      ? 'completed'
      : committeeStatus === 'running'
        ? 'running'
        : 'pending'
    return enrichExpertTasksFromSpecialistReviews(
      taskSpecs.map((spec, index) => ({
      taskId: String(spec.task_id || spec.id || `spec_${index}`),
      title: String(spec.title || spec.objective || `专家任务 ${index + 1}`),
      status: defaultStatus,
      executionMode: String(spec.execution_mode || 'planned'),
      specialist: String(spec.specialist || spec.specialist_id || spec.agent_id || spec.title || ''),
      objective: String(spec.objective || spec.title || ''),
      inputSummary: formatExpertInputSummary(spec, run, {}, {}),
      evidenceSummary: compactText(spec.evidence_summary || '', 180),
      findings: [],
      findingCount: 0,
      maxSeverity: 'none' as ReviewSeverityLevel,
      warnings: [],
    })),
      run,
    )
  }

  const specialistModes = resolveSmartCommitteeDiagnostics(run, resolvedClassification).specialistModes
  if (specialistModes.length) {
    return enrichExpertTasksFromSpecialistReviews(
      specialistModes.map((item, index) => ({
      taskId: String(item.agentId || `specialist_${index}`),
      title: item.title,
      status: committeeStatusFromRun(run),
      executionMode: item.executionMode,
      specialist: item.agentId || item.title,
      findings: [],
      findingCount: 0,
      maxSeverity: 'none' as ReviewSeverityLevel,
      warnings: [],
      fallbackReason: item.fallbackReason,
    })),
      run,
    )
  }

  return []
}

function committeeStatusFromRun(run: SuperAgentRun): WorkflowStepStatus {
  const committeeStatus = traceNodeStatus(run, 'smart_review_committee')
  return committeeStatus === 'pending' && hasTrace(run, 'smart_review_committee') ? 'running' : committeeStatus
}

function resolveSmartTaskBoardTasks(
  run: SuperAgentRun,
  classification?: MaterialClassification | null,
): Record<string, unknown>[] {
  const resolvedClassification = classification || run.classification
  const sources = [
    asRecord(asRecord(run.phase_artifacts?.document_review).smart_task_board),
    asRecord(asRecord(run.review_plus_result).smart_task_board),
    asRecord(resolvedClassification?.smart_task_board),
  ]
  for (const board of sources) {
    const tasks = asArray(board.tasks).map((item) => asRecord(item))
    if (tasks.length) return tasks
  }
  return []
}

function resolveFormatGateTaskRecord(
  run: SuperAgentRun,
  classification?: MaterialClassification | null,
): Record<string, unknown> | null {
  const gateTask = resolveSmartTaskBoardTasks(run, classification).find(
    (task) => String(task.kind || '') === 'format_gate',
  )
  if (gateTask) return gateTask

  const smartPlan = smartReviewPlanRecord(run)
  return asArray(smartPlan.task_specs).map((item) => asRecord(item)).find(
    (spec) => String(spec.kind || '') === 'format_gate',
  ) || null
}

function resolveSmartArbiterTaskRecord(
  run: SuperAgentRun,
  classification?: MaterialClassification | null,
): Record<string, unknown> | null {
  const tasks = resolveSmartTaskBoardTasks(run, classification)
  const arbiterTask = tasks.find((task) => {
    const kind = String(task.kind || '')
    const agentId = String(task.specialist_id || task.agent_id || '')
    return kind === 'arbiter_summary' || agentId === 'smart_arbiter'
  })
  if (arbiterTask) return arbiterTask

  const smartPlan = smartReviewPlanRecord(run)
  const planSpec = asArray(smartPlan.task_specs).map((item) => asRecord(item)).find((spec) => {
    const kind = String(spec.kind || '')
    const agentId = String(spec.specialist_id || spec.agent_id || '')
    return kind === 'arbiter_summary' || agentId === 'smart_arbiter'
  })
  return planSpec || null
}

function resolveSmartDispatchPlanPhase(run: SuperAgentRun, expertCount: number): string {
  if (expertCount === 0) return '等待专家选择'
  const smartPlan = smartReviewPlanRecord(run)
  const allSpecs = asArray(smartPlan.task_specs).map((item) => asRecord(item))
  const hasFormatGate = allSpecs.some((spec) => String(spec.kind || '') === 'format_gate')
  const hasChiefPlan = Boolean(smartPlan.chief_plan || smartPlan.chief_review_plan || allSpecs.length)
  if (hasFormatGate) return '格式校验通过'
  if (hasChiefPlan) return '规划完成'
  return '组会调度中'
}

function resolveSmartDispatchSubtitle(run: SuperAgentRun, expertCount: number): string {
  if (expertCount === 0) {
    return flowSubtitle('规划中 · 等待专家选择') || '规划中 · 等待专家选择'
  }
  const phase = resolveSmartDispatchPlanPhase(run, expertCount)
  return flowSubtitle(`已选 ${expertCount} 位专家 · ${phase}`) || `已选 ${expertCount} 位专家 · ${phase}`
}

function resolveSmartDispatchStatus(
  run: SuperAgentRun,
  expertTasks: ExpertTaskSource[],
  laneStatuses: WorkflowStepStatus[],
): WorkflowStepStatus {
  const expertCount = expertTasks.length
  const committeeStatus = committeeStatusFromRun(run)
  const smartPlan = smartReviewPlanRecord(run)
  const hasPlan = Boolean(
    asArray(smartPlan.task_specs).length
    || smartPlan.chief_plan
    || smartPlan.chief_review_plan,
  )

  if (expertCount === 0) {
    if (committeeStatus === 'running' || hasTrace(run, 'smart_review_committee')) return 'running'
    if (hasPlan) return 'completed'
    return 'pending'
  }

  if (committeeStatus === 'running' && !laneStatuses.every(isSmartDependencyTerminal)) {
    return 'running'
  }

  if (laneStatuses.some((status) => status === 'failed')) return 'failed'
  if (hasPlan || laneStatuses.length) return 'completed'
  return committeeStatus
}

function resolveSmartCommitteeMergeStatus(
  run: SuperAgentRun,
  laneStatuses: WorkflowStepStatus[],
  classification?: MaterialClassification | null,
): WorkflowStepStatus {
  if (run.status === 'completed' || run.status === 'limited') return 'completed'
  if (run.status === 'failed') return 'failed'

  const arbiterTask = resolveSmartArbiterTaskRecord(run, classification)
  if (arbiterTask) {
    const arbiterStatus = mapTaskBoardStatus(String(arbiterTask.status || 'pending'))
    if (arbiterStatus !== 'pending') return arbiterStatus
  }

  const review = asRecord(run.review_plus_result)
  if (Object.keys(asRecord(review.arbiter_summary)).length) return 'completed'

  return resolveMergeStatus(run, laneStatuses)
}

export function buildMainProcessNodes(
  run: SuperAgentRun,
  options?: {
    classification?: MaterialClassification | null
    reviewPlusTask?: ReviewPlusTaskDetail | null
    pauseContext?: SuperAgentRunPauseContext
  },
): MainProcessNodeSpec[] {
  const pauseContext = options?.pauseContext ?? 'active'
  return SUPER_AGENT_MAIN_FLOW_STEPS.map((mainDef) => {
    const subFlow = mainDef.expandable
      ? buildSubFlowForMain(mainDef.stepKey, run, options)
      : []
    const status = applyRunPauseToStepStatus(
      resolveMainFlowStepStatus(mainDef.stepKey, run, subFlow, options),
      pauseContext,
    )
    return {
      stepKey: mainDef.stepKey,
      nodeId: mainDef.nodeId,
      label: mainDef.label,
      subtitle: resolveMainFlowSubtitle(mainDef.stepKey, run, subFlow),
      status,
      expandable: mainDef.expandable,
      artifactKind: mainDef.artifactKind,
    }
  })
}

export function buildSubProcessNodes(
  run: SuperAgentRun,
  parentNodeId: string,
  options?: {
    classification?: MaterialClassification | null
    reviewPlusTask?: ReviewPlusTaskDetail | null
  },
): SubProcessNodeSpec[] {
  const mainDef = SUPER_AGENT_MAIN_FLOW_STEPS.find((step) => step.nodeId === parentNodeId)
  if (!mainDef?.expandable) return []
  return buildSubFlowForMain(mainDef.stepKey, run, options).map((sub) => ({
    subKey: sub.subKey,
    nodeId: subFlowNodeId(mainDef.stepKey, sub.subKey),
    parentNodeId: mainDef.nodeId,
    label: sub.label,
    subtitle: sub.subtitle,
    status: sub.status,
    badge: sub.badge,
  }))
}

export function buildExpandedSubprocess(
  run: SuperAgentRun,
  expandedNodeIds: ReadonlySet<string>,
  options?: {
    classification?: MaterialClassification | null
    reviewPlusTask?: ReviewPlusTaskDetail | null
  },
): SubProcessNodeSpec[] {
  return SUPER_AGENT_MAIN_FLOW_STEPS.flatMap((mainDef) => {
    if (!mainDef.expandable || !expandedNodeIds.has(mainDef.nodeId)) return []
    return buildSubProcessNodes(run, mainDef.nodeId, options)
  })
}

function buildIdentifySubFlow(run: SuperAgentRun, classification?: MaterialClassification | null): SubFlowNodeSpec[] {
  const adaptive = resolveAdaptiveRouterDiagnostics(classification || run.classification)
  const roles = classification?.material_roles || run.classification?.material_roles || []
  const roleSummary = roles.length
    ? `${roles.length} 份材料已识别角色`
    : '等待材料角色识别'
  const domainLabel = adaptive.visible
    ? adaptive.domainLabel
    : compactText(classification?.domain || run.classification?.domain, 24) || '领域待识别'
  const routeLabel = run.route_decision
    ? ROUTE_LABELS[run.route_decision.route] || run.route_decision.route
    : adaptive.routeLabel || '路由待生成'
  const guardrailDone = adaptive.hasGuardrailCorrections || Boolean(run.route_decision)
  const userConfirmed = Boolean(run.route_decision) || Boolean(classification?.user_overrides?.route)
  return [
    {
      subKey: 'material_role',
      label: '材料角色识别',
      subtitle: flowSubtitle(roleSummary) || '识别审查规则、任务书与被审材料角色',
      status: roles.length || run.route_decision ? 'completed' : run.status === 'running' ? 'running' : 'pending',
    },
    {
      subKey: 'domain',
      label: '领域识别',
      subtitle: flowSubtitle(domainLabel) || '判定型号领域与审查场景',
      status: classification?.domain || adaptive.visible ? 'completed' : 'pending',
    },
    {
      subKey: 'route_suggest',
      label: '路由建议',
      subtitle: flowSubtitle(routeLabel) || '生成推荐审查路径',
      status: run.route_decision ? 'completed' : run.status === 'running' ? 'running' : 'pending',
    },
    {
      subKey: 'guardrail',
      label: 'Guardrail 校验',
      subtitle: adaptive.hasGuardrailCorrections
        ? flowSubtitle(`已校正 ${adaptive.guardrailCorrections.length} 项`)
        : '策略护栏与能力边界校验',
      status: guardrailDone ? 'completed' : 'pending',
    },
    {
      subKey: 'user_confirm',
      label: '用户确认/覆盖',
      subtitle: userConfirmed ? '路由已确认或覆盖' : '等待用户确认路由',
      status: userConfirmed ? 'completed' : run.status === 'limited' ? 'awaiting_confirm' : 'pending',
    },
  ]
}

function buildParseSubFlow(run: SuperAgentRun): SubFlowNodeSpec[] {
  const bootstrapStatus = traceNodeStatus(run, 'bootstrap_review_plus_task')
  const stats = run.structured_bundle?.stats || {}
  const materialCount = Number(stats.material_count || run.materials?.length || 0)
  const parseQuality = run.quality_report?.parse_quality_score
  const parserLabel = compactText(
    run.classification?.parse_plan?.default_parser_type
      || run.classification?.parse_plan?.files?.[0]?.parser_type
      || '',
    24,
  )
  return [
    {
      subKey: 'text_extract',
      label: '文本抽取',
      subtitle: parserLabel
        ? flowSubtitle(`已选 ${parserLabel}`)
        : materialCount
          ? flowSubtitle(`已处理 ${materialCount} 份材料`)
          : '抽取正文与基础元数据',
      status: materialCount || parserLabel ? 'completed' : bootstrapStatus,
    },
    {
      subKey: 'document_ir',
      label: '文档 IR',
      subtitle: flowSubtitle(run.source_review_id ? `载体 ${run.source_review_id}` : '构建文档中间表示'),
      status: bootstrapStatus === 'completed' || run.source_review_id ? 'completed' : bootstrapStatus,
    },
    {
      subKey: 'blocks_tables_pages',
      label: '块/表/页码识别',
      subtitle: Number(stats.section_count || 0)
        ? flowSubtitle(`${stats.section_count} 个章节块`)
        : '识别文本块、表格与页码',
      status: Number(stats.section_count || 0) > 0 ? 'completed' : bootstrapStatus,
    },
    {
      subKey: 'parse_quality_summary',
      label: '解析质量摘要',
      subtitle: parseQuality != null && parseQuality > 0
        ? flowSubtitle(`解析质量 ${Math.round(parseQuality * 100)}%`)
        : '评估解析完整度与降级',
      status: parseQuality != null && parseQuality > 0 ? 'completed' : 'pending',
    },
  ]
}

function buildStructureSubFlow(run: SuperAgentRun): SubFlowNodeSpec[] {
  const structureStatus = traceNodeStatus(run, 'structure_materials')
  const stats = run.structured_bundle?.stats || {}
  const hasStats = Number(stats.material_count || 0) > 0 || Number(stats.section_count || 0) > 0
  const effectiveStructureStatus = structureStatus === 'pending' && hasStats ? 'completed' : structureStatus
  const checkItemCount = Number(stats.check_item_count || run.structured_bundle?.check_items?.length || 0)
  return [
    {
      subKey: 'section_tree',
      label: '章节树',
      subtitle: Number(stats.section_count || 0)
        ? flowSubtitle(`${stats.section_count} 个章节`)
        : '构建章节层级',
      status: Number(stats.section_count || 0) > 0 ? 'completed' : effectiveStructureStatus,
    },
    {
      subKey: 'evidence_pool',
      label: '证据池',
      subtitle: Number(stats.evidence_count || 0)
        ? flowSubtitle(`${stats.evidence_count} 条证据`)
        : '汇聚可引用证据片段',
      status: Number(stats.evidence_count || 0) > 0 ? 'completed' : effectiveStructureStatus,
    },
    {
      subKey: 'check_items',
      label: '合成检查项',
      subtitle: checkItemCount ? flowSubtitle(`${checkItemCount} 个检查项`) : '合成可执行检查项',
      status: checkItemCount > 0 ? 'completed' : effectiveStructureStatus,
    },
    {
      subKey: 'reviewability',
      label: '可审查性判断',
      subtitle: hasStats ? '结构化结果可用于审查' : '判断材料是否满足审查前置',
      status: hasStats ? 'completed' : effectiveStructureStatus,
    },
  ]
}

function buildSmartCommitteeReviewSubFlow(run: SuperAgentRun): SubFlowNodeSpec[] {
  return processModelToSubFlow(buildSmartReviewProcessModelFromRun(run))
}

function buildReviewPlusReviewSubFlow(
  run: SuperAgentRun,
  task?: ReviewPlusTaskDetail | null,
): SubFlowNodeSpec[] {
  return processModelToSubFlow(buildReviewPlusProcessModelFromRun(run, task))
}

function buildGncReviewSubFlow(run: SuperAgentRun): SubFlowNodeSpec[] {
  return processModelToSubFlow(buildGncReviewProcessModelFromRun(run))
}

function buildReviewSubFlow(
  run: SuperAgentRun,
  task?: ReviewPlusTaskDetail | null,
): SubFlowNodeSpec[] {
  const route = resolveReviewExecutionRoute(run)
  if (route === 'smart_committee') return buildSmartCommitteeReviewSubFlow(run)
  if (route === 'gnc') return buildGncReviewSubFlow(run)
  return buildReviewPlusReviewSubFlow(run, task)
}

function buildArbitrationSubFlow(run: SuperAgentRun): SubFlowNodeSpec[] {
  const findingCount = Number(run.review_plus_result?.finding_count || 0)
  const committeeStatus = traceNodeStatus(run, 'smart_review_committee')
  const mergeStatus: WorkflowStepStatus = findingCount > 0 || committeeStatus === 'completed'
    ? 'completed'
    : committeeStatus === 'running'
      ? 'running'
      : 'pending'
  return [
    {
      subKey: 'dedupe',
      label: '发现去重',
      subtitle: findingCount ? flowSubtitle(`${findingCount} 条待汇总`) : '合并重复发现',
      status: mergeStatus,
    },
    {
      subKey: 'conflict',
      label: '冲突处理',
      subtitle: '处理专家意见冲突',
      status: mergeStatus,
    },
    {
      subKey: 'adopt',
      label: '采纳/降级/驳回',
      subtitle: '按证据与策略裁定',
      status: mergeStatus,
    },
    {
      subKey: 'final_list',
      label: '最终清单',
      subtitle: findingCount ? flowSubtitle(`输出 ${findingCount} 条问题`) : '生成最终清单',
      status: run.status === 'completed' || run.status === 'limited' ? 'completed' : mergeStatus,
    },
  ]
}

function buildQualitySubFlow(run: SuperAgentRun): SubFlowNodeSpec[] {
  const smartDiag = resolveSmartCommitteeDiagnostics(run, run.classification)
  const evidenceScore = run.quality_report?.evidence_quality_score
  const hasReport = run.status === 'completed' || run.status === 'limited'
  const qualityStatus: WorkflowStepStatus = run.status === 'failed'
    ? 'failed'
    : hasReport
      ? 'completed'
      : run.quality_report?.parse_quality_score
        ? 'running'
        : 'pending'
  return [
    {
      subKey: 'coverage',
      label: '证据覆盖率',
      subtitle: smartDiag.citationCoverage != null
        ? flowSubtitle(`引用覆盖 ${Math.round(smartDiag.citationCoverage * 100)}%`)
        : evidenceScore != null
          ? flowSubtitle(`证据质量 ${Math.round(evidenceScore * 100)}%`)
          : '统计证据引用覆盖',
      status: qualityStatus,
    },
    {
      subKey: 'citation_integrity',
      label: '引用完整性',
      subtitle: '检查引用链与证据锚点',
      status: qualityStatus,
    },
    {
      subKey: 'execution_diagnostics',
      label: '执行模式诊断',
      subtitle: flowSubtitle(smartDiag.executionModeLabel) || '汇总执行模式与降级',
      status: qualityStatus,
    },
    {
      subKey: 'report',
      label: '报告生成',
      subtitle: hasReport ? '审查报告可导出' : '等待报告生成',
      status: hasReport ? 'completed' : qualityStatus,
    },
  ]
}

function buildSubFlowForMain(
  mainKey: SuperAgentMainFlowStepKey,
  run: SuperAgentRun,
  options?: { classification?: MaterialClassification | null; reviewPlusTask?: ReviewPlusTaskDetail | null },
): SubFlowNodeSpec[] {
  switch (mainKey) {
    case 'identify':
      return buildIdentifySubFlow(run, options?.classification)
    case 'parse':
      return buildParseSubFlow(run)
    case 'structure':
      return buildStructureSubFlow(run)
    case 'review':
      return buildReviewSubFlow(run, options?.reviewPlusTask)
    case 'arbitration':
      return buildArbitrationSubFlow(run)
    case 'quality':
      return buildQualitySubFlow(run)
    default:
      return []
  }
}

function resolveMainFlowStepStatus(
  mainKey: SuperAgentMainFlowStepKey,
  run: SuperAgentRun,
  subFlow: SubFlowNodeSpec[],
  options?: { reviewPlusTask?: ReviewPlusTaskDetail | null },
): WorkflowStepStatus {
  if (subFlow.length) return aggregateLaneStatus(subFlow.map((node) => node.status)) || 'pending'
  switch (mainKey) {
    case 'upload':
      return 'completed'
    case 'identify':
      return run.route_decision ? 'completed' : run.status === 'running' ? 'running' : 'pending'
    case 'parse':
      return resolveStepStatus('archive', run, resolveActivePipelineSteps(run))
    case 'structure':
      return traceNodeStatus(run, 'structure_materials')
    case 'review': {
      const route = resolveReviewExecutionRoute(run)
      if (route === 'smart_committee') return traceNodeStatus(run, 'smart_review_committee')
      if (route === 'gnc') return traceNodeStatus(run, 'run_gnc_review')
      return reviewPlusStepStatus(options?.reviewPlusTask, 'item_review')
        || traceNodeStatus(run, 'run_review_plus')
    }
    case 'arbitration':
      return run.status === 'completed' || run.status === 'limited'
        ? 'completed'
        : traceNodeStatus(run, 'smart_review_committee')
    case 'quality':
      if (run.status === 'completed' || run.status === 'limited') return 'completed'
      if (run.status === 'failed') return 'failed'
      return run.quality_report?.parse_quality_score ? 'running' : 'pending'
    default:
      return 'pending'
  }
}

function resolveMainFlowSubtitle(
  mainKey: SuperAgentMainFlowStepKey,
  run: SuperAgentRun,
  subFlow: SubFlowNodeSpec[],
): string {
  const running = subFlow.find((node) => node.status === 'running')
  if (running?.subtitle) return running.subtitle
  const lastDone = [...subFlow].reverse().find((node) => node.status === 'completed')
  if (lastDone?.subtitle) return lastDone.subtitle
  switch (mainKey) {
    case 'upload': {
      const count = run.materials?.length || 0
      return flowSubtitle(count ? `${count} 份材料已上传` : '读取材料元数据') || '材料已接收'
    }
    case 'identify':
      return flowSubtitle(run.route_decision?.reasons?.[0] || ROUTE_LABELS[run.route_decision?.route || ''])
        || '轻量分类与路由'
    case 'parse': {
      const count = Number(run.structured_bundle?.stats?.material_count || run.materials?.length || 0)
      return flowSubtitle(count ? `已解析 ${count} 份材料` : '文档解析与 IR 构建') || '文档解析'
    }
    case 'structure': {
      const stats = run.structured_bundle?.stats || {}
      return flowSubtitle(
        Number(stats.section_count || 0)
          ? `${stats.section_count} 章 · ${stats.evidence_count || 0} 证据`
          : '章节树与证据池',
      ) || '材料结构化'
    }
    case 'review': {
      const route = resolveReviewExecutionRoute(run)
      if (route === 'smart_committee') return flowSubtitle('智能专家组审查') || '审查执行'
      if (route === 'gnc') return flowSubtitle('GNC 专项审查') || '审查执行'
      return flowSubtitle('符合性专家审查') || '审查执行'
    }
    case 'arbitration':
      return flowSubtitle(
        Number(run.review_plus_result?.finding_count || 0)
          ? `${run.review_plus_result?.finding_count} 条发现待汇总`
          : '汇总各分支审查结论',
      ) || '仲裁汇总'
    case 'quality':
      return run.status === 'completed' || run.status === 'limited'
        ? flowSubtitle('质量评估与报告已完成') || '质量评估完成'
        : flowSubtitle('五维质量评分与报告') || '质量评估'
    default:
      return ''
  }
}

function resolveReviewPrepareStatus(
  run: SuperAgentRun,
  pauseContext: SuperAgentRunPauseContext = 'active',
): WorkflowStepStatus {
  const activeKeys = resolveActivePipelineSteps(run)
  const statuses = (['upload', 'identify', 'plan', 'archive'] as SuperAgentPipelineStepKey[]).map((key) =>
    applyRunPauseToStepStatus(resolveStepStatus(key, run, activeKeys), pauseContext),
  )
  return aggregateLaneStatus(statuses)
}

function buildReviewProcessCanvasMainBefore(
  run: SuperAgentRun,
  pauseContext: SuperAgentRunPauseContext = 'active',
): SuperAgentParallelFlowNode[] {
  const stats = run.structured_bundle?.stats || {}
  const materialCount = Number(stats.material_count || run.materials?.length || 0)
  const sectionCount = Number(stats.section_count || 0)
  const routeLabel = run.route_decision
    ? ROUTE_LABELS[run.route_decision.route] || run.route_decision.route
    : '待判定'
  const prepStatus = resolveReviewPrepareStatus(run, pauseContext)
  const subtitle = prepStatus === 'completed'
    ? flowSubtitle(`${materialCount} 份材料 · ${sectionCount} 章 · ${routeLabel}`) || '审查材料已就绪'
    : flowSubtitle('完成材料整理与结构化后进入专项审查') || '审查准备中'
  return [{
    id: 'launch',
    label: '审查准备',
    subtitle,
    status: prepStatus,
    badge: '主链',
    processItemId: 'review_prepare',
  }]
}

function buildSmartCommitteeBusinessLanes(run: SuperAgentRun): SuperAgentParallelFlowLane[] {
  const expertTasks = collectExpertTaskSources(run, run.classification)
  if (!expertTasks.length) return []

  const sources = expertTasks.map((task, index) => {
    const outcome = resolveReviewOutcomeStatus(task.status, task.findingCount, task.maxSeverity)
    return {
      id: sanitizeSubFlowKey(task.taskId) || `lane_${index}`,
      title: compactText(task.title, 40) || `审查组 ${index + 1}`,
      subtitle: flowSubtitle(outcome.outcomeLabel) || flowSubtitle(task.objective || task.specialist) || '专项审查',
      status: outcome.displayStatus,
    }
  })

  return sources.map((source) => {
    const laneStatus = source.status || committeeStatusFromRun(run)
    const nodes: SuperAgentParallelFlowNode[] = [
      {
        id: `${source.id}-review`,
        label: source.title,
        subtitle: source.subtitle,
        status: laneStatus,
        processItemId: `lane-${source.id}`,
      },
    ]
    return finalizeSequentialLane({
      id: source.id,
      title: source.title,
      subtitle: source.subtitle,
      status: aggregateLaneStatus(nodes.map((node) => node.status)),
      nodes,
      processItemId: `lane-${source.id}`,
    })
  })
}

function materialCountReady(run: SuperAgentRun): boolean {
  const stats = run.structured_bundle?.stats || {}
  return Number(stats.material_count || run.materials?.length || 0) > 0
}

export function resolveLaneDeepParallelTasks(
  nodeId: string,
  run: SuperAgentRun,
  options?: { classification?: MaterialClassification | null; reviewPlusTask?: ReviewPlusTaskDetail | null },
): LaneDeepParallelTask[] {
  const laneStepMatch = nodeId.match(/^node_lane_(.+)_step_(\d+)$/)
  if (!laneStepMatch) return []
  const stepIndex = Number(laneStepMatch[2])
  const laneId = laneStepMatch[1]

  if (laneId === 'gnc') {
    const model = buildGncReviewProcessModelFromRun(run)
    return resolveProcessStageDeepTasks('gnc', stepIndex, model)
  }

  if (laneId === 'review-plus') {
    const model = buildReviewPlusProcessModelFromRun(run, options?.reviewPlusTask)
    const itemReviewIndex = findProcessStageIndexByKey(model, 'item_review')
    if (stepIndex === itemReviewIndex) {
      return resolveProcessStageDeepTasks('review-plus', stepIndex, model)
    }
    const stage = model.stages[stepIndex]
    if (stage?.steps.length > 1) {
      return resolveProcessStageDeepTasks('review-plus', stepIndex, model)
    }
    return []
  }

  const smartModel = buildSmartReviewProcessModelFromRun(run)
  const expertReviewIndex = findProcessStageIndexByKey(smartModel, 'expert_review')
  if (stepIndex === expertReviewIndex) {
    return resolveProcessStageDeepTasks(laneId, stepIndex, smartModel)
  }

  if (stepIndex !== 1) return []

  const laneStatus: WorkflowStepStatus = laneId === 'review-plus' && options?.reviewPlusTask
    ? reviewPlusStepStatus(options.reviewPlusTask, 'item_review')
    : traceNodeStatus(run, 'smart_review_committee')

  return DEFAULT_LANE_DEEP_TASKS.map((task, index) => ({
    id: `${laneId}-${task.id}`,
    label: task.label,
    summary: task.summary,
    status: index === 0
      ? (laneStatus === 'completed' ? 'completed' : laneStatus === 'running' ? 'running' : 'pending')
      : index === 1
        ? (laneStatus === 'completed' ? 'completed' : laneStatus === 'running' ? 'running' : 'pending')
        : (laneStatus === 'completed' ? 'completed' : 'pending'),
  }))
}

function gncCommitteeGroupTeamLeadId(groupKey: string): string {
  return `node_lane_gnc_committee_${groupKey}`
}

function gncCommitteeUnitNodeId(groupKey: string, stageKey: string): string {
  return `${gncCommitteeGroupTeamLeadId(groupKey)}_${stageKey}`
}

function gncCommitteeJoinNodeId(groupKey: string, phaseIndex: number): string {
  return `${gncCommitteeGroupTeamLeadId(groupKey)}_join_${phaseIndex}`
}

function resolveGncCommitteeJoinStatus(unitStatuses: WorkflowStepStatus[]): WorkflowStepStatus {
  if (unitStatuses.some((status) => status === 'failed' || status === 'blocked')) return 'failed'
  if (unitStatuses.some((status) => status === 'running')) return 'running'
  if (unitStatuses.every((status) => status === 'completed')) return 'completed'
  if (unitStatuses.every((status) => status === 'skipped')) return 'skipped'
  return 'pending'
}

function mapGncSubflowStageStatus(status: GncSubflowStageStatus): WorkflowStepStatus {
  if (status === 'completed') return 'completed'
  if (status === 'running') return 'running'
  if (status === 'failed') return 'failed'
  if (status === 'blocked') return 'blocked'
  if (status === 'skipped') return 'skipped'
  if (status === 'not_checked') return 'awaiting_confirm'
  return 'pending'
}

function resolveGncCommitteeGroupTeamLeadStatus(lane: GncSubflowLaneProjection): WorkflowStepStatus {
  if (!lane.enabled) return 'skipped'
  const activeStages = lane.stages.filter((stage) => stage.status !== 'skipped')
  if (!activeStages.length) return 'pending'
  if (activeStages.some((stage) => stage.status === 'failed' || stage.status === 'blocked')) return 'failed'
  if (activeStages.some((stage) => stage.status === 'running')) return 'running'
  if (activeStages.every((stage) => stage.status === 'completed')) return 'completed'
  return 'pending'
}

function appendGncCommitteeNestedFlowNodes(
  run: SuperAgentRun,
  committeeStepId: string,
  laneTeamLeadId: string,
  nextStepId: string | undefined,
  nodes: WorkflowGraphNode[],
  edges: Array<{ edge_id: string; source: string; target: string }>,
): string[] {
  const subflowLanes = buildGncCommitteeSubflowLanes(extractGncCommitteeInput(run))
  if (!subflowLanes.length) return [committeeStepId]

  const exitIds: string[] = []

  subflowLanes.forEach((subLane) => {
    const groupTeamLeadId = gncCommitteeGroupTeamLeadId(subLane.groupKey)
    const teamLeadStatus = resolveGncCommitteeGroupTeamLeadStatus(subLane)
    const teamLeadSubtitle = subLane.enabled
      ? summarizeSubflowLane(subLane)
      : (subLane.skipReason || '本轮未启用')

    nodes.push(emptyWorkflowNode(
      groupTeamLeadId,
      `gnc_committee_${subLane.groupKey}`,
      subLane.groupLabel,
      'team_lead',
      teamLeadStatus,
      {
        subtitle: flowSubtitle(teamLeadSubtitle) || teamLeadSubtitle,
        parent_node_id: laneTeamLeadId,
      },
    ))
    edges.push({
      edge_id: `edge_${committeeStepId}_${groupTeamLeadId}`,
      source: committeeStepId,
      target: groupTeamLeadId,
    })

    const activeStages = subLane.enabled
      ? subLane.stages.filter((stage) => stage.status !== 'skipped')
      : []

    let branchPreviousId = groupTeamLeadId
    if (!activeStages.length) {
      exitIds.push(groupTeamLeadId)
      if (nextStepId) {
        edges.push({
          edge_id: `edge_${groupTeamLeadId}_${nextStepId}`,
          source: groupTeamLeadId,
          target: nextStepId,
        })
      }
      return
    }

    const stageByKey = new Map(activeStages.map((stage) => [stage.stageKey, stage]))
    const phases = getActiveStagesByPhase(subLane.groupKey, activeStages.map((stage) => stage.stageKey))

    phases.forEach((phaseStageKeys, phaseIndex) => {
      const phaseSourceId = branchPreviousId
      const phaseUnitIds: string[] = []
      const phaseUnitStatuses: WorkflowStepStatus[] = []
      const isParallelPhase = phaseStageKeys.length > 1

      phaseStageKeys.forEach((stageKey) => {
        const stage = stageByKey.get(stageKey)
        if (!stage) return

        const unitId = gncCommitteeUnitNodeId(subLane.groupKey, stage.stageKey)
        const unitStatus = mapGncSubflowStageStatus(stage.status)
        phaseUnitStatuses.push(unitStatus)

        const baseSubtitle = stage.findingCount
          ? `${stage.findingCount} 条发现 · ${subflowStageStatusLabel(stage.status)}`
          : (stage.summary || subflowStageStatusLabel(stage.status))
        const unitSubtitle = isParallelPhase
          ? `${baseSubtitle} · 并行`
          : baseSubtitle

        nodes.push(emptyWorkflowNode(
          unitId,
          stage.unitKey,
          stage.stageLabel,
          'agent',
          unitStatus,
          {
            subtitle: flowSubtitle(unitSubtitle) || unitSubtitle,
            parent_node_id: groupTeamLeadId,
          },
        ))
        edges.push({
          edge_id: `edge_${phaseSourceId}_${unitId}`,
          source: phaseSourceId,
          target: unitId,
        })
        phaseUnitIds.push(unitId)
      })

      if (phaseUnitIds.length > 1) {
        const joinId = gncCommitteeJoinNodeId(subLane.groupKey, phaseIndex)
        const joinStatus = resolveGncCommitteeJoinStatus(phaseUnitStatuses)
        nodes.push(emptyWorkflowNode(
          joinId,
          `gnc_committee_${subLane.groupKey}_join_${phaseIndex}`,
          '汇合',
          'merge',
          joinStatus,
          {
            subtitle: '并行阶段汇合',
            parent_node_id: groupTeamLeadId,
          },
        ))
        phaseUnitIds.forEach((unitId) => {
          edges.push({
            edge_id: `edge_${unitId}_${joinId}`,
            source: unitId,
            target: joinId,
          })
        })
        branchPreviousId = joinId
      } else if (phaseUnitIds.length === 1) {
        branchPreviousId = phaseUnitIds[0]
      }
    })

    exitIds.push(branchPreviousId)
    if (nextStepId) {
      edges.push({
        edge_id: `edge_${branchPreviousId}_${nextStepId}`,
        source: branchPreviousId,
        target: nextStepId,
      })
    }
  })

  return exitIds
}

function resolveGncCommitteeCanvasNodeContext(
  nodeId: string,
): SuperAgentFlowNodeContext | null {
  const groupMatch = nodeId.match(/^node_lane_gnc_committee_(ad_group|ac_group)$/)
  if (groupMatch) {
    const label = groupMatch[1] === 'ad_group' ? 'AD 姿态确定' : 'AC 姿态控制'
    return {
      nodeId,
      label,
      subtitle: 'GNC 专家组子流程',
      status: 'pending',
      processItemId: 'lane-gnc',
    }
  }

  const unitMatch = nodeId.match(/^node_lane_gnc_committee_(ad_group|ac_group)_(?!join_)(.+)$/)
  if (unitMatch) {
    const stageKey = unitMatch[2]
    const stageDef = [...AD_SUBFLOW_STAGE_DEFS, ...AC_SUBFLOW_STAGE_DEFS]
      .find((def) => def.stageKey === stageKey)
    return {
      nodeId,
      label: stageDef?.stageLabel || stageKey,
      subtitle: 'GNC 子流程单元',
      status: 'pending',
      processItemId: 'lane-gnc',
    }
  }

  return null
}

function buildGncCommitteeCanvasNodeDetail(
  nodeId: string,
  run: SuperAgentRun,
): SuperAgentFlowNodeDetail | null {
  const lanes = buildGncCommitteeSubflowLanes(extractGncCommitteeInput(run))
  const sections: SuperAgentFlowNodeDetailSection[] = []

  const groupMatch = nodeId.match(/^node_lane_gnc_committee_(ad_group|ac_group)$/)
  if (groupMatch) {
    const groupKey = groupMatch[1] as 'ad_group' | 'ac_group'
    const lane = lanes.find((item) => item.groupKey === groupKey)
    if (!lane) return null

    sections.push({
      kind: 'summary',
      title: '业务摘要',
      lines: filterBusinessLines([
        lane.groupLabel,
        lane.enabled ? summarizeSubflowLane(lane) : (lane.skipReason || '本轮未启用'),
        lane.verdict ? `结论：${lane.verdict}` : '',
      ]),
    })
    if (lane.enabled) {
      sections.push({
        kind: 'review',
        title: '子流程环节',
        lines: lane.stages
          .filter((stage) => stage.status !== 'skipped')
          .map((stage) => {
            const suffix = stage.findingCount ? ` · ${stage.findingCount} 条发现` : ''
            return `${stage.stageLabel}：${subflowStageStatusLabel(stage.status)}${suffix}`
          }),
      })
    }
    return {
      nodeId,
      label: lane.groupLabel,
      status: resolveGncCommitteeGroupTeamLeadStatus(lane),
      nodeLevel: 'sub',
      sections,
    }
  }

  const unitMatch = nodeId.match(/^node_lane_gnc_committee_(ad_group|ac_group)_(?!join_)(.+)$/)
  if (unitMatch) {
    const groupKey = unitMatch[1] as 'ad_group' | 'ac_group'
    const stageKey = unitMatch[2]
    const lane = lanes.find((item) => item.groupKey === groupKey)
    const stage = lane?.stages.find((item) => item.stageKey === stageKey)
    if (!lane || !stage || stage.status === 'skipped') return null

    sections.push({
      kind: 'summary',
      title: '业务摘要',
      lines: filterBusinessLines([
        `${lane.groupLabel} · ${stage.stageLabel}`,
        stage.summary || subflowStageStatusLabel(stage.status),
        stage.findingCount ? `发现 ${stage.findingCount} 条` : '',
      ]),
    })
    if (stage.blockingFlags.length) {
      sections.push({
        kind: 'review',
        title: '阻塞项',
        lines: stage.blockingFlags.slice(0, 6),
      })
    }
    return {
      nodeId,
      label: stage.stageLabel,
      status: mapGncSubflowStageStatus(stage.status),
      nodeLevel: 'sub',
      sections,
    }
  }

  return null
}

function emptyWorkflowNode(
  nodeId: string,
  stepKey: string,
  label: string,
  nodeType: string,
  status: WorkflowStepStatus,
  extras: Partial<WorkflowGraphNode> = {},
): WorkflowGraphNode {
  return {
    node_id: nodeId,
    step_key: stepKey,
    label,
    node_type: nodeType,
    status,
    agent_ids: [],
    agent_run_ids: [],
    blocked_reason: '',
    ...extras,
  } as WorkflowGraphNode
}

export function buildSuperAgentFlowGraph(
  run: SuperAgentRun,
  reviewPlusTask?: ReviewPlusTaskDetail | null,
  pauseContext: SuperAgentRunPauseContext = 'active',
): WorkflowGraph {
  const parallelFlow = buildSuperAgentParallelFlow(run, reviewPlusTask, pauseContext)
  const nodes: WorkflowGraphNode[] = []
  const edges: Array<{ edge_id: string; source: string; target: string }> = []

  REVIEW_PROCESS_CANVAS_MAIN_CHAIN_STEP_KEYS.forEach((stepKey, index) => {
    const parallelNode = parallelFlow.mainBefore.find((item) => item.id === stepKey)
    const def = SUPER_AGENT_PIPELINE_STEPS.find((item) => item.step_key === stepKey)
    nodes.push(emptyWorkflowNode(
      `node_${stepKey}`,
      stepKey,
      parallelNode?.label || def?.label || stepKey,
      'step',
      parallelNode?.status || 'pending',
      {
        subtitle: parallelNode?.subtitle || def?.description || '',
        output_summary: parallelNode?.subtitle || def?.description || '',
        layout_hint: index === 0 ? 'start' : undefined,
      },
    ))
    if (index > 0) {
      const previousKey = REVIEW_PROCESS_CANVAS_MAIN_CHAIN_STEP_KEYS[index - 1]
      edges.push({
        edge_id: `edge_${previousKey}_${stepKey}`,
        source: `node_${previousKey}`,
        target: `node_${stepKey}`,
      })
    }
  })

  const smartCommitteeCanvas = isSmartCommitteeRun(run)
  const formatGateRecord = smartCommitteeCanvas ? resolveFormatGateTaskRecord(run) : null
  const expertTasks = smartCommitteeCanvas ? collectExpertTaskSources(run, run.classification) : []

  const dispatchId = 'node_dispatch'
  nodes.push(emptyWorkflowNode(
    dispatchId,
    'delegate_dispatch',
    parallelFlow.dispatch.label,
    'dispatch',
    parallelFlow.dispatch.status,
    {
      subtitle: smartCommitteeCanvas
        ? parallelFlow.dispatch.subtitle
        : parallelFlow.dispatch.subtitle,
      icon: '🎯',
    },
  ))
  edges.push({
    edge_id: 'edge_launch_dispatch',
    source: 'node_launch',
    target: dispatchId,
  })

  const gateId = 'node_gate_format'
  if (formatGateRecord && smartCommitteeCanvas && parallelFlow.gate) {
    nodes.push(emptyWorkflowNode(
      gateId,
      'format_gate',
      parallelFlow.gate.label,
      'step',
      parallelFlow.gate.status,
      {
        subtitle: parallelFlow.gate.subtitle,
        output_summary: parallelFlow.gate.subtitle,
        icon: '🚧',
      },
    ))
    edges.push({
      edge_id: 'edge_dispatch_gate',
      source: dispatchId,
      target: gateId,
    })
  }

  const mergeId = 'node_merge'
  nodes.push(emptyWorkflowNode(
    mergeId,
    'delegate_merge',
    parallelFlow.merge.label,
    'merge',
    parallelFlow.merge.status,
    {
      subtitle: parallelFlow.merge.subtitle,
    },
  ))

  nodes.push(emptyWorkflowNode(
    'node_synthesize',
    'synthesize',
    parallelFlow.conclusion.label,
    'step',
    parallelFlow.conclusion.status,
    {
      subtitle: parallelFlow.conclusion.subtitle,
      output_summary: parallelFlow.conclusion.subtitle,
      layout_hint: 'end',
    },
  ))
  edges.push({
    edge_id: 'edge_merge_synthesize',
    source: mergeId,
    target: 'node_synthesize',
  })

  const laneEntrySourceId = formatGateRecord && smartCommitteeCanvas ? gateId : dispatchId
  parallelFlow.lanes.forEach((lane) => {
    const laneLabel = lane.title.replace(/^子任务 \d+ · /, '') || lane.title
    const smartSingleAgentLane = smartCommitteeCanvas && lane.nodes.length === 1
    const teamLeadId = `node_lane_${lane.id}`

    if (!smartSingleAgentLane) {
      nodes.push(emptyWorkflowNode(
        teamLeadId,
        `lane_${lane.id}`,
        laneLabel,
        'team_lead',
        lane.status,
        {
          subtitle: lane.subtitle,
          icon: lane.id === 'discovering' ? '⏳' : '📋',
        },
      ))
      edges.push({
        edge_id: `edge_dispatch_lane_${lane.id}`,
        source: dispatchId,
        target: teamLeadId,
      })
    }

    let previousSources: string[] = [smartSingleAgentLane ? laneEntrySourceId : teamLeadId]
    lane.nodes.forEach((stepNode, stepIndex) => {
      const laneKey = sanitizeSubFlowKey(lane.id)
      const expertTask = expertTasks.find((task) => sanitizeSubFlowKey(task.taskId) === laneKey)
      const executionStatus = stepNode.status
      const rawExpertStatus = expertTask?.status ?? stepNode.status
      const outcome = expertTask
        ? resolveReviewOutcomeStatus(executionStatus, expertTask.findingCount, expertTask.maxSeverity)
        : resolveReviewOutcomeStatus(executionStatus, 0, 'none')
      const agentStatus = smartCommitteeCanvas && expertTask ? outcome.displayStatus : executionStatus
      const agentSubtitle = smartCommitteeCanvas && expertTask
        ? (executionStatus !== rawExpertStatus || executionStatus === 'blocked'
          ? stepNode.subtitle
          : (flowSubtitle(outcome.outcomeLabel) || stepNode.subtitle))
        : stepNode.subtitle
      const agentId = `node_lane_${lane.id}_step_${stepIndex}`
      nodes.push(emptyWorkflowNode(
        agentId,
        stepNode.id,
        stepNode.label,
        'agent',
        agentStatus,
        {
          subtitle: agentSubtitle,
          output_summary: agentSubtitle,
          parent_node_id: smartSingleAgentLane ? undefined : teamLeadId,
        },
      ))
      previousSources.forEach((sourceId, sourceIndex) => {
        edges.push({
          edge_id: `edge_lane_${lane.id}_step_${stepIndex}${sourceIndex ? `_from_${sourceIndex}` : ''}`,
          source: sourceId,
          target: agentId,
        })
      })

      const nextStepId = lane.nodes[stepIndex + 1]
        ? `node_lane_${lane.id}_step_${stepIndex + 1}`
        : undefined
      previousSources = (
        lane.id === 'gnc' && stepIndex === GNC_COMMITTEE_STAGE_INDEX
      )
        ? appendGncCommitteeNestedFlowNodes(
          run,
          agentId,
          teamLeadId,
          nextStepId,
          nodes,
          edges,
        )
        : [agentId]
    })

    if (lane.nodes.length > 0) {
      previousSources.forEach((sourceId, sourceIndex) => {
        edges.push({
          edge_id: `edge_lane_${lane.id}_merge${sourceIndex ? `_from_${sourceIndex}` : ''}`,
          source: sourceId,
          target: mergeId,
        })
      })
    }
  })

  if (smartCommitteeCanvas && !formatGateRecord && !hasSmartCommitteeExpertLanes(parallelFlow.lanes)) {
    edges.push({
      edge_id: 'edge_dispatch_merge_planning',
      source: dispatchId,
      target: mergeId,
    })
  }

  return {
    title: '文档审查执行流程',
    description: run.status === 'running'
      ? '审查准备 → 专项分派 → 并行审查 → 汇合 → 结论'
      : '审查执行过程回放',
    nodes,
    edges,
  }
}

const SUPER_AGENT_CANVAS_STEP_KEY_ALIASES: Record<string, string> = {
  launch: 'node_launch',
  format_gate: 'node_gate_format',
  synthesize: 'node_synthesize',
  delegate_dispatch: 'node_dispatch',
}

export function normalizeSuperAgentCanvasNodeId(nodeId: string): string {
  if (!nodeId) return nodeId
  if (nodeId.startsWith('node_')) return nodeId
  return SUPER_AGENT_CANVAS_STEP_KEY_ALIASES[nodeId] || nodeId
}

export function resolveSuperAgentFlowNodeContext(
  nodeId: string,
  parallelFlow: SuperAgentParallelFlowModel,
): SuperAgentFlowNodeContext | null {
  const mainNode = parallelFlow.mainBefore.find((item) => `node_${item.id}` === nodeId)
  if (mainNode) {
    const processItemId = mainNode.id === 'launch' ? 'review_prepare' : 'prepare'
    return {
      nodeId,
      label: mainNode.label,
      subtitle: mainNode.subtitle,
      status: mainNode.status,
      processItemId,
    }
  }

  if (nodeId === 'node_dispatch') {
    return {
      nodeId,
      label: parallelFlow.dispatch.label,
      subtitle: parallelFlow.dispatch.subtitle,
      status: parallelFlow.dispatch.status,
      processItemId: 'delegate',
    }
  }

  if (nodeId === 'node_gate_format') {
    if (parallelFlow.gate) {
      return {
        nodeId,
        label: parallelFlow.gate.label,
        subtitle: parallelFlow.gate.subtitle,
        status: parallelFlow.gate.status,
        processItemId: 'delegate',
      }
    }
    return {
      nodeId,
      label: '格式预审',
      subtitle: '等待格式预审结果',
      status: 'pending',
      processItemId: 'delegate',
    }
  }

  if (nodeId === 'node_merge') {
    return {
      nodeId,
      label: parallelFlow.merge.label,
      subtitle: parallelFlow.merge.subtitle,
      status: parallelFlow.merge.status,
      processItemId: 'merge',
    }
  }

  if (nodeId === 'node_synthesize') {
    return {
      nodeId,
      label: parallelFlow.conclusion.label,
      subtitle: parallelFlow.conclusion.subtitle,
      status: parallelFlow.conclusion.status,
      processItemId: 'conclusion',
    }
  }

  const laneHeadMatch = nodeId.match(/^node_lane_(.+)$/)
  if (laneHeadMatch && !nodeId.includes('_step_')) {
    const lane = parallelFlow.lanes.find((item) => item.id === laneHeadMatch[1])
    if (lane) {
      return {
        nodeId,
        label: lane.title.replace(/^子任务 \d+ · /, '') || lane.title,
        subtitle: lane.subtitle,
        status: lane.status,
        processItemId: lane.processItemId || `lane-${lane.id}`,
      }
    }
  }

  const laneStepMatch = nodeId.match(/^node_lane_(.+)_step_(\d+)$/)
  if (laneStepMatch) {
    const lane = parallelFlow.lanes.find((item) => item.id === laneStepMatch[1])
    const stepIndex = Number(laneStepMatch[2])
    const stepNode = lane?.nodes[stepIndex]
    if (lane && stepNode) {
      return {
        nodeId,
        label: stepNode.label,
        subtitle: stepNode.subtitle,
        status: stepNode.status,
        processItemId: lane.processItemId || `lane-${lane.id}`,
      }
    }
  }

  return resolveGncCommitteeCanvasNodeContext(nodeId)
}

export function buildNodeDetail(
  nodeId: string,
  run: SuperAgentRun,
  options?: {
    classification?: MaterialClassification | null
    reviewPlusTask?: ReviewPlusTaskDetail | null
  },
): SuperAgentFlowNodeDetail | null {
  const mainDef = SUPER_AGENT_MAIN_FLOW_STEPS.find((step) => step.nodeId === nodeId)
  const subMatch = nodeId.match(/^node_sub_(\w+)_(.+)$/)
  const classification = options?.classification || run.classification
  const adaptive = resolveAdaptiveRouterDiagnostics(classification)
  const smartDiag = resolveSmartCommitteeDiagnostics(run, classification)
  const sections: SuperAgentFlowNodeDetailSection[] = []

  const pushSection = (
    kind: SuperAgentFlowNodeDetailSectionKind,
    title: string,
    lines: string[],
  ) => {
    const cleaned = filterBusinessLines(lines.map((line) => compactText(line, 240)).filter(Boolean))
    if (cleaned.length) sections.push({ kind, title, lines: cleaned })
  }

  if (mainDef?.stepKey === 'identify' || (subMatch && subMatch[1] === 'identify')) {
    pushSection('inputs', '输入', [
      run.objective ? `用户目标：${run.objective}` : '',
      `${run.materials?.length || 0} 份上传材料`,
    ])
    pushSection('outputs', '输出', [
      run.route_decision
        ? `路由：${ROUTE_LABELS[run.route_decision.route] || run.route_decision.route}`
        : classification?.recommended_route
          ? `推荐：${classification.recommended_route}`
          : '',
      classification?.doc_type ? `文档类型：${classification.doc_type}` : '',
      classification?.domain ? `领域：${classification.domain}` : '',
    ])
    pushSection('review', '复判信息', [
      adaptive.reasoningSummary ? `路由推理：${adaptive.reasoningSummary}` : classification?.reason || '',
      ...(run.route_decision?.reasons || []).slice(0, 4).map((reason) => `依据：${reason}`),
      ...adaptive.guardrailCorrections.slice(0, 4).map((item) => `Guardrail：${item}`),
      adaptive.confidencePercent != null ? `置信度：${adaptive.confidencePercent}%` : '',
    ])
    if (classification?.user_overrides?.route) {
      pushSection('actions', '用户操作', [`已覆盖路由：${classification.user_overrides.route}`])
    }
  }

  if (mainDef?.stepKey === 'parse' || (subMatch && subMatch[1] === 'parse')) {
    const stats = run.structured_bundle?.stats || {}
    const parseTrace = skillTraceById(run.skill_traces || [], 'bootstrap_review_plus_task')
    pushSection('inputs', '输入', [
      `${run.materials?.length || 0} 份上传材料`,
      run.classification?.parse_plan?.default_parser_type
        ? `默认解析器：${run.classification.parse_plan.default_parser_type}`
        : '',
    ])
    pushSection('outputs', '输出', [
      `${stats.material_count || run.materials?.length || 0} 份材料已解析`,
      `${stats.section_count || 0} 个章节块`,
      run.source_review_id ? `Document IR 载体：${run.source_review_id}` : '',
    ])
    pushSection('review', '复判信息', [
      run.quality_report?.parse_quality_score != null
        ? `解析质量：${Math.round(Number(run.quality_report.parse_quality_score) * 100)}%`
        : '',
      ...(run.structured_bundle?.parser_fallback_logs || []).slice(0, 3).map(
        (log) => sanitizeBusinessReportText(String(log)),
      ),
    ])
    if (parseTrace) {
      pushSection('diagnostics', '诊断', [
        ...formatObjectSummaryLines(parseTrace.output_summary),
        ...(parseTrace.warnings || []).map((warning) => sanitizeBusinessReportText(warning)),
      ])
    }
  }

  if (mainDef?.stepKey === 'structure' || (subMatch && subMatch[1] === 'structure')) {
    const stats = run.structured_bundle?.stats || {}
    const sectionTree = asRecord(run.structured_bundle?.section_tree)
    const evidencePool = asRecord(run.structured_bundle?.evidence_pool)
    const sectionSummaries = summarizeNamedRecords(sectionTree.sections || run.structured_bundle?.chunks, 3)
    const evidenceSummaries = summarizeNamedRecords(evidencePool.evidences || evidencePool.items || run.structured_bundle?.chunks, 3)
    pushSection('inputs', '输入', [
      `材料 ${stats.material_count || run.materials?.length || 0} 份`,
      run.source_review_id ? `上游载体：${run.source_review_id}` : '',
    ])
    pushSection('outputs', '输出', [
      `${stats.section_count || 0} 个章节`,
      `${stats.evidence_count || 0} 条证据`,
      `${stats.check_item_count || run.structured_bundle?.check_items?.length || 0} 个检查项`,
      ...sectionSummaries.map((item) => `关键 section：${item}`),
      ...evidenceSummaries.map((item) => `关键 evidence：${item}`),
    ])
    pushSection('review', '复判信息', [
      ...(run.structured_bundle?.warnings || []).slice(0, 4),
      run.structured_bundle?.stats ? '结构化结果可用于后续审查与仲裁' : '结构化尚未完成',
    ])
    const structureTrace = skillTraceById(run.skill_traces || [], 'structure_materials')
    if (structureTrace) {
      pushSection('diagnostics', '执行诊断', [
        ...formatObjectSummaryLines(structureTrace.output_summary),
        ...(structureTrace.warnings || []).map((warning) => sanitizeBusinessReportText(warning)),
      ])
    }
  }

  const isExpertReviewNode = subMatch?.[1] === 'review' && subMatch[2].startsWith('expert_')
  if (subMatch && subMatch[1] === 'review' && subMatch[2] === 'dispatch') {
    pushSection('review', '复判信息', [
      smartDiag.taskBoardSummary?.task_count
        ? `TaskBoard：${smartDiag.taskBoardSummary.task_count} 个任务`
        : '',
      smartDiag.taskSpecCount ? `TaskSpec：${smartDiag.taskSpecCount} 项` : '',
      smartDiag.executionModeLabel ? `执行模式：${smartDiag.executionModeLabel}` : '',
      ...smartDiag.executionModeSummaryLines.slice(0, 3),
    ])
    pushSection('diagnostics', '诊断', smartDiag.degradationNotes.slice(0, 4))
  }

  if (isExpertReviewNode || nodeId === 'node_sub_review_specialists') {
    const expertKey = isExpertReviewNode ? subMatch![2].replace(/^expert_/, '') : ''
    const expertTasks = collectExpertTaskSources(run, classification)
    const expert = isExpertReviewNode
      ? expertTasks.find((task) => sanitizeSubFlowKey(task.taskId) === expertKey)
      : undefined
    pushSection('inputs', '输入', [
      expert?.specialist ? `specialist：${expert.specialist}` : '',
      expert?.objective ? `任务目标：${expert.objective}` : '',
      expert?.inputSummary ? `input_summary：${expert.inputSummary}` : '',
      expert?.evidenceSummary ? `evidence_summary：${expert.evidenceSummary}` : '',
      `${run.structured_bundle?.stats?.evidence_count || 0} 条输入证据`,
    ])
    pushSection('outputs', '输出', [
      expert?.title ? `专家：${expert.title}` : '',
      expert?.executionMode ? `execution_mode：${expert.executionMode}` : '',
      ...(expert?.findings || []).slice(0, 4).map((item) => `finding：${item}`),
    ])
    pushSection('review', '复判信息', [
      expert ? `状态：${stepStatusDisplayLabel(expert.status, 'active')}` : '',
      expert?.fallbackReason ? `fallback：${expert.fallbackReason}` : '',
      ...(expert?.warnings || []).slice(0, 4).map((item) => `warning：${item}`),
      ...smartDiag.specialistModes.slice(0, 4).map(
        (item) => `${item.title}（${item.executionMode}）`,
      ),
    ])
    pushSection('diagnostics', '诊断', [
      ...smartDiag.fallbackReasons.slice(0, 3),
      ...smartDiag.degradationNotes.slice(0, 3),
    ])
  } else if (nodeId === 'node_review' || (subMatch && subMatch[1] === 'review' && subMatch[2] === 'arbiter')) {
    pushSection('inputs', '输入', [
      `${run.structured_bundle?.stats?.evidence_count || 0} 条证据可供引用`,
      run.source_review_id ? `审查载体：${run.source_review_id}` : '',
    ])
    if (isSmartCommitteeRun(run)) {
      const review = asRecord(run.review_plus_result)
      const arbiterSummary = asRecord(review.arbiter_summary)
      pushSection('outputs', '输出', [
        Number(run.review_plus_result?.finding_count || 0)
          ? `${run.review_plus_result?.finding_count} 条专家发现`
          : '等待专家组回传',
        smartDiag.hasArbiterSummary ? '含仲裁汇总摘要' : '',
      ])
      pushSection('review', '复判信息', [
        smartDiag.executionModeLabel ? `执行模式：${smartDiag.executionModeLabel}` : '',
        ...smartDiag.executionModeSummaryLines.slice(0, 4),
        smartDiag.arbiterConsensusSummary ? `仲裁共识：${smartDiag.arbiterConsensusSummary}` : '',
        Object.keys(arbiterSummary).length ? `冲突处理：${Object.keys(arbiterSummary.conflicts || {}).length || 0} 组` : '',
        ...asArray(review.replan_suggestions).slice(0, 3).map((item) => `建议：${String(item)}`),
      ])
      pushSection('diagnostics', '诊断', [
        ...smartDiag.degradationNotes.slice(0, 4),
        ...smartDiag.fallbackReasons.slice(0, 3),
      ])
    } else if (resolveReviewExecutionRoute(run) === 'review_plus') {
      const task = options?.reviewPlusTask
      pushSection('review', '复判信息', [
        task?.status ? `委托状态：${task.status}` : '',
        Number(run.review_plus_result?.finding_count || 0)
          ? `审查意见 ${run.review_plus_result?.finding_count} 条`
          : '',
      ])
    }
  } else if (subMatch && subMatch[1] === 'review') {
    const task = options?.reviewPlusTask
    pushSection('review', '复判信息', [
      task?.status ? `Review-Plus 状态：${task.status}` : '',
      Number(run.review_plus_result?.finding_count || 0)
        ? `审查意见 ${run.review_plus_result?.finding_count} 条`
        : '',
    ])
  }

  if (mainDef?.stepKey === 'arbitration' || (subMatch && subMatch[1] === 'arbitration')) {
    const review = asRecord(run.review_plus_result)
    const arbiterSummary = asRecord(review.arbiter_summary)
    const conflictCount = Number(review.conflict_count || Object.keys(asRecord(arbiterSummary.conflicts)).length || 0)
    pushSection('inputs', '输入', [
      Number(run.review_plus_result?.finding_count || 0)
        ? `${run.review_plus_result?.finding_count} 条原始发现`
        : '等待各分支审查回传',
    ])
    pushSection('outputs', '输出', [
      conflictCount ? `冲突组 ${conflictCount} 个` : '无显著冲突',
      smartDiag.hasArbiterSummary ? '已生成仲裁摘要' : '等待仲裁汇总',
    ])
    pushSection('review', '复判信息', [
      smartDiag.arbiterConsensusSummary ? `仲裁共识：${smartDiag.arbiterConsensusSummary}` : '',
      ...asArray(review.replan_suggestions).slice(0, 4).map((item) => `建议：${String(item)}`),
      ...Object.entries(asRecord(arbiterSummary.recommendations)).slice(0, 3).map(
        ([key, value]) => `${key}：${compactText(value, 80)}`,
      ),
    ])
  }

  if (nodeId === 'node_gate_format' && isSmartCommitteeRun(run)) {
    const formatGate = resolveFormatGateTaskRecord(run, classification)
    if (formatGate) {
      const ctx = resolveFormatGateOutputContext(formatGate, run, classification)
      const stats = run.structured_bundle?.stats || {}
      pushSection('summary', '业务摘要', buildFormatGateBusinessLines(ctx, formatGate))
      pushSection('outputs', '预审输出', buildFormatGateOutputLines(ctx))
      pushSection('inputs', '阶段输入', filterBusinessLines([
        formatSummaryRecord(formatGate.input_summary),
        `${stats.material_count || run.materials?.length || 0} 份材料`,
        `${stats.evidence_count || 0} 条证据`,
      ]))
      pushSection('review', '审查输出', filterBusinessLines([
        ...ctx.findingLines.slice(0, 6),
      ]))
      pushSection('diagnostics', '执行诊断', filterBusinessLines([
        ...smartDiag.degradationNotes.slice(0, 2),
      ]))
      return {
        nodeId,
        label: resolveFormatGateLabel(formatGate),
        status: ctx.gateStatus,
        nodeLevel: 'main',
        sections,
      }
    }
    return buildFormatGateFallbackDetail(nodeId, run, classification)
  }

  if (nodeId === 'node_dispatch' && isSmartCommitteeRun(run)) {
    const expertTasks = collectExpertTaskSources(run, classification)
    const smartPlan = smartReviewPlanRecord(run)
    const laneStatuses = expertTasks.map((task) => task.status)
    const dispatchPhase = resolveSmartDispatchPlanPhase(run, expertTasks.length)
    const formatGate = resolveFormatGateTaskRecord(run, classification)
    pushSection('summary', '业务摘要', filterBusinessLines([
      expertTasks.length ? `调度结论：已选择 ${expertTasks.length} 位专家` : '调度结论：待选择专家',
      run.route_decision?.route ? `路径：${ROUTE_LABELS[run.route_decision.route] || run.route_decision.route}` : '',
      formatGate ? `门禁：${stepStatusDisplayLabel(mapTaskBoardStatus(String(formatGate.status || 'pending')), 'active')}` : '',
      dispatchPhase ? `当前阶段：${dispatchPhase}` : '',
    ]))
    pushSection('review', '专家清单', expertTasks.map((task) => {
      const modeTag = task.executionMode && task.executionMode !== 'unknown' && task.executionMode !== 'planned'
        ? ` · ${formatExecutionModeLabel(task.executionMode)}`
        : ''
      return `${task.title}（${stepStatusDisplayLabel(task.status, 'active')}${modeTag}）`
    }).filter(Boolean))
    const selectionReasons = filterBusinessLines([
      ...asArray(smartPlan.selection_reasons).map((item) => String(item)),
      ...asArray(smartPlan.expert_selection_reasons).map((item) => String(item)),
      ...asArray(asRecord(smartPlan.chief_review_plan).selection_reasons).map((item) => String(item)),
      adaptive.reasoningSummary ? `路由推理：${adaptive.reasoningSummary}` : '',
      classification?.reason ? `分类依据：${classification.reason}` : '',
    ]).slice(0, 6)
    if (selectionReasons.length) {
      pushSection('review', '选择理由', selectionReasons)
    }
    pushSection('outputs', '调度输出', filterBusinessLines([
      expertTasks.length ? `已选专家：${expertTasks.map((task) => task.title).join('、')}` : '已选专家：待选择',
      dispatchPhase ? `当前阶段：${dispatchPhase}` : '',
      run.route_decision?.route ? `路径：${ROUTE_LABELS[run.route_decision.route] || run.route_decision.route}` : '',
      formatGate ? `门禁：${stepStatusDisplayLabel(mapTaskBoardStatus(String(formatGate.status || 'pending')), 'active')}` : '',
      ...selectionReasons.slice(0, 2),
    ]))
    if (formatGate) {
      const gateStatus = mapTaskBoardStatus(String(formatGate.status || 'pending'))
      const gateOutput = asRecord(formatGate.output_summary)
      pushSection('review', '格式门禁', filterBusinessLines([
        `门禁项：${String(formatGate.title || '文档格式预审')}`,
        `状态：${stepStatusDisplayLabel(gateStatus, 'active')}`,
        compactText(gateOutput.summary || gateOutput.gate_summary || formatGate.summary, 180),
        ...asArray(gateOutput.warnings).map((item) => String(item)).slice(0, 3),
      ]))
    }
    pushSection('inputs', '阶段输入', [
      `${run.materials?.length || 0} 份材料`,
      `${run.structured_bundle?.stats?.evidence_count || 0} 条证据`,
      smartDiag.taskSpecCount ? `TaskSpec ${smartDiag.taskSpecCount} 项` : '',
    ])
    const dispatchTraceCount = resolveSuperAgentNodeLlmTraces('node_dispatch', run).length
    pushSection('diagnostics', '执行诊断', filterBusinessLines([
      ...smartDiag.degradationNotes.slice(0, 4),
      dispatchTraceCount ? `执行轨迹 ${dispatchTraceCount} 条` : '',
    ]))
    return {
      nodeId,
      label: '智能调度',
      status: resolveSmartDispatchStatus(run, expertTasks, laneStatuses),
      nodeLevel: 'main',
      sections,
    }
  }

  if (nodeId === 'node_merge' && isSmartCommitteeRun(run)) {
    const review = asRecord(run.review_plus_result)
    const arbiterSummary = asRecord(review.arbiter_summary)
    const findingCount = Number(run.review_plus_result?.finding_count || 0)
    const conflictCount = Number(
      review.conflict_count || Object.keys(asRecord(arbiterSummary.conflicts)).length || 0,
    )
    const recommendations = Object.entries(asRecord(arbiterSummary.recommendations)).slice(0, 4).map(
      ([key, value]) => `${key}：${compactText(value, 100)}`,
    )
    pushSection('summary', '业务摘要', filterBusinessLines([
      smartDiag.arbiterConsensusSummary
        ? `综合结论：${smartDiag.arbiterConsensusSummary}`
        : findingCount
          ? `已汇总 ${findingCount} 条专家发现，等待总师裁决`
          : '等待各专家回传审查结论',
      conflictCount ? `冲突组 ${conflictCount} 个` : '暂无显著冲突',
      findingCount ? `发现 ${findingCount} 项` : '',
      summarizeFindingSeverityDistribution(run),
    ]))
    pushSection('review', '裁决依据', filterBusinessLines([
      '加权因素：证据覆盖、发现严重度、专家置信度',
      smartDiag.citationCoverage != null
        ? `引用覆盖 ${Math.round(smartDiag.citationCoverage * 100)}%`
        : '',
      smartDiag.hasArbiterSummary ? '已完成总师加权汇总' : '等待仲裁汇总',
      ...recommendations,
    ]))
    pushSection('outputs', '综合输出', filterBusinessLines([
      findingCount ? `问题 ${findingCount} 项` : '问题：暂无',
      summarizeFindingSeverityDistribution(run),
      conflictCount ? `冲突组 ${conflictCount} 个` : '冲突：暂无显著冲突',
      smartDiag.arbiterConsensusSummary
        ? `最终建议：${compactText(smartDiag.arbiterConsensusSummary, 120)}`
        : recommendations[0] || '',
      ...smartDiag.replanSuggestions.slice(0, 2).map((item) => `建议：${item}`),
    ]))
    if (smartDiag.replanSuggestions.length) {
      pushSection('review', '后续建议', smartDiag.replanSuggestions.slice(0, 4))
    }
    pushSection('outputs', '汇总输出', filterBusinessLines([
      findingCount ? `${findingCount} 条审查发现` : '',
      ...asArray(review.final_recommendations).map((item) => String(item)).slice(0, 4),
    ]))
    pushSection('diagnostics', '执行诊断', [
      ...smartDiag.degradationNotes.slice(0, 3),
      ...smartDiag.fallbackReasons.slice(0, 3),
    ])
    const expertTasks = collectExpertTaskSources(run, classification)
    return {
      nodeId,
      label: '总师综合评判',
      status: resolveSmartCommitteeMergeStatus(run, expertTasks.map((task) => task.status), classification),
      nodeLevel: 'main',
      sections,
    }
  }

  const canvasLaneStepMatch = nodeId.match(/^node_lane_(.+)_step_(\d+)$/)
  if (canvasLaneStepMatch && isSmartCommitteeRun(run)) {
    const laneId = canvasLaneStepMatch[1]
    const expertTasks = collectExpertTaskSources(run, classification)
    const expert = expertTasks.find((task) => sanitizeSubFlowKey(task.taskId) === laneId)
    if (expert) {
      const outcome = resolveReviewOutcomeStatus(expert.status, expert.findingCount, expert.maxSeverity)
      pushSection('summary', '业务摘要', filterBusinessLines([
        `专家：${expert.title}`,
        `审查状态：${outcome.outcomeLabel}`,
        expert.findingCount ? `发现 ${expert.findingCount} 项` : expert.status === 'completed' ? '审查已完成，暂无发现' : '审查进行中',
      ]))
      pushSection('review', '审查输出', filterBusinessLines([
        ...expert.findings.slice(0, 6),
        expert.evidenceSummary ? `证据引用：${expert.evidenceSummary}` : '',
        expert.fallbackReason ? `降级说明：${expert.fallbackReason}` : '',
        ...expert.warnings.slice(0, 3),
      ]))
      pushSection('inputs', '阶段输入', filterBusinessLines([
        expert.objective ? `任务目标：${expert.objective}` : '',
        expert.inputSummary ? `输入摘要：${expert.inputSummary}` : '',
        `${run.structured_bundle?.stats?.evidence_count || 0} 条输入证据`,
      ]))
      if (expert.executionMode && !['unknown', 'planned'].includes(expert.executionMode)) {
        pushSection('outputs', '执行方式', [formatExecutionModeLabel(expert.executionMode)])
      }
      pushSection('diagnostics', '执行诊断', smartDiag.degradationNotes.slice(0, 3))
      return {
        nodeId,
        label: expert.title,
        status: outcome.displayStatus,
        nodeLevel: 'sub',
        sections,
      }
    }
  }

  if (nodeId === 'node_synthesize') {
    const findingCount = Number(run.review_plus_result?.finding_count || 0)
    const review = asRecord(run.review_plus_result)
    const evidenceCoverage = review.evidence_coverage != null
      ? Number(review.evidence_coverage)
      : run.quality_report?.evidence_quality_score != null
        ? Number(run.quality_report.evidence_quality_score)
        : undefined
    const limited = run.status === 'limited' || smartDiag.limited
    pushSection('summary', '业务摘要', filterBusinessLines([
      run.status === 'completed' || run.status === 'limited'
        ? '质量评测与审查报告已生成'
        : '等待质量评测与报告生成',
      run.status === 'completed' || run.status === 'limited' ? '报告状态：可导出' : '报告状态：生成中',
      run.quality_report?.overall_score != null
        ? `质量分 ${Math.round(Number(run.quality_report.overall_score) * 100)}%`
        : '',
      smartDiag.citationCoverage != null
        ? `引用覆盖 ${Math.round(smartDiag.citationCoverage * 100)}%`
        : '',
      findingCount ? `已汇总 ${findingCount} 条审查发现` : '',
      limited ? '当前为 limited，需人工确认' : '',
    ]))
    pushSection('review', '质量复核', filterBusinessLines([
      run.quality_report?.overall_score != null
        ? `综合质量 ${Math.round(Number(run.quality_report.overall_score) * 100)}%`
        : '',
      smartDiag.citationCoverage != null
        ? `引用覆盖 ${Math.round(smartDiag.citationCoverage * 100)}%`
        : '',
      evidenceCoverage != null
        ? `证据覆盖 ${Math.round(evidenceCoverage * 100)}%`
        : '',
      run.quality_report?.evidence_quality_score != null
        ? `证据质量 ${Math.round(Number(run.quality_report.evidence_quality_score) * 100)}%`
        : '',
      limited ? '当前为 limited，需人工确认' : '',
      ...(run.quality_report?.warnings || []).slice(0, 3),
    ]))
    pushSection('outputs', '报告输出', filterBusinessLines([
      run.status === 'completed' || run.status === 'limited' ? '报告状态：可导出' : '报告状态：生成中',
      limited ? 'limited：是，需人工确认' : 'limited：否',
      run.quality_report?.overall_score != null
        ? `质量分 ${Math.round(Number(run.quality_report.overall_score) * 100)}%`
        : '',
      smartDiag.citationCoverage != null
        ? `引用覆盖 ${Math.round(smartDiag.citationCoverage * 100)}%`
        : '',
      evidenceCoverage != null
        ? `证据覆盖 ${Math.round(evidenceCoverage * 100)}%`
        : '',
      findingCount ? `汇总问题 ${findingCount} 项` : '',
    ]))
    pushSection('diagnostics', '执行诊断', (run.trace_report?.degradation_summary || []).slice(0, 4))
    return {
      nodeId,
      label: '质量复核与报告',
      status: run.status === 'completed' || run.status === 'limited'
        ? 'completed'
        : run.status === 'failed'
          ? 'failed'
          : 'running',
      nodeLevel: 'main',
      sections,
    }
  }

  const gncCommitteeCanvasDetail = buildGncCommitteeCanvasNodeDetail(nodeId, run)
  if (gncCommitteeCanvasDetail) {
    return gncCommitteeCanvasDetail
  }

  const gncLaneStepMatch = nodeId.match(/^node_lane_gnc_step_(\d+)$/)
  if (gncLaneStepMatch) {
    const stepIndex = Number(gncLaneStepMatch[1])
    const model = buildGncReviewProcessModelFromRun(run)
    const stage = model.stages[stepIndex]
    const hybridIndex = stepIndex - model.stages.length
    const hybridDef = hybridIndex >= 0 ? GNC_HYBRID_EXTENSION_DEFS[hybridIndex] : undefined
    const ctx = buildGncWorkflowContext(run)

    if (stage) {
      const label = stage.label
      const subtitle = buildGncStageSubtitleFromModel(stage.stageKey, model)
      const stepStatus = mapGncFlowStatusToWorkflow(stage.status)

      pushSection('summary', '业务摘要', filterBusinessLines([
        label,
        subtitle,
        stage.conditionalNote || '',
      ]))
      pushSection('review', '审查输出', buildGncReviewOutputLines(run))
      if (stage.steps.length > 1) {
        pushSection('review', '底层步骤', stage.steps.map(
          (step) => `${step.label}（${stepStatusDisplayLabel(mapGncFlowStatusToWorkflow(step.status), 'active')}）${step.subtitle ? `：${step.subtitle}` : ''}`,
        ))
      }
      if (stage.stageKey === 'document_evidence_prep' || stage.stageKey === 'committee_review') {
        pushSection('review', 'AD/AC 子流程', buildGncUnitCoverageLines(run))
      }
      if (stage.stageKey === 'committee_review') {
        const subflowTasks = resolveGncCommitteeDeepParallelTasks(run)
        pushSection('review', '专家组子流程', subflowTasks.map(
          (task) => `${task.label}（${stepStatusDisplayLabel(task.status, 'active')}）${task.summary ? `：${task.summary}` : ''}`,
        ))
        pushSection('review', '专家组结论汇总', filterBusinessLines([
          stepStatus === 'completed' ? '专家组审查已完成，意见已归并' : '',
          stepStatus === 'running' ? '专家组审查进行中，等待结论汇总' : '',
          asArray(ctx.result.findings).length ? `汇总发现 ${asArray(ctx.result.findings).length} 条` : '',
          asArray(ctx.result.conflicts).length ? `冲突 ${asArray(ctx.result.conflicts).length} 组` : '',
          stepStatus === 'pending' ? '等待专家组审查启动' : '',
        ]))
        pushSection('review', '旁听角色', GNC_COMMITTEE_OBSERVER_DEFS.map(
          (observer) => `${observer.label}：${stepStatus === 'completed' ? '已参与' : '未启用 · 详情占位'}`,
        ))
      }
      const gncTraces = asArray(run.gnc_review_result?.traces)
      if (gncTraces.length) {
        pushSection('diagnostics', '执行轨迹', gncTraces.slice(0, 6).map((trace) => {
          const record = asRecord(trace)
          return `${formatGncStepLabel(textValue(record.step))}：${formatGncTraceSummary(record.summary)}`
        }))
      }
      return {
        nodeId,
        label,
        status: stepStatus,
        nodeLevel: 'sub',
        sections,
      }
    }

    if (hybridDef) {
      const extensionOutput = asRecord(ctx.result[hybridDef.stepKey])
      pushSection('summary', '业务摘要', filterBusinessLines([
        hybridDef.label,
        hybridDef.summary,
      ]))
      pushSection('review', '扩展接入状态', filterBusinessLines([
        Object.keys(extensionOutput).length
          ? '后端已返回该 HYBRID 扩展节点结果'
          : `当前仅做前端可视化规划，后端 ${hybridDef.stepKey} 尚未执行`,
        hybridDef.summary,
      ]))
      return {
        nodeId,
        label: hybridDef.label,
        status: 'pending',
        nodeLevel: 'sub',
        sections,
      }
    }
  }

  if (nodeId === 'node_launch') {
    pushSection('summary', '业务摘要', [
      materialCountReady(run) ? '审查材料已就绪' : '等待材料准备完成',
      run.source_review_id ? `审查载体 ${run.source_review_id}` : '',
    ])
    pushSection('outputs', '准备输出', [
      `${run.structured_bundle?.stats?.material_count || run.materials?.length || 0} 份材料`,
      `${run.structured_bundle?.stats?.evidence_count || 0} 条证据`,
      `${run.structured_bundle?.stats?.check_item_count || 0} 个检查项`,
    ])
    return {
      nodeId,
      label: '审查准备',
      status: materialCountReady(run) ? 'completed' : run.status === 'running' ? 'running' : 'pending',
      nodeLevel: 'main',
      sections,
    }
  }

  if (mainDef?.stepKey === 'quality' || (subMatch && subMatch[1] === 'quality')) {
    pushSection('inputs', '输入', [
      `${run.structured_bundle?.stats?.evidence_count || 0} 条证据`,
      Number(run.review_plus_result?.finding_count || 0)
        ? `${run.review_plus_result?.finding_count} 条审查发现`
        : '',
    ])
    pushSection('outputs', '输出', [
      run.quality_report?.overall_score != null
        ? `综合质量 ${Math.round(Number(run.quality_report.overall_score) * 100)}%`
        : '',
      run.status === 'completed' || run.status === 'limited' ? '报告可导出' : '报告生成中',
    ])
    pushSection('review', '复判信息', [
      smartDiag.citationCoverage != null
        ? `引用覆盖：${Math.round(smartDiag.citationCoverage * 100)}%`
        : '',
      run.quality_report?.evidence_quality_score != null
        ? `证据质量：${Math.round(Number(run.quality_report.evidence_quality_score) * 100)}%`
        : '',
      smartDiag.executionModeLabel ? `execution mode：${smartDiag.executionModeLabel}` : '',
      run.status === 'limited' ? '当前为 limited，需人工确认' : '无 limited 限制',
      ...(run.quality_report?.warnings || []).slice(0, 4),
    ])
    pushSection('diagnostics', '诊断', [
      ...(run.trace_report?.degradation_summary || []).slice(0, 4),
    ])
  }

  if (mainDef) {
    const subFlow = buildSubFlowForMain(mainDef.stepKey, run, options)
    const label = mainDef.label
    const status = resolveMainFlowStepStatus(mainDef.stepKey, run, subFlow, options)
    if (!sections.length) {
      pushSection('outputs', '产出摘要', [resolveMainFlowSubtitle(mainDef.stepKey, run, subFlow)])
    }
    return {
      nodeId,
      label,
      status,
      nodeLevel: 'main',
      artifactKind: mainDef.artifactKind,
      sections,
    }
  }

  if (subMatch) {
    const mainKey = subMatch[1] as SuperAgentMainFlowStepKey
    const subKey = subMatch[2]
    const subFlow = buildSubFlowForMain(mainKey, run, options)
    const sub = subFlow.find((item) => item.subKey === subKey)
    const parent = SUPER_AGENT_MAIN_FLOW_STEPS.find((step) => step.stepKey === mainKey)
    if (!sub || !parent) return null
    if (!sections.length) {
      pushSection('outputs', '步骤摘要', [sub.subtitle])
    }
    return {
      nodeId,
      label: sub.label,
      status: sub.status,
      nodeLevel: 'sub',
      parentId: parent.nodeId,
      artifactKind: parent.artifactKind,
      sections,
    }
  }

  return null
}

export const buildNodeDetails = buildNodeDetail

export function buildNodeDetailPanelModel(
  detail: SuperAgentFlowNodeDetail | null,
  fallbackSummary = '',
): SuperAgentNodeDetailPanelModel {
  if (!detail) {
    return {
      businessSummary: fallbackSummary ? [fallbackSummary] : [],
      reviewSections: [],
      phaseSections: [],
      diagnosticSections: [],
    }
  }

  const summaryLines = sanitizeDetailLines(
    detail.sections
      .filter((section) => section.kind === 'summary')
      .flatMap((section) => section.lines),
  )
  const reviewSections = detail.sections
    .filter((section) => section.kind === 'review' || section.kind === 'actions')
    .map((section) => ({ title: section.title, lines: sanitizeDetailLines(section.lines) }))
    .filter((section) => section.lines.length)
  const phaseSections = detail.sections
    .filter((section) => section.kind === 'inputs' || section.kind === 'outputs')
    .map((section) => ({ title: section.title, lines: sanitizeDetailLines(section.lines) }))
    .filter((section) => section.lines.length)
  const diagnosticSections = detail.sections
    .filter((section) => section.kind === 'diagnostics')
    .map((section) => ({ title: section.title, lines: sanitizeDetailLines(section.lines) }))
    .filter((section) => section.lines.length)

  const businessSummary = summaryLines.length
    ? summaryLines
    : fallbackSummary
      ? sanitizeDetailLines([fallbackSummary])
      : sanitizeDetailLines(
        detail.sections
          .filter((section) => section.kind === 'outputs')
          .flatMap((section) => section.lines)
          .slice(0, 4),
      ).length
        ? sanitizeDetailLines(
          detail.sections
            .filter((section) => section.kind === 'outputs')
            .flatMap((section) => section.lines)
            .slice(0, 4),
        )
        : reviewSections[0]?.lines.slice(0, 2) || phaseSections[0]?.lines.slice(0, 2) || []

  return {
    businessSummary,
    reviewSections,
    phaseSections,
    diagnosticSections,
  }
}

function aggregateStatuses(statuses: WorkflowStepStatus[]): WorkflowStepStatus | undefined {
  if (!statuses.length) return undefined
  if (statuses.some((status) => status === 'failed' || status === 'blocked')) return 'failed'
  if (statuses.some((status) => status === 'running')) return 'running'
  if (statuses.some((status) => status === 'awaiting_confirm')) return 'awaiting_confirm'
  if (statuses.every((status) => status === 'completed' || status === 'skipped')) return 'completed'
  if (statuses.some((status) => status === 'completed')) return 'running'
  return 'pending'
}

function aggregateLaneStatus(statuses: WorkflowStepStatus[]): WorkflowStepStatus {
  return aggregateStatuses(statuses) || 'pending'
}

function isLaneReturned(status: WorkflowStepStatus): boolean {
  return status === 'completed' || status === 'awaiting_confirm' || status === 'skipped'
}

function resolveMergeStatus(run: SuperAgentRun, laneStatuses: WorkflowStepStatus[]): WorkflowStepStatus {
  if (run.status === 'completed' || run.status === 'limited') return 'completed'
  if (run.status === 'failed') return 'failed'
  if (!laneStatuses.length) return 'pending'
  if (laneStatuses.every(isLaneReturned)) {
    return laneStatuses.some((status) => status === 'awaiting_confirm') ? 'awaiting_confirm' : 'completed'
  }
  if (aggregateLaneStatus(laneStatuses) === 'failed') return 'failed'
  if (laneStatuses.some((status) => isLaneReturned(status) || status === 'running')) return 'running'
  return 'pending'
}

function countReturnedLanes(lanes: SuperAgentParallelFlowLane[], run: SuperAgentRun): number {
  if (run.status === 'completed' || run.status === 'limited') return lanes.length
  return lanes.filter((lane) => isLaneReturned(lane.status)).length
}

function stepStatusProgressRank(status: WorkflowStepStatus): number {
  switch (status) {
    case 'pending':
      return 0
    case 'running':
    case 'blocked':
    case 'interrupted':
      return 1
    case 'awaiting_confirm':
      return 2
    case 'failed':
    case 'completed':
    case 'skipped':
      return 3
    default:
      return 0
  }
}

function capDownstreamStatus(
  downstream: WorkflowStepStatus,
  upstream: WorkflowStepStatus,
): WorkflowStepStatus {
  if (upstream === 'failed') return downstream === 'failed' ? 'failed' : 'pending'
  if (stepStatusProgressRank(downstream) <= stepStatusProgressRank(upstream)) return downstream
  if (upstream === 'pending') return 'pending'
  if (upstream === 'running' || upstream === 'blocked' || upstream === 'interrupted') return 'pending'
  if (upstream === 'awaiting_confirm') return 'awaiting_confirm'
  return downstream
}

function applySmartDependencyStatusCaps(
  flow: SuperAgentParallelFlowModel,
  run: SuperAgentRun,
  formatGateRecord: Record<string, unknown> | null,
): SuperAgentParallelFlowModel {
  if (!isSmartCommitteeRun(run)) return flow
  if (run.status === 'completed' || run.status === 'limited') return flow

  const launchStatus = flow.mainBefore.find((node) => node.id === 'launch')?.status || 'pending'
  const dispatchRaw = flow.dispatch.status
  const dispatchStatus = capNodeStatusByDependencies(dispatchRaw, [launchStatus])
  const dispatchCapped = dispatchStatus !== dispatchRaw
  const dispatch = {
    ...flow.dispatch,
    status: dispatchStatus,
    subtitle: dispatchCapped
      ? appendSmartDependencyWaitSubtitle(flow.dispatch.subtitle, SMART_DEPENDENCY_WAIT_MESSAGES.upstream)
      : flow.dispatch.subtitle,
  }

  const effectiveGateStatus = formatGateRecord
    ? resolveEffectiveGateDownstreamStatus(formatGateRecord, run, run.classification)
    : undefined
  let gate = flow.gate
  if (gate) {
    const gateRaw = gate.status
    const gateStatus = capNodeStatusByDependencies(gateRaw, [dispatchStatus])
    const gateCapped = gateStatus !== gateRaw
    gate = {
      ...gate,
      status: gateStatus,
      subtitle: gateCapped
        ? appendSmartDependencyWaitSubtitle(gate.subtitle, SMART_DEPENDENCY_WAIT_MESSAGES.upstream)
        : gate.subtitle,
    }
  }

  const expertUpstreamStatuses: WorkflowStepStatus[] = formatGateRecord
    ? [effectiveGateStatus ?? gate?.status ?? 'pending']
    : [dispatchStatus]
  const gateBlocksExperts = expertUpstreamStatuses.some(isSmartDependencyBlocking)
  const expertWaitMessage = gateBlocksExperts
    ? SMART_DEPENDENCY_WAIT_MESSAGES.gateBlocked
    : SMART_DEPENDENCY_WAIT_MESSAGES.upstream

  const lanes = flow.lanes.map((lane) => {
    const nodes = lane.nodes.map((node) => {
      const nodeRaw = node.status
      const nodeStatus = capNodeStatusByDependencies(nodeRaw, expertUpstreamStatuses)
      const nodeCapped = nodeStatus !== nodeRaw
      return {
        ...node,
        status: nodeStatus,
        subtitle: nodeCapped
          ? appendSmartDependencyWaitSubtitle(node.subtitle, expertWaitMessage)
          : node.subtitle,
      }
    })
    return finalizeSequentialLane({
      ...lane,
      nodes,
      subtitle: nodes.some((node, index) => node.status !== lane.nodes[index]?.status)
        ? appendSmartDependencyWaitSubtitle(lane.subtitle, expertWaitMessage)
        : lane.subtitle,
    })
  })

  const expertLaneStatuses = lanes.map((lane) => lane.status)
  const mergeUpstream: WorkflowStepStatus[] = [...expertUpstreamStatuses]
  if (expertLaneStatuses.length) {
    if (!expertLaneStatuses.every(isSmartDependencyTerminal)) {
      mergeUpstream.push('pending')
    }
  } else if (!formatGateRecord) {
    mergeUpstream.push(dispatchStatus)
  }

  const mergeRaw = flow.merge.status
  let mergeStatus = capNodeStatusByDependencies(mergeRaw, mergeUpstream)
  const mergeBlocked = expertUpstreamStatuses.some(isSmartDependencyBlocking)
  const mergeWaitingExperts = expertLaneStatuses.length > 0
    && !expertLaneStatuses.every(isSmartDependencyTerminal)
  const mergeCapped = mergeStatus !== mergeRaw
  const mergeWaitMessage = mergeBlocked
    ? SMART_DEPENDENCY_WAIT_MESSAGES.gateBlocked
    : mergeWaitingExperts
      ? SMART_DEPENDENCY_WAIT_MESSAGES.experts
      : SMART_DEPENDENCY_WAIT_MESSAGES.upstream
  const merge = {
    ...flow.merge,
    status: mergeStatus,
    subtitle: mergeCapped || mergeWaitingExperts || mergeBlocked
      ? appendSmartDependencyWaitSubtitle(flow.merge.subtitle, mergeWaitMessage)
      : flow.merge.subtitle,
  }

  const conclusionRaw = flow.conclusion.status
  const conclusionStatus = capNodeStatusByDependencies(conclusionRaw, [mergeStatus])
  const conclusionCapped = conclusionStatus !== conclusionRaw
  const mergeIncomplete = !isSmartDependencyTerminal(mergeStatus) && mergeStatus !== 'failed'
  const conclusion = {
    ...flow.conclusion,
    status: conclusionStatus,
    subtitle: (conclusionCapped || mergeIncomplete) && conclusionStatus !== 'completed'
      ? appendSmartDependencyWaitSubtitle(
        flow.conclusion.subtitle,
        SMART_DEPENDENCY_WAIT_MESSAGES.merge,
      )
      : flow.conclusion.subtitle,
  }

  return {
    ...flow,
    dispatch,
    gate,
    lanes,
    merge,
    conclusion,
  }
}

function finalizeSequentialLaneNodes(nodes: SuperAgentParallelFlowNode[]): SuperAgentParallelFlowNode[] {
  let upstreamStatus: WorkflowStepStatus = 'completed'
  return nodes.map((node, index) => {
    const status = index === 0 ? node.status : capDownstreamStatus(node.status, upstreamStatus)
    upstreamStatus = status
    return { ...node, status }
  })
}

function finalizeSequentialLane(lane: SuperAgentParallelFlowLane): SuperAgentParallelFlowLane {
  const nodes = finalizeSequentialLaneNodes(lane.nodes)
  return {
    ...lane,
    nodes,
    status: aggregateLaneStatus(nodes.map((node) => node.status)),
  }
}

function reviewPlusStepStatus(task: ReviewPlusTaskDetail | null | undefined, stepKey: string): WorkflowStepStatus {
  if (!task) return 'pending'
  const graph = buildReviewPlusWorkflowGraph(task)
  const status = graph.nodes.find((node) => node.step_key === stepKey)?.status || 'pending'
  // 智能审查向导不提供追溯链路审签入口；待确认仅应在有操作入口的页面展示。
  return status === 'awaiting_confirm' ? 'completed' : status
}

function traceNodeStatus(run: SuperAgentRun, skillId: string): WorkflowStepStatus {
  const trace = skillTraceById(run.skill_traces || [], skillId)
  if (!trace) return run.status === 'running' ? 'pending' : 'pending'
  if (trace.status === 'completed') return 'completed'
  if (trace.status === 'failed') return 'failed'
  if (trace.status === 'running') return 'running'
  return 'pending'
}

function hasRoute(run: SuperAgentRun, routes: string[]): boolean {
  const route = run.route_decision?.route || run.requested_route
  return routes.includes(route)
}

function hasTrace(run: SuperAgentRun, skillId: string): boolean {
  return Boolean(skillTraceById(run.skill_traces || [], skillId))
}

function smartReviewPlanRecord(run: SuperAgentRun): Record<string, unknown> {
  const classification = run.classification as (MaterialClassification & { smart_review_plan?: unknown }) | undefined
  const reviewPlan = asRecord(classification?.review_plan)
  const directSmartPlan = asRecord(classification?.smart_review_plan)
  if (Object.keys(directSmartPlan).length) return directSmartPlan
  return asRecord(reviewPlan.smart_review_plan)
}

function smartPrimaryPath(run: SuperAgentRun): string {
  const reviewPlan = asRecord(run.classification?.review_plan)
  const smartPlan = smartReviewPlanRecord(run)
  return textValue(reviewPlan.smart_primary_path || smartPlan.primary_path).trim()
}

function isSmartCommitteeRun(run: SuperAgentRun): boolean {
  return smartPrimaryPath(run) === 'smart_committee' || (
    hasRoute(run, ['smart'])
    && hasTrace(run, 'smart_review_committee')
    && !hasTrace(run, 'run_review_plus')
  )
}

function isReviewPlusPrimaryRun(run: SuperAgentRun): boolean {
  if (isSmartCommitteeRun(run)) return false
  const reviewPlan = asRecord(run.classification?.review_plan)
  const primaryPath = textValue(reviewPlan.smart_primary_path || smartPrimaryPath(run)).trim()
  if (primaryPath === 'review_plus') return true
  if (run.classification?.review_plus_ready === true) return true
  return hasRoute(run, ['review_plus', 'hybrid']) || hasTrace(run, 'run_review_plus')
}

function buildReviewPlusLane(run: SuperAgentRun, task?: ReviewPlusTaskDetail | null): SuperAgentParallelFlowLane | null {
  const smartCommittee = isSmartCommitteeRun(run)
  if (!smartCommittee && !run.source_review_id && !hasTrace(run, 'run_review_plus') && !hasRoute(run, ['review_plus', 'hybrid', 'auto'])) return null

  if (smartCommittee) {
    const model = buildSmartReviewProcessModelFromRun(run)
    const spec = buildProcessLaneFromModel('review-plus', model, {
      title: '子任务 1 · 智能审查',
      subtitle: model.subtitle,
      processItemId: 'lane-review-plus',
      resolveStageSubtitle: (stage) => buildSmartStageSubtitleFromModel(stage.stageKey, model),
    })
    return processLaneSpecToParallelLane(spec)
  }

  const model = buildReviewPlusProcessModelFromRun(run, task)
  const spec = buildProcessLaneFromModel('review-plus', model, {
    title: '子任务 1 · 文件组审查',
    subtitle: model.subtitle || '型号文件组符合性审查',
    processItemId: 'lane-review-plus',
    resolveStageSubtitle: (stage) => buildReviewPlusStageSubtitleFromModel(stage.stageKey, model),
  })
  return processLaneSpecToParallelLane(spec)
}

function shouldShowStructuringLane(run: SuperAgentRun, hasReviewPlusLane: boolean): boolean {
  if (resolveReviewExecutionMode(run) === 'structure_only') return true
  if (hasReviewPlusLane && resolveReviewExecutionMode(run) !== 'hybrid') return false
  return hasTrace(run, 'structure_materials') || Boolean(run.structured_bundle?.stats?.section_count)
}

function buildStructuringLane(run: SuperAgentRun): SuperAgentParallelFlowLane {
  const structureStatus = traceNodeStatus(run, 'structure_materials')
  const stats = run.structured_bundle?.stats || {}
  const materialCount = Number(stats.material_count || run.materials?.length || 0)
  const sectionCount = Number(stats.section_count || 0)
  const evidenceCount = Number(stats.evidence_count || 0)
  const hasStats = materialCount > 0 || sectionCount > 0
  const nodes: SuperAgentParallelFlowNode[] = [
    {
      id: 'structure-build',
      label: '材料结构化',
      subtitle: hasStats
        ? `${materialCount} 份材料 · ${sectionCount} 章节 · ${evidenceCount} 条证据`
        : '章节树、片段解析与证据池构建',
      status: structureStatus === 'pending' && hasStats ? 'completed' : structureStatus,
      badge: '步骤 1',
      processItemId: 'lane-structuring',
    },
  ]
  return finalizeSequentialLane({
    id: 'structuring',
    title: '子任务 · 材料结构化',
    subtitle: '材料解析与证据池构建',
    status: aggregateLaneStatus(nodes.map((node) => node.status)),
    nodes,
    processItemId: 'lane-structuring',
  })
}

function buildGncLane(run: SuperAgentRun): SuperAgentParallelFlowLane | null {
  if (!hasRoute(run, ['gnc_review', 'gnc_review_only', 'hybrid']) && !hasTrace(run, 'run_gnc_review')) return null
  const model = buildGncReviewProcessModelFromRun(run)
  const hybridNodes = buildGncHybridExtensionNodes(run).map((node) => ({
    id: node.id,
    label: node.label,
    subtitle: node.subtitle || '',
    status: node.status,
    badge: node.badge,
    processItemId: 'lane-gnc',
  }))
  const spec = buildProcessLaneFromModel('gnc', model, {
    title: resolveReviewExecutionMode(run) === 'hybrid'
      ? '子任务 · GNC 深化审查'
      : '子任务 · GNC 审查',
    subtitle: model.currentStageLabel !== '—'
      ? `当前：${model.currentStageLabel}`
      : (model.subtitle || 'GNC 审查流程'),
    processItemId: 'lane-gnc',
    resolveStageSubtitle: (stage) => buildGncStageSubtitleFromModel(stage.stageKey, model),
    extraNodes: hybridNodes,
  })
  return processLaneSpecToParallelLane(spec)
}

function resolveNonSmartSynthesizeOutputSummary(run: SuperAgentRun): string {
  const findingCount = Number(run.review_plus_result?.finding_count || 0)
  const overall = run.quality_report?.overall_score
  if (run.status === 'completed' || run.status === 'limited') {
    const parts = [run.status === 'limited' ? 'limited 报告' : '报告已生成']
    if (overall != null) parts.push(`质量 ${Math.round(Number(overall) * 100)}%`)
    if (findingCount) parts.push(`${findingCount} 条问题`)
    return flowSubtitle(parts.join(' · ')) || parts.join(' · ')
  }
  if (run.quality_report?.parse_quality_score) {
    return flowSubtitle('质量复核进行中') || '质量复核进行中'
  }
  return flowSubtitle('等待质量复核与报告生成') || '等待质量复核与报告生成'
}

function renumberVisibleLanes(lanes: SuperAgentParallelFlowLane[]): SuperAgentParallelFlowLane[] {
  return lanes.map((lane, index) => ({
    ...lane,
    title: lane.title.replace(/^子任务 \d+ · /, `子任务 ${index + 1} · `),
  }))
}

export function buildSuperAgentParallelFlow(
  run: SuperAgentRun,
  reviewPlusTask?: ReviewPlusTaskDetail | null,
  pauseContext: SuperAgentRunPauseContext = 'active',
): SuperAgentParallelFlowModel {
  const smartCommittee = isSmartCommitteeRun(run)
  const expertTasks = smartCommittee ? collectExpertTaskSources(run, run.classification) : []
  const reviewPlusLane = smartCommittee ? null : buildReviewPlusLane(run, reviewPlusTask)
  const discoveredLanes = renumberVisibleLanes((
    smartCommittee
      ? buildSmartCommitteeBusinessLanes(run)
      : [
        reviewPlusLane,
        shouldShowStructuringLane(run, Boolean(reviewPlusLane)) ? buildStructuringLane(run) : null,
        buildGncLane(run),
      ].filter((lane): lane is SuperAgentParallelFlowLane => Boolean(lane))
  ))
  const lanes = (
    discoveredLanes.length
      ? discoveredLanes
      : smartCommittee
        ? []
        : [{
          id: 'discovering',
          title: '子任务 · 等待链路上报',
          subtitle: '等待子流程上报结果',
          status: run.status === 'running' ? 'running' as const : 'pending' as const,
          processItemId: 'lane-discovering',
          nodes: [],
        }]
  ).map((lane) => {
    if (lane.nodes.length) return lane
    return {
      ...lane,
      nodes: [
        {
          id: `${lane.id}-discovering`,
          label: '等待上报',
          subtitle: '正在发现调用链路',
          status: lane.status,
          badge: '待展开',
          processItemId: lane.processItemId,
        },
      ],
    }
  })
  const laneStatuses = lanes.map((lane) => lane.status)
  const delegatedStatus = aggregateLaneStatus(laneStatuses)
  const mergeStatus = smartCommittee
    ? resolveSmartCommitteeMergeStatus(run, laneStatuses, run.classification)
    : resolveMergeStatus(run, laneStatuses)
  const mainBefore = buildReviewProcessCanvasMainBefore(run, pauseContext)
  const smartMergeSubtitle = resolveSmartMergeOutputSummary(run, run.classification)
  const formatGateRecord = smartCommittee ? resolveFormatGateTaskRecord(run, run.classification) : null
  const gateStatus = resolveFormatGateStatus(formatGateRecord)
  const gateNode: SuperAgentParallelFlowNode | undefined = formatGateRecord
    ? {
      id: 'gate_format',
      label: resolveFormatGateLabel(formatGateRecord),
      subtitle: resolveFormatGateOutputSummary(formatGateRecord, run, run.classification),
      status: gateStatus,
      badge: '门禁',
      processItemId: 'delegate',
    }
    : undefined

  const rawFlow: SuperAgentParallelFlowModel = {
    mainBefore,
    dispatch: {
      id: 'dispatch',
      label: smartCommittee ? '智能调度' : '任务执行',
      subtitle: smartCommittee
        ? resolveSmartDispatchOutputSummary(run, expertTasks.length, formatGateRecord)
        : `分派 ${lanes.length} 个专项分支`,
      status: smartCommittee
        ? resolveSmartDispatchStatus(run, expertTasks, laneStatuses)
        : (lanes.length ? delegatedStatus : 'pending'),
      badge: '分叉',
      processItemId: 'delegate',
    },
    gate: gateNode,
    lanes,
    merge: {
      id: 'merge',
      label: smartCommittee ? '总师综合评判' : SUPER_AGENT_PROCESSING_TERMS.mergeResults,
      subtitle: smartCommittee
        ? smartMergeSubtitle
        : '等待各审查分支完成后汇合',
      status: mergeStatus,
      badge: smartCommittee ? '总师' : '汇合',
      processItemId: 'merge',
    },
    conclusion: {
      id: 'synthesize',
      label: '质量复核与报告',
      subtitle: smartCommittee
        ? resolveSmartSynthesizeOutputSummary(run)
        : resolveNonSmartSynthesizeOutputSummary(run),
      status: run.status === 'completed' || run.status === 'limited'
        ? 'completed'
        : run.status === 'failed'
          ? 'failed'
          : mergeStatus === 'completed' || mergeStatus === 'awaiting_confirm'
            ? 'running'
            : 'pending',
      badge: '主链',
      processItemId: 'conclusion',
    },
  }

  const dependencyCappedFlow = applySmartDependencyStatusCaps(rawFlow, run, formatGateRecord)

  return applyPauseToParallelFlow(dependencyCappedFlow, pauseContext)
}

function completedCount(statuses: WorkflowStepStatus[]): number {
  return statuses.filter((status) => status === 'completed' || status === 'skipped').length
}

function laneCurrentNode(
  lane: SuperAgentParallelFlowLane,
  pauseContext: SuperAgentRunPauseContext = 'active',
): SuperAgentParallelFlowNode | undefined {
  const active = lane.nodes.find((node) => (
    node.status === 'running'
    || node.status === 'awaiting_confirm'
    || node.status === 'blocked'
    || isPausedStepStatus(node.status, pauseContext)
  ))
  if (active) return active

  const failed = lane.nodes.find((node) => node.status === 'failed')
  if (failed) return failed

  const pending = lane.nodes.find((node) => node.status === 'pending')
  if (pending) return pending

  return lane.nodes[lane.nodes.length - 1]
}

export function resolveReviewPlusRunningStepLabel(task?: ReviewPlusTaskDetail | null): string {
  if (!task || task.status === 'completed') return ''
  const stepKey = resolveActiveWorkflowStepKey(task)
  const step = REVIEW_PLUS_PIPELINE_STEPS.find((item) => item.step_key === stepKey)
  return step?.label || stepKey
}

function resolveRunningStageLabel(
  run: SuperAgentRun,
  flowGraph: SuperAgentParallelFlowModel,
  reviewPlusTask?: ReviewPlusTaskDetail | null,
  pauseContext: SuperAgentRunPauseContext = 'active',
): string {
  if (pauseContext === 'resuming') return '正在续跑…'
  if (pauseContext === 'interrupted') return '审查已中断'
  if (pauseContext === 'failed') return '审查执行失败'
  if (pauseContext === 'stale') return '审查可能已停滞'
  const reviewPlusStep = resolveReviewPlusRunningStepLabel(reviewPlusTask)
  if (reviewPlusStep && isReviewPlusPrimaryRun(run) && (run.status === 'running' || reviewPlusTask?.status === 'running')) {
    return `文件组审查 · ${reviewPlusStep}`
  }
  if (isSmartCommitteeRun(run) && (run.status === 'running' || hasTrace(run, 'smart_review_committee'))) {
    const runningLane = flowGraph.lanes.find(
      (lane) => lane.status === 'running'
        || lane.status === 'awaiting_confirm'
        || isPausedStepStatus(lane.status, pauseContext),
    )
    if (runningLane) {
      const current = laneCurrentNode(runningLane, pauseContext)
      if (current) return `审查执行 · ${current.label}`
    }
    return '审查执行'
  }
  const runningLane = flowGraph.lanes.find(
    (lane) => lane.status === 'running'
      || lane.status === 'awaiting_confirm'
      || isPausedStepStatus(lane.status, pauseContext),
  )
  if (runningLane) {
    const current = laneCurrentNode(runningLane, pauseContext)
    if (current) return `${runningLane.title.replace(/^子任务 \d+ · /, '')} · ${current.label}`
    return runningLane.title
  }
  const mainActive = flowGraph.mainBefore.find(
    (node) => node.status === 'running' || isPausedStepStatus(node.status, pauseContext),
  )
  if (mainActive) return mainActive.label
  if (flowGraph.merge.status === 'running' || isPausedStepStatus(flowGraph.merge.status, pauseContext)) {
    return flowGraph.merge.label
  }
  if (flowGraph.conclusion.status === 'running' || isPausedStepStatus(flowGraph.conclusion.status, pauseContext)) {
    return flowGraph.conclusion.label
  }
  return '等待下一阶段'
}

function laneToProcessItem(
  lane: SuperAgentParallelFlowLane,
  pauseContext: SuperAgentRunPauseContext = 'active',
  reviewPlusTask?: ReviewPlusTaskDetail | null,
): SuperAgentProcessItem {
  const current = laneCurrentNode(lane, pauseContext)
  const done = completedCount(lane.nodes.map((node) => node.status))
  const findings = current ? [`当前环节：${current.label}`] : []
  if (lane.id === 'review-plus' && reviewPlusTask) {
    const attentionCount = countPendingCoverageHitl(reviewPlusTask)
    if (attentionCount > 0) {
      findings.push(`${attentionCount} 项建议在审查结果页复核`)
    }
  }
  return {
    id: `lane-${lane.id}`,
    title: lane.title,
    summary: current ? `${current.label}：${compactText(current.subtitle, 48)}` : '等待专项分支回传',
    status: lane.status,
    relation: '并行',
    tags: ['专项分支', `${done}/${lane.nodes.length} 已完成`],
    details: lane.nodes.map((node) => `${node.label}：${compactText(node.subtitle, 80)}`),
    findings,
  }
}

export function buildSuperAgentProcessingViewModel(
  run: SuperAgentRun,
  options?: {
    classification?: MaterialClassification | null
    reviewPlusTask?: ReviewPlusTaskDetail | null
    pauseContext?: SuperAgentRunPauseContext
  },
): SuperAgentProcessingViewModel {
  const pauseContext = options?.pauseContext ?? 'active'
  const flowGraph = buildSuperAgentParallelFlow(run, options?.reviewPlusTask, pauseContext)
  const laneNodeTotal = flowGraph.lanes.reduce((sum, lane) => sum + lane.nodes.length, 0)
  const laneNodeDone = flowGraph.lanes.reduce(
    (sum, lane) => sum + completedCount(lane.nodes.map((node) => node.status)),
    0,
  )
  const laneDone = countReturnedLanes(flowGraph.lanes, run)
  const totalUnits = flowGraph.mainBefore.length + Math.max(laneNodeTotal, flowGraph.lanes.length) + 2
  const doneUnits =
    completedCount(flowGraph.mainBefore.map((node) => node.status))
    + (laneNodeTotal > 0 ? laneNodeDone : laneDone)
    + (flowGraph.merge.status === 'completed' || flowGraph.merge.status === 'awaiting_confirm' ? 1 : 0)
    + (flowGraph.conclusion.status === 'completed' ? 1 : 0)
  const currentStage = resolveRunningStageLabel(run, flowGraph, options?.reviewPlusTask, pauseContext)
  const routeLabel = run.route_decision
    ? ROUTE_LABELS[run.route_decision.route] || run.route_decision.route
    : options?.classification?.recommended_route || '自动路由'
  const materialCount = Number(run.structured_bundle?.stats?.material_count || run.materials?.length || 0)
  const sectionCount = Number(run.structured_bundle?.stats?.section_count || 0)
  const evidenceCount = Number(run.structured_bundle?.stats?.evidence_count || 0)
  const warningCount = [...(run.quality_report?.warnings || []), ...(run.trace_report?.degradation_summary || [])].length
  const delegateTitle = '并行专项审查'
  const delegateTags = ['并行专项', `${laneDone}/${flowGraph.lanes.length} 已回传`]

  const prepNode = flowGraph.mainBefore[0]
  const processItems: SuperAgentProcessItem[] = [
    {
      id: 'review_prepare',
      title: '审查准备',
      summary: prepNode
        ? compactText(prepNode.subtitle, 80) || '材料与结构化输入已就绪'
        : (materialCount ? `已整理 ${materialCount} 份材料` : '正在完成审查前置准备'),
      status: prepNode?.status || resolveReviewPrepareStatus(run, pauseContext),
      relation: '串行',
      tags: ['审查准备', routeLabel],
      details: [
        `审查路径：${routeLabel}`,
        materialCount ? `材料：${materialCount} 份` : '',
        sectionCount || evidenceCount ? `结构化：${sectionCount} 章 · ${evidenceCount} 证据` : '',
        options?.classification?.domain ? `领域：${options.classification.domain}` : '',
      ].filter(Boolean),
      findings: options?.classification?.reason
        ? [`背景：${compactText(options.classification.reason, 80)}`]
        : [],
    },
    {
      id: 'delegate',
      title: isSmartCommitteeRun(run) ? '并行智能审查' : delegateTitle,
      summary: isSmartCommitteeRun(run)
        ? (flowGraph.lanes.length
          ? `智能调度 · 已分派 ${flowGraph.lanes.length} 位专家，已回传 ${laneDone}/${flowGraph.lanes.length}`
          : '智能调度 · 规划中，等待专家选择')
        : `已分派 ${flowGraph.lanes.length} 个专项分支，已回传 ${laneDone}/${flowGraph.lanes.length}`,
      status: flowGraph.dispatch.status,
      relation: '并行',
      tags: delegateTags,
      details: isSmartCommitteeRun(run)
        ? [
          flowGraph.lanes.length ? `智能调度已选定 ${flowGraph.lanes.length} 位专家` : '智能调度规划中',
          laneDone === flowGraph.lanes.length && flowGraph.lanes.length ? '全部专家已回传' : '等待专家审查回传',
        ]
        : [
          `已启动 ${flowGraph.lanes.length} 个专项审查分支`,
          laneDone === flowGraph.lanes.length ? '全部分支已回传结果' : '等待专项分支回传',
        ],
      findings: flowGraph.lanes.map((lane) => {
        const current = laneCurrentNode(lane, pauseContext)
        return `${lane.title}：${current?.label || stepStatusDisplayLabel(lane.status, pauseContext)}`
      }),
      children: flowGraph.lanes.map((lane) => laneToProcessItem(lane, pauseContext, options?.reviewPlusTask)),
    },
    {
      id: 'merge',
      title: isSmartCommitteeRun(run) ? '总师综合评判' : '交叉核验与结果汇合',
      summary: isSmartCommitteeRun(run)
        ? (flowGraph.merge.status === 'completed'
          ? '专家意见已加权汇总'
          : `等待 ${laneDone}/${flowGraph.lanes.length} 位专家回传后汇总`)
        : (flowGraph.merge.status === 'completed'
          ? '专项分支结果已汇合'
          : flowGraph.merge.status === 'awaiting_confirm'
            ? `已接收 ${laneDone}/${flowGraph.lanes.length} 个分支结果，待人工确认`
            : `已接收 ${laneDone}/${flowGraph.lanes.length} 个分支结果`),
      status: flowGraph.merge.status,
      relation: '汇合',
      tags: isSmartCommitteeRun(run) ? ['总师汇总', '加权仲裁'] : ['结果汇合', '证据交叉核验'],
      details: isSmartCommitteeRun(run)
        ? [
          flowGraph.merge.subtitle,
          flowGraph.merge.status === 'completed'
            ? '总师已完成冲突处理与综合结论'
            : '等待各专家审查完成后进入总师汇总',
        ]
        : [
          flowGraph.merge.status === 'completed'
            ? '专项分支结果已汇合'
            : flowGraph.merge.status === 'awaiting_confirm'
              ? '分支结果已回传，部分项待人工确认'
              : '等待专项分支回传',
          `需确认项：${warningCount}`,
        ],
      findings: [
        ...(run.quality_report?.warnings || []).slice(0, 3),
        ...(run.trace_report?.degradation_summary || []).slice(0, 3),
      ].map((item) => compactText(item, 100)),
    },
    {
      id: 'conclusion',
      title: '质量复核与报告',
      summary: run.status === 'running' ? '等待质量复核与报告' : '质量复核与报告已生成',
      status: flowGraph.conclusion.status,
      relation: '结论',
      tags: ['最终结论', run.status],
      details: [
        `运行状态：${run.status}`,
        `审查意见：${Number(run.review_plus_result?.finding_count || 0)} 条`,
      ],
      findings: run.status === 'running'
        ? []
        : [run.error || '审查流程已结束，可查看结果摘要。'].filter(Boolean),
    },
  ]

  const executionMode = resolveReviewExecutionMode(run)
  const initialExpandedTeamLeadIds = executionMode === 'gnc' || executionMode === 'hybrid'
    ? resolveGncInitialExpandedTeamLeadIds(run)
    : []

  return {
    progress: totalUnits > 0 ? Math.round((doneUnits / totalUnits) * 100) : 0,
    currentStage,
    processItems,
    flowGraph,
    workflowGraph: buildSuperAgentFlowGraph(run, options?.reviewPlusTask, pauseContext),
    initialExpandedTeamLeadIds,
  }
}

function buildDelegateSubflow(task?: ReviewPlusTaskDetail | null): {
  nodes: WorkflowGraphNode[]
  edges: Array<{ edge_id: string; source: string; target: string }>
  status?: WorkflowStepStatus
  activeNodeId?: string
} {
  if (!task) return { nodes: [], edges: [] }

  const reviewGraph = buildReviewPlusWorkflowGraph(task)
  const convertedNodes: WorkflowGraphNode[] = reviewGraph.nodes.map((node) => {
    const isReviewStep = node.node_type === 'step'
    return {
      ...node,
      node_id: `rp_${node.node_id}`,
      step_key: `rp_${node.step_key}`,
      label: isReviewStep ? `子任务：${node.label}` : node.label,
      subtitle: node.subtitle || node.output_summary || (isReviewStep ? 'Review-Plus 委托步骤' : ''),
      node_type: isReviewStep ? 'agent' : node.node_type,
      parent_node_id: node.parent_node_id ? `rp_${node.parent_node_id}` : 'node_delegate_review',
    }
  })
  const convertedEdges = reviewGraph.edges.map((edge) => ({
    edge_id: `rp_${edge.edge_id}`,
    source: `rp_${edge.source}`,
    target: `rp_${edge.target}`,
  }))
  const firstReviewNodeId = 'rp_node_material_classification'
  const lastReviewNodeId = 'rp_node_report_composition'
  const bridgeEdges = [
    {
      edge_id: 'edge_delegate_review_to_review_plus',
      source: 'node_delegate_review',
      target: firstReviewNodeId,
    },
    {
      edge_id: 'edge_review_plus_to_synthesize',
      source: convertedNodes.some((node) => node.node_id === lastReviewNodeId)
        ? lastReviewNodeId
        : convertedNodes[convertedNodes.length - 1]?.node_id || firstReviewNodeId,
      target: 'node_synthesize',
    },
  ].filter((edge) => {
    const hasSource = edge.source === 'node_delegate_review' || convertedNodes.some((node) => node.node_id === edge.source)
    const hasTarget = edge.target === 'node_synthesize' || convertedNodes.some((node) => node.node_id === edge.target)
    return hasSource && hasTarget
  })
  const activeStepKey = resolveActiveWorkflowStepKey(task)
  return {
    nodes: convertedNodes,
    edges: [...bridgeEdges, ...convertedEdges],
    status: aggregateStatuses(convertedNodes.map((node) => node.status)),
    activeNodeId: activeStepKey ? `rp_node_${activeStepKey}` : undefined,
  }
}

export function getActiveSuperAgentNodeId(
  run: SuperAgentRun,
  reviewPlusTask?: ReviewPlusTaskDetail | null,
  pauseContext: SuperAgentRunPauseContext = 'active',
): string {
  const parallelFlow = buildSuperAgentParallelFlow(run, reviewPlusTask, pauseContext)

  for (const lane of parallelFlow.lanes) {
    const current = laneCurrentNode(lane, pauseContext)
    if (current && (
      current.status === 'running'
      || current.status === 'awaiting_confirm'
      || current.status === 'blocked'
      || current.status === 'failed'
      || isPausedStepStatus(current.status, pauseContext)
    )) {
      const stepIndex = lane.nodes.indexOf(current)
      return `node_lane_${lane.id}_step_${stepIndex}`
    }
    if (lane.status === 'running' || lane.status === 'awaiting_confirm' || isPausedStepStatus(lane.status, pauseContext)) {
      return `node_lane_${lane.id}`
    }
  }

  const mainActive = parallelFlow.mainBefore.find(
    (node) => node.status === 'running' || isPausedStepStatus(node.status, pauseContext),
  )
  if (mainActive) return `node_${mainActive.id}`

  if (
    parallelFlow.dispatch.status === 'running'
    || isPausedStepStatus(parallelFlow.dispatch.status, pauseContext)
  ) return 'node_dispatch'
  if (
    parallelFlow.gate
    && (parallelFlow.gate.status === 'running'
      || parallelFlow.gate.status === 'blocked'
      || isPausedStepStatus(parallelFlow.gate.status, pauseContext))
  ) return 'node_gate_format'
  if (
    parallelFlow.merge.status === 'running'
    || isPausedStepStatus(parallelFlow.merge.status, pauseContext)
  ) return 'node_merge'
  if (
    parallelFlow.conclusion.status === 'running'
    || isPausedStepStatus(parallelFlow.conclusion.status, pauseContext)
  ) return 'node_synthesize'

  const lastCompletedMain = [...parallelFlow.mainBefore].reverse().find((node) => node.status === 'completed')
  if (lastCompletedMain) return `node_${lastCompletedMain.id}`

  return 'node_upload'
}

export function statusLabel(status?: WorkflowStepStatus): string {
  if (!status) return '—'
  return STEP_STATUS_LABELS[status] || status
}

export function formatChatElapsed(ms?: number): string {
  if (!ms) return ''
  return formatElapsedMs(ms)
}

const REVIEW_PLUS_PREPARE_STEPS: ReviewPlusPipelineStepKey[] = [
  'material_classification',
  'document_structuring',
  'chief_orchestration',
  'rule_extraction',
  'rule_section_mapping',
]

const REVIEW_PLUS_RETURN_STEPS: ReviewPlusPipelineStepKey[] = [
  'traceability',
  'cross_document_review',
  'report_composition',
]

function formatObjectSummaryLines(obj: Record<string, unknown> | undefined, max = 8): string[] {
  if (!obj || !Object.keys(obj).length) return []
  return Object.entries(obj)
    .filter(([, value]) => value != null && value !== '')
    .slice(0, max)
    .map(([key, value]) => {
      if (Array.isArray(value)) return `${key}：${value.length} 项`
      if (typeof value === 'object') {
        const text = JSON.stringify(value)
        return `${key}：${text.length > 100 ? `${text.slice(0, 100)}…` : text}`
      }
      const text = String(value).trim()
      return `${key}：${text.length > 120 ? `${text.slice(0, 120)}…` : text}`
    })
}

function formatEventPayloadSummary(eventType: string, payload: Record<string, unknown>): string[] {
  const lines: string[] = []
  const summary = compactText(payload.summary, 160)
  if (summary) lines.push(summary)
  const countKeys = [
    ['material_count', '型号资料'],
    ['check_item_count', '检查项'],
    ['finding_count', '审查意见'],
    ['mapped_count', '已映射'],
    ['section_count', '章节'],
    ['evidence_count', '证据'],
  ] as const
  for (const [key, label] of countKeys) {
    const value = payload[key]
    if (value != null && value !== '') lines.push(`${label}：${value}`)
  }
  if (payload.error) lines.push(`异常：${compactText(payload.error, 120)}`)
  if (!lines.length && Object.keys(payload).length) {
    lines.push(...formatObjectSummaryLines(payload, 4))
  }
  if (!lines.length && eventType) lines.push(eventType)
  return lines
}

function skillTraceToRecord(trace: SuperAgentSkillTrace, index: number, smartCommittee = false): SuperAgentLlmTraceRecord {
  const skillLabels: Record<string, string> = {
    bootstrap_review_plus_task: '审查任务建档',
    structure_materials: '型号资料结构化',
    run_review_plus: smartCommittee ? '智能审查委托' : '文件组审查委托',
    run_gnc_review: 'GNC 专项审查',
    smart_review_committee: '智能调度',
  }
  return {
    id: `skill-${trace.skill_id}-${index}`,
    agentName: skillLabels[trace.skill_id] || trace.agent_id || trace.skill_id,
    toolName: trace.tool_name || trace.skill_id,
    status: trace.status,
    elapsedMs: trace.elapsed_ms || undefined,
    inputLines: formatObjectSummaryLines(trace.input_summary),
    outputLines: formatTraceOutputSummary(trace.output_summary).length
      ? formatTraceOutputSummary(trace.output_summary)
      : formatObjectSummaryLines(trace.output_summary),
    findings: [],
    warnings: trace.warnings || [],
    evidenceRefs: [],
  }
}

function agentTraceToRecord(
  trace: Record<string, unknown>,
  index: number,
): SuperAgentLlmTraceRecord {
  const agentId = textValue(trace.agent_id)
  const input = asRecord(trace.input_summary)
  const output = asRecord(trace.output_summary)
  const outputLines = formatTraceOutputSummary(output).length
    ? formatTraceOutputSummary(output)
    : formatObjectSummaryLines(output)
  const findings = asArray(output.findings)
    .map((item) => compactText(asRecord(item).title || asRecord(item).reasoning, 120))
    .filter(Boolean)
  const evidenceRefs = [
    ...asArray(output.evidence_refs),
    ...asArray(output.task_book_evidence_refs),
    ...asArray(output.subject_evidence_refs),
  ].map(textValue).filter(Boolean)
  return {
    id: `agent-${agentId || index}`,
    agentName: formatAgentIdLabel(agentId),
    toolName: textValue(trace.tool_name) || agentId,
    status: textValue(trace.status) || 'unknown',
    elapsedMs: numberValue(trace.elapsed_ms) || undefined,
    inputLines: formatObjectSummaryLines(input),
    outputLines,
    findings: findings.slice(0, 6),
    warnings: [textValue(trace.error_message), textValue(trace.error_code)].filter(Boolean),
    evidenceRefs: [...new Set(evidenceRefs)].slice(0, 8),
  }
}

function workflowEventToRecord(
  event: Record<string, unknown>,
  index: number,
): SuperAgentLlmTraceRecord {
  const type = textValue(event.type)
  const payload = asRecord(event.payload)
  return {
    id: `event-${type || index}`,
    agentName: REVIEW_PLUS_EVENT_LABELS[type] || type || '流程事件',
    status: type.includes('failed') ? 'failed' : type.includes('started') ? 'running' : 'completed',
    timestamp: textValue(event.created_at) || undefined,
    inputLines: formatObjectSummaryLines(asRecord(payload.input)),
    outputLines: formatEventPayloadSummary(type, payload),
    findings: asArray(payload.findings)
      .map((item) => compactText(asRecord(item).title || item, 100))
      .filter(Boolean)
      .slice(0, 4),
    warnings: asArray(payload.warnings).map(textValue).filter(Boolean).slice(0, 4),
    evidenceRefs: asArray(payload.evidence_refs).map(textValue).filter(Boolean).slice(0, 6),
  }
}

function collectAgentTraces(run: SuperAgentRun, task?: ReviewPlusTaskDetail | null): Record<string, unknown>[] {
  if (task?.agent_run_traces?.length) {
    return task.agent_run_traces.map((trace) => trace as unknown as Record<string, unknown>)
  }
  return (run.trace_report?.agent_run_traces || []).map(asRecord)
}

function collectWorkflowEvents(run: SuperAgentRun, task?: ReviewPlusTaskDetail | null): Record<string, unknown>[] {
  if (task?.events?.length) {
    return task.events.map((event) => event as unknown as Record<string, unknown>)
  }
  return (run.trace_report?.workflow_events || []).map(asRecord)
}

function eventsForReviewPlusSteps(
  events: Record<string, unknown>[],
  stepKeys: ReviewPlusPipelineStepKey[],
): Record<string, unknown>[] {
  const prefixes = stepKeys.flatMap((key) => [key, `${key}_`])
  return events.filter((event) => {
    const type = textValue(event.type)
    return prefixes.some((prefix) => type === prefix || type.startsWith(prefix))
  })
}

function stepDetailToRecords(
  stepKey: ReviewPlusPipelineStepKey,
  task: ReviewPlusTaskDetail,
  nodeStatus: WorkflowStepStatus,
): SuperAgentLlmTraceRecord[] {
  const detail = buildReviewPlusStepDetail(stepKey, task, nodeStatus)
  const records: SuperAgentLlmTraceRecord[] = []

  for (const [index, event] of detail.recentEvents.entries()) {
    records.push({
      id: `rp-step-${stepKey}-event-${index}`,
      agentName: event.label || stepKey,
      status: event.type.includes('failed') ? 'failed' : 'completed',
      timestamp: event.at || undefined,
      inputLines: [],
      outputLines: event.summary ? [event.summary] : [],
      findings: [],
      warnings: [],
      evidenceRefs: [],
    })
  }

  if (stepKey === 'item_review') {
    for (const [index, trace] of (task.agent_run_traces || []).entries()) {
      records.push(agentTraceToRecord(trace as unknown as Record<string, unknown>, index))
    }
  }

  for (const [index, preview] of detail.findingPreviews.slice(0, 6).entries()) {
    records.push({
      id: `rp-step-${stepKey}-finding-${index}`,
      agentName: detail.label,
      status: preview.tone === 'danger' ? 'failed' : 'completed',
      inputLines: [],
      outputLines: [],
      findings: [preview.title, preview.subtitle].filter(Boolean) as string[],
      warnings: [],
      evidenceRefs: [],
    })
  }

  if (!records.length && (detail.summaryLines.length || detail.metrics.length)) {
    records.push({
      id: `rp-step-${stepKey}-summary`,
      agentName: detail.label,
      status: nodeStatus,
      inputLines: detail.metrics.map((metric) => `${metric.label}：${metric.value}`),
      outputLines: detail.summaryLines.slice(0, 6),
      findings: detail.highlights.slice(0, 4),
      warnings: detail.pendingHint ? [detail.pendingHint] : [],
      evidenceRefs: [],
    })
  }

  return records
}

function classificationToRecord(classification: MaterialClassification): SuperAgentLlmTraceRecord {
  return {
    id: 'classification-result',
    agentName: '型号场景识别',
    toolName: 'classify_materials',
    status: 'completed',
    inputLines: [],
    outputLines: [
      `文档类型：${classification.doc_type}`,
      `型号领域：${classification.domain}`,
      `推荐路径：${classification.recommended_route}`,
    ],
    findings: classification.reason ? [classification.reason] : [],
    warnings: [],
    evidenceRefs: [],
  }
}

function routeDecisionToRecord(run: SuperAgentRun): SuperAgentLlmTraceRecord | null {
  const decision = run.route_decision
  if (!decision) return null
  return {
    id: 'route-decision',
    agentName: '审查路径决策',
    toolName: 'route_policy',
    status: 'completed',
    inputLines: formatObjectSummaryLines({
      requested_route: run.requested_route,
      objective: compactText(run.objective, 120),
    }),
    outputLines: [
      `路径：${ROUTE_LABELS[decision.route] || decision.route}`,
      `置信度：${Math.round(decision.confidence * 100)}%`,
      ...decision.reasons.slice(0, 3),
    ],
    findings: decision.required_tools.map((tool) => `启用：${tool}`),
    warnings: decision.skipped_tools.map((tool) => `跳过：${tool}`),
    evidenceRefs: [],
  }
}

export function resolveSuperAgentNodeLlmTraces(
  nodeId: string,
  run: SuperAgentRun,
  options?: {
    classification?: MaterialClassification | null
    reviewPlusTask?: ReviewPlusTaskDetail | null
  },
): SuperAgentLlmTraceRecord[] {
  const task = options?.reviewPlusTask
  const classification = options?.classification || run.classification
  const smartCommittee = isSmartCommitteeRun(run)
  const events = collectWorkflowEvents(run, task)
  const agentTraces = collectAgentTraces(run, task)
  const records: SuperAgentLlmTraceRecord[] = []

  const pushSkill = (...skillIds: string[]) => {
    for (const skillId of skillIds) {
      const trace = skillTraceById(run.skill_traces || [], skillId)
      if (trace) records.push(skillTraceToRecord(trace, records.length, smartCommittee))
    }
  }

  if ((nodeId === 'node_identify' || nodeId.startsWith('node_sub_identify_')) && classification) {
    records.push(classificationToRecord(classification as MaterialClassification))
  }

  if (nodeId === 'node_identify' || nodeId.startsWith('node_sub_identify_')) {
    const routeRecord = routeDecisionToRecord(run)
    if (routeRecord) records.push(routeRecord)
  }

  if (nodeId === 'node_parse' || nodeId.startsWith('node_sub_parse_')) {
    pushSkill('bootstrap_review_plus_task')
  }

  if (nodeId === 'node_structure' || nodeId.startsWith('node_sub_structure_')) {
    pushSkill('structure_materials')
  }

  if (nodeId === 'node_review' || nodeId.startsWith('node_sub_review_')) {
    if (isSmartCommitteeRun(run)) {
      pushSkill('smart_review_committee')
      agentTraces.slice(0, 8).forEach((trace, index) => records.push(agentTraceToRecord(trace, index)))
    } else if (resolveReviewExecutionRoute(run) === 'gnc') {
      pushSkill('run_gnc_review')
    } else {
      pushSkill('run_review_plus')
    }
  }

  if (nodeId === 'node_arbitration' || nodeId.startsWith('node_sub_arbitration_')) {
    for (const trace of run.skill_traces || []) {
      if (trace.status === 'completed' || trace.status === 'failed') {
        records.push(skillTraceToRecord(trace, records.length, smartCommittee))
      }
    }
  }

  if (nodeId === 'node_plan') {
    const routeRecord = routeDecisionToRecord(run)
    if (routeRecord) records.push(routeRecord)
  }

  if (nodeId === 'node_archive' || nodeId === 'node_parse') {
    pushSkill('bootstrap_review_plus_task')
  }

  if (nodeId === 'node_synthesize' || nodeId === 'node_quality') {
    pushSkill('run_review_plus', 'run_gnc_review', 'structure_materials')
    if (run.quality_report?.warnings?.length) {
      records.push({
        id: 'quality-assessment',
        agentName: '质量与追溯评估',
        toolName: 'evaluate_quality',
        status: run.status === 'failed' ? 'failed' : 'completed',
        outputLines: [
          `解析质量：${run.quality_report.parse_quality_score}`,
          `追溯质量：${run.quality_report.traceability_score}`,
          `一致性：${run.quality_report.consistency_score}`,
        ],
        inputLines: [],
        findings: [],
        warnings: run.quality_report.warnings.slice(0, 6),
        evidenceRefs: [],
      })
    }
    const findingCount = Number(run.review_plus_result?.finding_count || 0)
    if (findingCount > 0) {
      records.push({
        id: 'synthesize-findings',
        agentName: SUPER_AGENT_PROCESSING_TERMS.synthesizeConclusion,
        status: 'completed',
        outputLines: [`审查意见：${findingCount} 条`],
        inputLines: [],
        findings: findingsFromRun(run).slice(0, 5).map((f) => compactText(f.title || f.reasoning, 100)).filter(Boolean),
        warnings: [],
        evidenceRefs: [],
      })
    }
  }

  const laneStepMatch = nodeId.match(/^node_lane_(.+)_step_(\d+)$/)
  if (laneStepMatch) {
    const laneId = laneStepMatch[1]
    const stepIndex = Number(laneStepMatch[2])

    if (stepIndex === 1) {
      resolveLaneDeepParallelTasks(nodeId, run, { classification, reviewPlusTask: task }).forEach((deepTask) => {
        records.push({
          id: `lane-deep-${deepTask.id}`,
          agentName: deepTask.label,
          status: deepTask.status,
          outputLines: [deepTask.summary],
          inputLines: [],
          findings: [],
          warnings: [],
          evidenceRefs: [],
        })
      })
    }

    if (laneId === 'review-plus') {
      if (stepIndex === 0) {
        pushSkill('run_review_plus')
        if (run.source_review_id) {
          records.push({
            id: 'review-plus-task-id',
            agentName: '材料与规则准备',
            toolName: 'run_review_plus',
            status: 'completed',
            outputLines: [`审查任务 ID：${run.source_review_id}`],
            inputLines: formatObjectSummaryLines({ objective: compactText(run.objective, 120) }),
            findings: [],
            warnings: [],
            evidenceRefs: [],
          })
        }
        if (task) {
          for (const stepKey of REVIEW_PLUS_PREPARE_STEPS) {
            records.push(...stepDetailToRecords(stepKey, task, reviewPlusStepStatus(task, stepKey)))
          }
        } else {
          eventsForReviewPlusSteps(events, REVIEW_PLUS_PREPARE_STEPS)
            .forEach((event, index) => records.push(workflowEventToRecord(event, index)))
        }
      } else if (stepIndex === 1) {
        if (task) {
          records.push(...stepDetailToRecords('item_review', task, reviewPlusStepStatus(task, 'item_review')))
        } else {
          agentTraces.forEach((trace, index) => records.push(agentTraceToRecord(trace, index)))
          eventsForReviewPlusSteps(events, ['item_review'])
            .forEach((event, index) => records.push(workflowEventToRecord(event, index)))
        }
      } else if (stepIndex === 2) {
        if (task) {
          for (const stepKey of REVIEW_PLUS_RETURN_STEPS) {
            records.push(...stepDetailToRecords(stepKey, task, reviewPlusStepStatus(task, stepKey)))
          }
        } else {
          eventsForReviewPlusSteps(events, REVIEW_PLUS_RETURN_STEPS)
            .forEach((event, index) => records.push(workflowEventToRecord(event, index)))
          const findingCount = Number(run.review_plus_result?.finding_count || 0)
          if (findingCount) {
            records.push({
              id: 'review-plus-report-summary',
              agentName: '结论汇总与报告',
              status: 'completed',
              outputLines: [
                `审查意见：${findingCount} 条`,
                `条款覆盖矩阵：${coverageRowsFromRun(run).length} 行`,
              ],
              inputLines: [],
              findings: [],
              warnings: [],
              evidenceRefs: [],
            })
          }
        }
      }
    }

    if (laneId === 'structuring') {
      if (stepIndex === 0) pushSkill('structure_materials')
      if (stepIndex === 0 && run.structured_bundle?.stats) {
        records.push({
          id: 'structure-output',
          agentName: '型号资料结构化输出',
          status: 'completed',
          outputLines: formatObjectSummaryLines(run.structured_bundle.stats),
          inputLines: [],
          findings: (run.structured_bundle.warnings || []).slice(0, 4),
          warnings: [],
          evidenceRefs: [],
        })
      }
    }

    if (laneId === 'gnc') {
      if (stepIndex >= 0) pushSkill('run_gnc_review')
      const model = buildGncReviewProcessModelFromRun(run)
      const stage = model.stages[stepIndex]
      if (stage?.stageKey === 'committee_review') {
        resolveGncCommitteeDeepParallelTasks(run).forEach((expert) => {
          records.push({
            id: `gnc-expert-${expert.id}`,
            agentName: expert.label,
            status: expert.status,
            outputLines: [expert.summary],
            inputLines: [],
            findings: [],
            warnings: [],
            evidenceRefs: [],
          })
        })
      }
      if (stage && (stage.stageKey === 'document_evidence_prep' || stage.stageKey === 'committee_review')) {
        buildGncUnitCoverageLines(run).slice(0, 6).forEach((line, index) => {
          records.push({
            id: `gnc-unit-${index}`,
            agentName: 'AD/AC 子流程',
            status: 'pending',
            outputLines: [line],
            inputLines: [],
            findings: [],
            warnings: [],
            evidenceRefs: [],
          })
        })
      }
      const stageStepKeys = new Set(stage?.stepKeys || [])
      const gncTraces = (run.gnc_review_result?.traces as Array<Record<string, unknown>> | undefined) || []
      gncTraces
        .filter((trace) => !stage || stageStepKeys.has(textValue(trace.step)))
        .forEach((trace, index) => {
          const stepKey = textValue(trace.step)
          records.push({
            id: `gnc-trace-${stepKey || index}`,
            agentName: formatGncStepLabel(stepKey),
            status: textValue(trace.status) || (stageStepKeys.has(stepKey) ? 'completed' : 'unknown'),
            outputLines: [formatGncTraceSummary(trace.summary)].filter(Boolean),
            inputLines: [],
            findings: [],
            warnings: [textValue(trace.error_message), textValue(trace.error_code)].filter(Boolean),
            evidenceRefs: [],
          })
        })
    }
  }

  const laneHeadMatch = nodeId.match(/^node_lane_(.+)$/)
  if (laneHeadMatch && !nodeId.includes('_step_')) {
    const laneId = laneHeadMatch[1]
    if (laneId === 'review-plus') {
      pushSkill('run_review_plus')
      agentTraces.slice(0, 8).forEach((trace, index) => records.push(agentTraceToRecord(trace, index)))
    }
    if (laneId === 'structuring') pushSkill('structure_materials')
    if (laneId === 'gnc') pushSkill('run_gnc_review')
  }

  const rpNodeMatch = nodeId.match(/^rp_node_(.+)$/)
  if (rpNodeMatch && task) {
    const stepKey = rpNodeMatch[1] as ReviewPlusPipelineStepKey
    records.push(...stepDetailToRecords(stepKey, task, reviewPlusStepStatus(task, stepKey)))
  }

  if (nodeId === 'node_dispatch') {
    pushSkill('bootstrap_review_plus_task', 'structure_materials', 'run_review_plus', 'run_gnc_review')
  }

  if (nodeId === 'node_merge') {
    for (const trace of run.skill_traces || []) {
      if (trace.status === 'completed' || trace.status === 'failed') {
        records.push(skillTraceToRecord(trace, records.length, smartCommittee))
      }
    }
  }

  const seen = new Set<string>()
  return records.filter((record) => {
    const key = `${record.agentName}|${record.toolName}|${record.outputLines.join('|')}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function buildSuperAgentResultExplainability(run: SuperAgentRun): SuperAgentResultExplainability {
  const bundle = run.structured_bundle
  const stats = bundle?.stats || {}
  const chunks = (bundle?.chunks || []).map(asRecord)
  const materials = (bundle?.materials?.length ? bundle.materials : run.materials || []).map(asRecord)
  const parsedMaterials = materials.map((material, index) => {
    const name = textValue(material.name || material.filename || `材料 ${index + 1}`)
    const relatedChunks = chunks.filter((chunk) => chunkBelongsToMaterial(chunk, name))
    const charCount = materialContentLength(material)
    const pageCount = numberValue(material.page_count || material.pages || material.pageCount)
    const sectionCount = numberValue(material.section_count)
    const metrics = [
      pageCount ? `${pageCount} 页` : '',
      charCount ? `${charCount} 字符` : '',
      relatedChunks.length ? `${relatedChunks.length} 个片段` : '',
      sectionCount ? `${sectionCount} 个章节` : '',
    ].filter(Boolean)
    const role = textValue(material.role)
    return {
      id: `${name}-${index}`,
      name,
      fileType: textValue(material.file_type || material.fileType),
      parser: textValue(material.parser_name || material.parser_type),
      parseStatus: textValue(material.parse_status || material.status || '已解析'),
      role: roleLabel(role),
      roleConfidence: material.role_confidence === undefined ? undefined : numberValue(material.role_confidence),
      documentVersion: textValue(material.document_version),
      baselineId: textValue(material.baseline_id),
      summary: materialSummary(material, chunks),
      metrics,
      warnings: asArray(material.warnings).map(textValue).filter(Boolean),
    }
  })

  const checkItems = checkItemsFromRun(run)
  const findings = findingsFromRun(run)
  const reviewItems = findings.length
    ? findings.map((finding, index) => reviewItemFromFinding(finding, index, checkItems))
    : coverageRowsFromRun(run).map(reviewItemFromCoverageRow)

  const report = reportFromRun(run)
  const chiefReviewItems = chiefReviewFromReport(report)
  const riskItems = filterBusinessLines([
    ...asArray(report.residual_risks).map(textValue),
    ...chiefReviewItems.map((item) => compactText(item.title, 120)),
    ...asArray(report.cross_document_items).map((item) => {
      const record = asRecord(item)
      return compactText(record.title || record.description || record.recommendation, 160)
    }),
    ...(run.quality_report?.warnings || []),
    ...(run.trace_report?.degradation_summary || []),
  ])
  const sourceMaterials = parsedMaterials.map((material) => material.name).filter(Boolean)
  const checkedScope = [
    `${numberValue(stats.material_count || parsedMaterials.length)} 份材料`,
    `${numberValue(stats.check_item_count || checkItems.length || reviewItems.length)} 个检查项`,
    `${numberValue(stats.section_count || countSections(bundle?.section_tree || {}))} 个章节`,
    `${numberValue(stats.evidence_count || countEvidences(bundle?.evidence_pool || {}))} 条证据`,
  ].filter((item) => !item.startsWith('0 '))
  const conclusionSummary = chiefConclusionSummary(report)
    || compactText(report.conclusion || report.summary, 260)
    || (reviewItems.some((item) => item.status !== 'passed')
      ? '审查发现需关注或不符合条目，建议按明细逐项闭环。'
      : `基于${checkedScope.join('、') || '当前材料和检查项'}未发现需关注或不符合项。`)

  return {
    materials: parsedMaterials,
    reviewItems,
    chiefReviewItems,
    conclusionSummary,
    conclusionBasis: `基于 ${sourceMaterials.join('、') || '本次输入材料'}；检查范围：${checkedScope.join('、') || '暂无结构化统计'}。`,
    riskItems,
    sourceMaterials,
    checkedScope,
  }
}

export function buildSuperAgentExportMarkdown(run: SuperAgentRun): string {
  const backendMarkdown = resolveBusinessExportMarkdown(textValue(run.report_markdown).trim())
  if (backendMarkdown) return backendMarkdown

  const result = buildSuperAgentResultExplainability(run)
  const report = reportFromRun(run)
  const reportMarkdown = resolveBusinessExportMarkdown(textValue(report.markdown).trim())
  const generatedAt = new Date().toLocaleString('zh-CN')
  const reviewCounts = result.reviewItems.length
    ? result.reviewItems.reduce(
        (counts, item) => {
          counts[item.status] += 1
          return counts
        },
        { passed: 0, attention: 0, failed: 0 } as Record<SuperAgentReviewItemStatus, number>,
      )
    : {
        passed: numberValue(report.satisfied_count),
        attention: numberValue(report.insufficient_evidence_count),
        failed: numberValue(report.not_satisfied_count) + numberValue(report.critical_count),
      }

  const lines: string[] = [
    '# 设计过程符合性审查单',
    '',
    `- 审查任务：${markdownText(run.name) || '未命名审查任务'}`,
    `- 审查日期：${generatedAt}`,
    '',
    '## 结果概览',
    '',
    `- 符合：${reviewCounts.passed}`,
    `- 需关注：${reviewCounts.attention}`,
    `- 不符合：${reviewCounts.failed}`,
    `- 检查范围：${result.checkedScope.join('、') || '暂无统计'}`,
    '',
    '## 总体结论',
    '',
    `- ${result.conclusionSummary}`,
    `- 依据：${result.conclusionBasis}`,
    '',
    '## 检查项明细',
    '',
  ]

  if (result.reviewItems.length) {
    result.reviewItems.forEach((item, index) => {
      const details = [
        markdownBullet('检查要求', item.requirement),
        markdownBullet('结论', item.conclusion),
        markdownBullet('建议', item.recommendation),
        markdownBullet('位置', item.source),
        markdownBullet('原文摘录', item.sourceQuote),
      ].filter(Boolean)
      lines.push(
        `### ${index + 1}. [${REVIEW_ITEM_STATUS_LABELS[item.status]}] ${item.title}`,
        '',
        ...(details.length ? details : ['  - 明细：该检查项已纳入统计，暂无更多结构化说明。']),
        '',
      )
    })
  } else {
    lines.push(`- 暂未返回逐项检查记录；已执行范围：${result.checkedScope.join('、') || '暂无统计'}。`, '')
  }

  if (result.riskItems.length) {
    lines.push(
      '## 风险与待确认事项',
      '',
      ...markdownList(result.riskItems, '未返回残余风险或待确认事项。'),
      '',
    )
  }

  if (reportMarkdown) {
    lines.push('## 专项审查摘要', '', reportMarkdown, '')
  }

  return sanitizeBusinessReportText(lines.join('\n'))
}
