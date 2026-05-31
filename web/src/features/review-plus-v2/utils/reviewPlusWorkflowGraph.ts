import { REVIEW_PLUS_TERMS } from '@/lib/aeroTerminology'
import type { WorkflowGraph, WorkflowGraphNode, WorkflowStepStatus } from '@aqua/workflow-core'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { REVIEW_PLUS_PIPELINE_STEPS } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { buildReviewPlusStepOutputSummary } from '@/features/review-plus-v2/utils/reviewPlusStepDetail'
import type { ReviewPlusPipelineStepKey } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import {
  countPendingTraceLinks,
  formatAgentLabel,
} from '@/features/review-plus-v2/utils/aeroDesignerWorkbenchUtils'
import { getHarnessPlan } from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'

const STATUS_TO_ACTIVE_STEP: Record<string, string> = {
  materials_uploaded: 'material_classification',
  parsing: 'document_structuring',
  parsed: 'document_structuring',
  classifying: 'material_classification',
  classified: 'scenario_detection',
  scenario_detected: 'scenario_detection',
  gatekeeping: 'scenario_detection',
  structuring: 'document_structuring',
  rule_extracting: 'rule_extraction',
  mapping: 'rule_section_mapping',
  reviewing: 'item_review',
  traceability_building: 'traceability',
  reporting: 'report_composition',
}

function eventSequence(event: { sequence?: number; created_at?: string }, fallback: number): number {
  if (Number.isFinite(Number(event.sequence))) return Number(event.sequence)
  const time = event.created_at ? Date.parse(event.created_at) : Number.NaN
  return Number.isFinite(time) ? time : fallback
}

function sortedEvents(task: ReviewPlusTaskDetail) {
  return [...(task.events || [])].sort((a, b) => eventSequence(a, 0) - eventSequence(b, 0))
}

function latestEventOfType(task: ReviewPlusTaskDetail, eventType: string) {
  const matched = sortedEvents(task).filter((event) => String(event.type || '') === eventType)
  return matched[matched.length - 1] ?? null
}

function eventOrder(task: ReviewPlusTaskDetail, eventType: string): number {
  const event = latestEventOfType(task, eventType)
  return event ? eventSequence(event, 0) : -1
}

export function getReviewPlusCompletedStepKeys(task: ReviewPlusTaskDetail): Set<string> {
  if (task.status === 'completed' || latestEventOfType(task, 'report_composition_completed')) {
    return new Set(REVIEW_PLUS_PIPELINE_STEPS.map((step) => step.step_key))
  }

  const completed = new Set<string>()
  for (const step of REVIEW_PLUS_PIPELINE_STEPS) {
    if (latestEventOfType(task, step.completeEvent)) completed.add(step.step_key)
  }
  return completed
}

function resolveFailedStepKey(task: ReviewPlusTaskDetail, completedSteps: Set<string>): string {
  const failedEvent = latestEventOfType(task, 'workflow_failed')
  const failedStep = String((failedEvent?.payload || {}).step || '')
  if (failedStep) return failedStep

  for (const step of REVIEW_PLUS_PIPELINE_STEPS) {
    if (!completedSteps.has(step.step_key)) return step.step_key
  }
  return REVIEW_PLUS_PIPELINE_STEPS[REVIEW_PLUS_PIPELINE_STEPS.length - 1]?.step_key || ''
}

function runningStepFromEvents(task: ReviewPlusTaskDetail, completedSteps: Set<string>): string {
  let running = ''
  let latestStartOrder = -1
  for (const step of REVIEW_PLUS_PIPELINE_STEPS) {
    if (!step.startEvent || completedSteps.has(step.step_key)) continue
    const startOrder = eventOrder(task, step.startEvent)
    const completeOrder = eventOrder(task, step.completeEvent)
    if (startOrder > completeOrder && startOrder > latestStartOrder) {
      running = step.step_key
      latestStartOrder = startOrder
    }
  }
  return running
}

function nextIncompleteStepKey(completedSteps: Set<string>): string {
  return REVIEW_PLUS_PIPELINE_STEPS.find((step) => !completedSteps.has(step.step_key))?.step_key || ''
}

function resolveRunningWorkflowStepKey(task: ReviewPlusTaskDetail, completedSteps: Set<string>): string {
  const eventRunning = runningStepFromEvents(task, completedSteps)
  if (eventRunning) return eventRunning

  const statusActive = STATUS_TO_ACTIVE_STEP[String(task.status)] || ''
  if (statusActive && !completedSteps.has(statusActive)) return statusActive

  return ''
}

function hasAwaitingConfirm(stepKey: string, task: ReviewPlusTaskDetail, completedSteps: Set<string>): boolean {
  // 覆盖矩阵行的 requires_human_confirmation 仅表示「结果需人工复核/待审签」，
  // 不是可阻塞流程的确认关卡；真正可操作的 HITL 在 traceability 的候选链路审签。
  if (stepKey === 'traceability' && countPendingTraceLinks(task) > 0) {
    return completedSteps.has(stepKey) || String(task.status) === 'traceability_building'
  }
  return false
}

function stepStatus(
  stepKey: string,
  task: ReviewPlusTaskDetail,
  completedSteps: Set<string>,
  runningStepKey: string,
): WorkflowStepStatus {
  if (hasAwaitingConfirm(stepKey, task, completedSteps)) return 'awaiting_confirm'
  if (completedSteps.has(stepKey)) return 'completed'

  if (task.status === 'failed') {
    const failedKey = resolveFailedStepKey(task, completedSteps)
    if (stepKey === failedKey) return 'failed'
    return 'pending'
  }

  if (runningStepKey === stepKey) return 'running'
  return 'pending'
}

function latestEventForStep(task: ReviewPlusTaskDetail, stepKey: string) {
  const step = REVIEW_PLUS_PIPELINE_STEPS.find((item) => item.step_key === stepKey)
  if (!step) return null
  const candidates = sortedEvents(task).filter((event) => {
    const type = String(event.type || '')
    return type === step.completeEvent || type === step.startEvent || type.includes(stepKey)
  })
  return candidates.length > 0 ? candidates[candidates.length - 1] : null
}

function traceStatusForAgent(agentId: string, task: ReviewPlusTaskDetail): WorkflowStepStatus {
  const trace = (task.agent_run_traces || []).find((item) => item.agent_id === agentId)
  if (!trace) return 'pending'
  if (trace.status === 'completed') return 'completed'
  if (trace.status === 'failed') return 'failed'
  return 'running'
}

function buildHarnessSubflowNodes(task: ReviewPlusTaskDetail, stepKey: ReviewPlusPipelineStepKey): WorkflowGraphNode[] {
  const plan = getHarnessPlan(task)
  const agentIds = plan?.selected_agent_ids || []
  if (!agentIds.length || stepKey !== 'item_review') return []

  const parentStepId = `node_${stepKey}`
  const dispatchId = `node_${stepKey}_dispatch`
  const mergeId = `node_${stepKey}_merge`
  const nodes: WorkflowGraphNode[] = [
    {
      node_id: dispatchId,
      step_key: `${stepKey}_dispatch`,
      label: '总师阵容规划',
      node_type: 'dispatch',
      status: traceStatusForAgent('chief_orchestrator_agent', task),
      agent_ids: ['chief_orchestrator_agent'],
      agent_run_ids: [],
      blocked_reason: '',
      parent_node_id: parentStepId,
    },
    {
      node_id: mergeId,
      step_key: `${stepKey}_merge`,
      label: '审查裁决汇聚',
      node_type: 'merge',
      status: traceStatusForAgent('review_plus_arbiter_agent', task),
      agent_ids: ['review_plus_arbiter_agent'],
      agent_run_ids: [],
      blocked_reason: '',
      parent_node_id: parentStepId,
    },
  ]

  agentIds.forEach((agentId, index) => {
    nodes.push({
      node_id: `node_${stepKey}_agent_${index}`,
      step_key: agentId,
      label: formatAgentLabel(agentId),
      node_type: 'agent',
      status: traceStatusForAgent(agentId, task),
      agent_ids: [agentId],
      agent_run_ids: [],
      blocked_reason: '',
      parent_node_id: dispatchId,
    })
  })

  return nodes
}

function buildHarnessSubflowEdges(stepKey: ReviewPlusPipelineStepKey, agentCount: number) {
  if (agentCount <= 0) return []
  const dispatchId = `node_${stepKey}_dispatch`
  const mergeId = `node_${stepKey}_merge`
  const edges = [
    { edge_id: `edge-${stepKey}-dispatch-merge`, source: dispatchId, target: mergeId },
  ]
  for (let index = 0; index < agentCount; index += 1) {
    const agentId = `node_${stepKey}_agent_${index}`
    edges.push({ edge_id: `edge-${stepKey}-dispatch-agent-${index}`, source: dispatchId, target: agentId })
    edges.push({ edge_id: `edge-${stepKey}-agent-merge-${index}`, source: agentId, target: mergeId })
  }
  return edges
}

export function buildReviewPlusWorkflowGraph(task: ReviewPlusTaskDetail): WorkflowGraph {
  const completedSteps = getReviewPlusCompletedStepKeys(task)
  const runningStepKey = resolveRunningWorkflowStepKey(task, completedSteps)
  const harnessPlan = getHarnessPlan(task)
  const harnessAgentIds = harnessPlan?.selected_agent_ids || []

  const nodes: WorkflowGraphNode[] = REVIEW_PLUS_PIPELINE_STEPS.map((step, index) => {
    const status = stepStatus(step.step_key, task, completedSteps, runningStepKey)
    const latest = latestEventForStep(task, step.step_key)
    const payload = (latest?.payload || {}) as Record<string, unknown>
    const blockedReason = String(payload.error || payload.detail || payload.message || '')
    const outputSummary = buildReviewPlusStepOutputSummary(
      step.step_key as ReviewPlusPipelineStepKey,
      task,
      status,
      payload,
    )
    const stepAgentIds = step.step_key === 'item_review'
      ? harnessAgentIds
      : []
    return {
      node_id: `node_${step.step_key}`,
      step_key: step.step_key,
      label: step.label,
      node_type: 'step',
      status,
      agent_ids: stepAgentIds,
      agent_run_ids: [],
      blocked_reason: status === 'failed' ? blockedReason : '',
      output_summary: outputSummary || step.description,
      started_at: latest?.created_at,
      completed_at: status === 'completed' ? latest?.created_at : undefined,
      layout_hint: index === 0 ? 'start' : index === REVIEW_PLUS_PIPELINE_STEPS.length - 1 ? 'end' : undefined,
    }
  })

  const subflowNodes = REVIEW_PLUS_PIPELINE_STEPS.flatMap((step) =>
    buildHarnessSubflowNodes(task, step.step_key as ReviewPlusPipelineStepKey),
  )
  nodes.push(...subflowNodes)

  let filteredEdges = REVIEW_PLUS_PIPELINE_STEPS.slice(0, -1).map((step, index) => ({
    edge_id: `edge-${step.step_key}`,
    source: `node_${step.step_key}`,
    target: `node_${REVIEW_PLUS_PIPELINE_STEPS[index + 1].step_key}`,
  }))

  const extraEdges: Array<{ edge_id: string; source: string; target: string }> = []

  if (harnessAgentIds.length > 0) {
    const subflowSteps: ReviewPlusPipelineStepKey[] = ['item_review']
    subflowSteps.forEach((stepKey) => {
      // 1. Connect parent step node to dispatch subnode
      extraEdges.push({
        edge_id: `edge-${stepKey}-to-dispatch`,
        source: `node_${stepKey}`,
        target: `node_${stepKey}_dispatch`,
      })

      // 2. Connect merge subnode to the next step node
      const currentStepIdx = REVIEW_PLUS_PIPELINE_STEPS.findIndex((step) => step.step_key === stepKey)
      if (currentStepIdx !== -1 && currentStepIdx < REVIEW_PLUS_PIPELINE_STEPS.length - 1) {
        const nextStepKey = REVIEW_PLUS_PIPELINE_STEPS[currentStepIdx + 1].step_key
        extraEdges.push({
          edge_id: `edge-${stepKey}-merge-to-next`,
          source: `node_${stepKey}_merge`,
          target: `node_${nextStepKey}`,
        })

        // 3. Filter out the original direct serial edge
        filteredEdges = filteredEdges.filter(
          (edge) => !(edge.source === `node_${stepKey}` && edge.target === `node_${nextStepKey}`)
        )
      }
    })
  }

  const harnessEdges = ['item_review'].flatMap((stepKey) =>
    buildHarnessSubflowEdges(stepKey as ReviewPlusPipelineStepKey, harnessAgentIds.length),
  )

  return {
    title: REVIEW_PLUS_TERMS.flowTitle,
    description: task.name,
    nodes,
    edges: [...filteredEdges, ...extraEdges, ...harnessEdges],
  }
}

export function resolveActiveWorkflowStepKey(task: ReviewPlusTaskDetail): string {
  const completedSteps = getReviewPlusCompletedStepKeys(task)
  if (task.status === 'completed' || completedSteps.has('report_composition')) {
    return 'report_composition'
  }

  if (task.status === 'failed') {
    return resolveFailedStepKey(task, completedSteps)
  }

  return resolveRunningWorkflowStepKey(task, completedSteps)
    || nextIncompleteStepKey(completedSteps)
}
