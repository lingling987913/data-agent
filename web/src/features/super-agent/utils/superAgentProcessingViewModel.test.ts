import { describe, expect, it } from 'vitest'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import type { SuperAgentRun } from '@/features/super-agent/types'
import { WORKFLOW_DAG_EDGE_TYPE } from '@aqua/workflow-core'
import {
  buildNodeDetail,
  buildNodeDetailPanelModel,
  buildSuperAgentFlowGraph,
  buildSuperAgentProcessingViewModel,
  capNodeStatusByDependencies,
  formatExecutionModeLabel,
  GNC_COMMITTEE_COMMITTEE_STEP_INDEX,
  GNC_WORKFLOW_STEP_DEFS,
  resolveGncCommitteeDeepParallelTasks,
  resolveGncInitialExpandedTeamLeadIds,
  resolveLaneDeepParallelTasks,
  resolveReviewExecutionMode,
  resolveReviewOutcomeStatus,
  resolveSuperAgentNodeLlmTraces,
  reviewProcessHiddenPrepNodeIds,
  normalizeSuperAgentCanvasNodeId,
  WORKFLOW_DAG_EDGE_TYPE as VIEW_MODEL_EDGE_TYPE,
} from './superAgentProcessingViewModel'
import { REVIEW_PLUS_PROCESS_STAGE_DEFS } from '@/features/review-process-model/adapters/reviewPlusProcessAdapter'

function smartCommitteeRun(): SuperAgentRun {
  return {
    run_id: 'rda_test',
    name: '智能审查任务',
    objective: '审查单份 PDF',
    status: 'running',
    processing_mode: 'OPTIMAL',
    input_mode: 'existing_review_plus',
    source_review_id: 'rp_test',
    requested_route: 'smart',
    review_mode: 'full',
    materials: [{ name: 'single.pdf', file_type: 'application/pdf' }],
    route_decision: {
      route: 'smart',
      confidence: 1,
      reasons: ['用户显式指定 route=smart'],
      required_tools: ['bootstrap_review_plus_task', 'smart_review_committee'],
      skipped_tools: [],
      gnc_review_id: '',
    },
    classification: {
      doc_type: '单份 PDF',
      domain: '通用文档',
      recommended_route: 'smart',
      reason: '槽位不完整，走智能审查',
      review_plus_ready: false,
      missing_slots: ['审查规则/检查单', '研制任务书'],
      review_plan: {
        route: 'smart',
        recommended_route: 'smart',
        review_mode_selection: 'smart',
        required_tools: ['bootstrap_review_plus_task', 'smart_review_committee'],
        skipped_tools: [],
        bootstrap_review_plus: true,
        run_structure_parse: false,
        reuse_review_plus_parse: true,
        confidence: 1,
        reasons: [],
        downgrade_reasons: [],
        review_plus_ready: false,
        smart_primary_path: 'smart_committee',
      } as never,
      smart_review_plan: {
        primary_path: 'smart_committee',
        task_specs: [
          {
            task_id: 'format_gate:document_consistency_reviewer',
            kind: 'format_gate',
            specialist_id: 'document_consistency_reviewer',
            title: '文档一致性审查 Agent',
          },
          {
            task_id: 'smart_specialist:risk_issue_reviewer',
            kind: 'smart_specialist_review',
            specialist_id: 'risk_issue_reviewer',
            title: '风险问题审查 Agent',
          },
          {
            task_id: 'arbiter_summary:committee',
            kind: 'arbiter_summary',
            specialist_id: 'smart_arbiter',
            title: '总师综合评判',
          },
        ],
      },
    },
    structured_bundle: {
      materials: [],
      parser_traces: [],
      section_tree: {},
      evidence_pool: {},
      chunks: [],
      check_items: [],
      stats: { material_count: 1, section_count: 6, evidence_count: 68, check_item_count: 3 },
      warnings: [],
    },
    review_plus_result: {},
    gnc_review_result: {},
    trace_report: { degradation_summary: [] },
    quality_report: {
      parse_quality_score: 0,
      evidence_quality_score: 0,
      traceability_score: 0,
      consistency_score: 0,
      stability_score: 0,
      overall_score: 0,
      expert_consensus_score: 0,
      evidence_sufficiency_score: 0,
      conflict_detection_score: 0,
      warnings: [],
      human_confirmation_required: false,
    },
    skill_traces: [
      {
        skill_id: 'smart_review_committee',
        agent_id: 'data-agent:smart_review_orchestrator',
        tool_name: 'run_smart_review_committee',
        status: 'running',
        input_summary: { primary_path: 'smart_committee' },
        output_summary: {},
        warnings: [],
        elapsed_ms: 0,
      },
    ],
    completed_steps: ['structure_materials', 'bootstrap_review_plus_task'],
    error: '',
    created_at: '',
    updated_at: '',
  } as unknown as SuperAgentRun
}

function reviewPlusRun(): SuperAgentRun {
  return {
    ...smartCommitteeRun(),
    requested_route: 'review_plus',
    route_decision: {
      route: 'review_plus',
      confidence: 0.9,
      reasons: ['材料齐全'],
      required_tools: ['run_review_plus'],
      skipped_tools: [],
      gnc_review_id: '',
    },
    classification: {
      doc_type: '型号文件组',
      domain: '航天型号',
      recommended_route: 'review_plus',
      reason: '走文件组审查',
      review_plus_ready: true,
      review_plan: { smart_primary_path: 'review_plus' } as never,
    },
    skill_traces: [
      {
        skill_id: 'run_review_plus',
        agent_id: 'review_plus',
        status: 'running',
        input_summary: {},
        output_summary: { finding_count: 2 },
        warnings: [],
        elapsed_ms: 0,
      },
    ],
  } as unknown as SuperAgentRun
}

function runningReviewPlusTask(): ReviewPlusTaskDetail {
  return {
    review_plus_id: 'rp_test',
    name: '载体任务',
    status: 'reviewing',
    materials: [],
    check_items: [],
    findings: [],
    events: [{ type: 'item_review_started', sequence: 1, created_at: '' }],
    created_at: '',
    updated_at: '',
  } as ReviewPlusTaskDetail
}

describe('superAgentProcessingViewModel parallel flow graph', () => {
  it('renders review-focused main chain, dispatch, merge, and lane branches on the canvas', () => {
    const graph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    const stepIds = graph.nodes.filter((node) => node.node_type === 'step').map((node) => node.node_id)
    expect(stepIds).toEqual(['node_launch', 'node_gate_format', 'node_synthesize'])
    expect(reviewProcessHiddenPrepNodeIds().every((id) => !graph.nodes.some((node) => node.node_id === id))).toBe(true)
    expect(graph.nodes.some((node) => node.node_id === 'node_dispatch')).toBe(true)
    expect(graph.nodes.some((node) => node.node_id === 'node_merge')).toBe(true)
    expect(graph.nodes.some((node) => node.node_id.startsWith('node_lane_'))).toBe(true)
  })

  it('renders format gate node between dispatch and experts for smart committee', () => {
    const graph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    const gateNode = graph.nodes.find((node) => node.node_id === 'node_gate_format')
    const expertNode = graph.nodes.find((node) => node.label === '风险问题审查 Agent')

    expect(gateNode).toBeTruthy()
    expect(gateNode?.label).toMatch(/格式预审|送审材料门禁/)
    expect(gateNode?.node_type).toBe('step')
    expect(gateNode?.subtitle).toBeTruthy()
    expect(gateNode?.subtitle).not.toBe('检查材料完整性与可审查性')
    expect(expertNode?.node_type).toBe('agent')
    expect(graph.edges.some((edge) => edge.source === 'node_dispatch' && edge.target === 'node_gate_format')).toBe(true)
    expect(graph.edges.some((edge) => edge.source === 'node_gate_format' && edge.target === expertNode?.node_id)).toBe(true)
    expect(graph.edges.some((edge) => edge.source === 'node_dispatch' && edge.target === expertNode?.node_id)).toBe(false)
    expect(graph.edges.some((edge) => edge.source === 'node_dispatch' && edge.target === 'node_merge')).toBe(false)
    expect(graph.nodes.some((node) => node.label === '文档一致性审查 Agent')).toBe(false)
  })

  it('allows dispatch to merge fallback only without gate and expert lanes', () => {
    const run = {
      ...smartCommitteeRun(),
      classification: {
        ...(smartCommitteeRun().classification as object),
        smart_review_plan: { primary_path: 'smart_committee', task_specs: [] },
      },
    } as unknown as SuperAgentRun
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    expect(graph.nodes.some((node) => node.node_id === 'node_gate_format')).toBe(false)
    expect(graph.nodes.filter((node) => node.node_id.startsWith('node_lane_'))).toHaveLength(0)
    expect(graph.edges.some((edge) => edge.source === 'node_dispatch' && edge.target === 'node_merge')).toBe(true)
  })

  it('does not add dispatch to merge fallback when gate exists without expert lanes yet', () => {
    const run = {
      ...smartCommitteeRun(),
      classification: {
        ...(smartCommitteeRun().classification as object),
        smart_review_plan: {
          primary_path: 'smart_committee',
          task_specs: [
            {
              task_id: 'format_gate:document_consistency_reviewer',
              kind: 'format_gate',
              specialist_id: 'document_consistency_reviewer',
              title: '文档一致性审查 Agent',
            },
          ],
        },
      },
    } as unknown as SuperAgentRun
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    expect(graph.nodes.some((node) => node.node_id === 'node_gate_format')).toBe(true)
    expect(graph.edges.some((edge) => edge.source === 'node_dispatch' && edge.target === 'node_merge')).toBe(false)
  })

  it('labels smart committee and review-plus synthesize node as quality review and report', () => {
    const smartGraph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    const reviewGraph = buildSuperAgentFlowGraph(reviewPlusRun(), runningReviewPlusTask())
    expect(smartGraph.nodes.find((node) => node.node_id === 'node_synthesize')?.label).toBe('质量复核与报告')
    expect(reviewGraph.nodes.find((node) => node.node_id === 'node_synthesize')?.label).toBe('质量复核与报告')
  })

  it('uses concise smart committee lane labels without debug semantics', () => {
    const graph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    const labels = graph.nodes.map((node) => node.label)
    const viewModel = buildSuperAgentProcessingViewModel(smartCommitteeRun(), { reviewPlusTask: runningReviewPlusTask() })
    expect(labels).toContain('智能调度')
    expect(labels).toContain('审查准备')
    expect(labels).toContain('总师综合评判')
    expect(labels).not.toContain('智能审查组会')
    expect(labels).not.toContain('动态专家组')
    expect(labels).not.toContain('专家任务调度')
    expect(labels).not.toContain('TaskBoard 编排')
    expect(labels).not.toContain('文件组审查')
    expect(labels).not.toContain('一致性审查')
    expect(labels).not.toContain('风险审查')
    expect(labels.join(' ')).not.toMatch(/TaskSpec|TaskBoard|execution_mode/i)
    const dispatchNode = graph.nodes.find((node) => node.node_id === 'node_dispatch')
    expect(dispatchNode?.label).toMatch(/智能调度|总师组会/)
    const delegateChildren = viewModel.processItems.find((item) => item.id === 'delegate')?.children || []
    expect(delegateChildren.some((child) => child.title === '风险问题审查 Agent')).toBe(true)
    expect(delegateChildren.every((child) => !child.details?.some((line) => line.startsWith('接收材料')))).toBe(true)
    expect(labels).not.toContain('文档一致性审查 Agent')
  })

  it('does not put raw execution summary or long JSON into node subtitles', () => {
    const run = {
      ...smartCommitteeRun(),
      skill_traces: [
        {
          skill_id: 'smart_review_committee',
          status: 'running',
          input_summary: {},
          output_summary: {
            execution_mode_summary: { harness_count: 3, deterministic_count: 1 },
            note: 'x'.repeat(200),
          },
          warnings: [],
          elapsed_ms: 0,
        },
      ],
    } as unknown as SuperAgentRun
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    for (const node of graph.nodes) {
      const subtitle = node.subtitle || ''
      expect(subtitle).not.toMatch(/execution_mode_summary/)
      expect(subtitle).not.toMatch(/TaskSpec|TaskBoard|execution_mode|raw JSON/i)
      expect(subtitle.length).toBeLessThanOrEqual(120)
      expect(subtitle).not.toMatch(/^\{/)
    }
  })

  it('uses orthogonal smoothstep edges in workflow DAG viewer', () => {
    expect(WORKFLOW_DAG_EDGE_TYPE).toBe('smoothstep')
    expect(VIEW_MODEL_EDGE_TYPE).toBe('smoothstep')
  })

  it('renders one canvas node per smart committee expert without lifecycle triplets', () => {
    const graph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    const labels = graph.nodes.map((node) => node.label)
    expect(labels).toContain('风险问题审查 Agent')
    expect(labels).not.toContain('接收材料')
    expect(labels).not.toContain('执行审查')
    expect(labels).not.toContain('输出结论')
    expect(labels.filter((label) => label === '风险问题审查 Agent')).toHaveLength(1)
  })

  it('shows chief arbiter merge node on smart committee canvas', () => {
    const graph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    const mergeNode = graph.nodes.find((node) => node.node_id === 'node_merge')
    expect(mergeNode?.label).toBe('总师综合评判')
    expect(mergeNode?.subtitle).toMatch(/证据覆盖|严重度|置信度/)
  })

  it('does not render blueprint placeholder experts without task_specs', () => {
    const run = {
      ...smartCommitteeRun(),
      classification: {
        ...(smartCommitteeRun().classification as object),
        smart_review_plan: { primary_path: 'smart_committee' },
      },
    } as unknown as SuperAgentRun
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const laneNodes = graph.nodes.filter((node) => node.node_id.startsWith('node_lane_'))
    expect(laneNodes).toHaveLength(0)
    expect(graph.nodes.find((node) => node.node_id === 'node_dispatch')?.label).toMatch(/智能调度|总师组会/)
    expect(graph.nodes.some((node) => node.label === '一致性审查')).toBe(false)
    expect(graph.nodes.some((node) => node.label === '风险审查')).toBe(false)
  })

  it('keeps deep parallel tasks out of canvas nodes and only in detail model', () => {
    const graph = buildSuperAgentFlowGraph(reviewPlusRun(), runningReviewPlusTask())
    const laneHead = graph.nodes.find((node) => node.node_id === 'node_lane_review-plus')
    expect(laneHead).toBeTruthy()
    const deepTasks = resolveLaneDeepParallelTasks('node_lane_review-plus_step_3', reviewPlusRun(), {
      reviewPlusTask: runningReviewPlusTask(),
    })
    expect(deepTasks.map((task) => task.label)).toEqual([
      '符合性判读子任务 · 条款核验',
      '符合性判读子任务 · 证据核验',
      '符合性判读子任务 · 交叉核验',
    ])
    expect(graph.nodes.some((node) => node.label === '条款核验')).toBe(false)
    expect(graph.nodes.some((node) => node.label === '证据核验')).toBe(false)
  })

  it('resolveReviewExecutionMode distinguishes smart committee from review_plus', () => {
    expect(resolveReviewExecutionMode(smartCommitteeRun())).toBe('smart_committee')
    expect(resolveReviewExecutionMode(reviewPlusRun())).toBe('review_plus')
  })
})

const LIFECYCLE_CANVAS_LABELS = ['接收', '回传', '返回', '接收材料', '执行审查', '输出结论']

function collectCanvasNodeText(graph: ReturnType<typeof buildSuperAgentFlowGraph>): string[] {
  return graph.nodes.flatMap((node) => [node.label, node.subtitle || ''])
}

describe('superAgentProcessingViewModel non-smart lane business labels', () => {
  it('review-plus lane uses user-facing stages without lifecycle nodes on canvas', () => {
    const graph = buildSuperAgentFlowGraph(reviewPlusRun(), runningReviewPlusTask())
    const laneStepLabels = graph.nodes
      .filter((node) => node.node_id.startsWith('node_lane_review-plus_step_'))
      .map((node) => node.label)
    expect(laneStepLabels).toEqual(REVIEW_PLUS_PROCESS_STAGE_DEFS.map((stage) => stage.label))
    const laneStepTexts = graph.nodes
      .filter((node) => node.node_id.startsWith('node_lane_review-plus_step_'))
      .flatMap((node) => [node.subtitle || ''])
    for (const text of laneStepTexts) {
      expect(LIFECYCLE_CANVAS_LABELS.some((term) => text.includes(term))).toBe(false)
    }
    expect(graph.nodes.some((node) => node.node_id.startsWith('node_lane_quality'))).toBe(false)
  })

  it('hides structuring lane for review_plus-only runs', () => {
    const graph = buildSuperAgentFlowGraph(reviewPlusRun(), runningReviewPlusTask())
    expect(graph.nodes.some((node) => node.node_id.startsWith('node_lane_structuring'))).toBe(false)
  })

  it('gnc lane uses six user-facing stages without lifecycle nodes on canvas', () => {
    const run = {
      ...reviewPlusRun(),
      requested_route: 'gnc_review_only',
      route_decision: {
        route: 'gnc_review_only',
        confidence: 0.9,
        reasons: ['GNC 专项'],
        required_tools: ['run_gnc_review'],
        skipped_tools: [],
        gnc_review_id: 'gnc_test',
      },
      skill_traces: [
        {
          skill_id: 'run_gnc_review',
          agent_id: 'gnc',
          status: 'running',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
      ],
    } as unknown as SuperAgentRun
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const gncStepLabels = graph.nodes
      .filter((node) => node.node_id.startsWith('node_lane_gnc_step_'))
      .map((node) => node.label)
    expect(gncStepLabels).toEqual([
      '材料接收与任务建立',
      '文档解析与证据准备',
      '专家组审查（AD/AC/规则）',
      '问题合稿与 RID 台账',
      '总师裁定与仲裁',
      '报告归档 / 闭环',
    ])
    expect(gncStepLabels).not.toEqual(GNC_WORKFLOW_STEP_DEFS.map((step) => step.label))
    for (const label of gncStepLabels) {
      expect(LIFECYCLE_CANVAS_LABELS.includes(label)).toBe(false)
    }
    const canvasText = collectCanvasNodeText(graph).join(' ')
    expect(canvasText).not.toMatch(/TaskSpec|execution_mode|raw trace/i)
  })

  it('smart committee exposes generic review stages in process subflow', () => {
    const viewModel = buildSuperAgentProcessingViewModel(smartCommitteeRun(), {
      reviewPlusTask: runningReviewPlusTask(),
    })
    const reviewItem = viewModel.processItems.find((item) => item.id === 'review_prepare')
    const delegateChildren = viewModel.processItems.find((item) => item.id === 'delegate')?.children || []
    const expertLane = delegateChildren.find((child) => child.title.includes('风险问题审查 Agent'))
    expect(expertLane).toBeTruthy()
    expect(reviewItem?.details?.some((line) => line.includes('审查路径'))).toBe(true)
    const graph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    const laneStepLabels = graph.nodes
      .filter((node) => node.node_id.startsWith('node_lane_') && node.node_id.includes('_step_'))
      .map((node) => node.label)
    expect(laneStepLabels).toContain('风险问题审查 Agent')
    expect(laneStepLabels).not.toContain('送审材料接收')
  })

  it('gnc committee stage exposes AD/AC subflow tasks in detail', () => {
    const run = {
      ...reviewPlusRun(),
      requested_route: 'gnc_review_only',
      route_decision: {
        route: 'gnc_review_only',
        confidence: 0.9,
        reasons: ['GNC 专项'],
        required_tools: ['run_gnc_review'],
        skipped_tools: [],
        gnc_review_id: 'gnc_test',
      },
      skill_traces: [
        {
          skill_id: 'run_gnc_review',
          agent_id: 'gnc',
          status: 'running',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
      ],
      gnc_review_result: {
        status: 'running',
        review_scope: 'ad_ac',
        discipline_reviews: {
          quality_engineer: { completed: true, findings: [{ title: '模板章节缺失' }] },
          fdir_specialist: { status: 'failed', completed: false, error: 'model unavailable' },
        },
      },
    } as unknown as SuperAgentRun
    const nodeId = `node_lane_gnc_step_${GNC_COMMITTEE_COMMITTEE_STEP_INDEX}`
    const deepTasks = resolveGncCommitteeDeepParallelTasks(run)
    expect(deepTasks.length).toBeGreaterThan(0)
    expect(deepTasks.some((task) => task.label.includes('AD'))).toBe(true)
    expect(deepTasks.some((task) => task.label.includes('AC'))).toBe(true)

    const detail = buildNodeDetail(nodeId, run)
    const unitSection = detail?.sections.find((section) => section.title === 'AD/AC 子流程')
    expect(unitSection?.lines.some((line) => line.includes('AD 姿态确定'))).toBe(true)
    expect(unitSection?.lines.some((line) => line.includes('AC 姿态控制'))).toBe(true)

    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const mainCanvasLabels = graph.nodes.map((node) => node.label).join(' ')
    expect(mainCanvasLabels).not.toContain('送审材料接收')
    expect(mainCanvasLabels).toContain('专家组审查（AD/AC/规则）')
  })

  it('renders AD/AC team_lead nested nodes under gnc committee step on canvas', () => {
    const run = {
      ...reviewPlusRun(),
      requested_route: 'gnc_review_only',
      route_decision: {
        route: 'gnc_review_only',
        confidence: 0.9,
        reasons: ['GNC 专项'],
        required_tools: ['run_gnc_review'],
        skipped_tools: [],
        gnc_review_id: 'gnc_test',
      },
      skill_traces: [
        {
          skill_id: 'run_gnc_review',
          agent_id: 'gnc',
          status: 'running',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
      ],
      gnc_review_result: {
        status: 'running',
        review_scope: 'ad_ac',
        ad_group_result: {
          conclusion: { verdict: 'conditionally_approved', summary: 'AD 组完成' },
          stage_results: {
            req_err: { status: 'completed', finding_count: 0, rule_judgment_count: 2, blocking_flags: [] },
            algorithm: {
              status: 'blocked',
              finding_count: 1,
              rule_judgment_count: 3,
              blocking_flags: ['algorithm:not_checked_rules'],
            },
          },
        },
        ac_group_result: {
          conclusion: { verdict: 'approved', summary: 'AC 组通过' },
          stage_results: {
            control_law: { status: 'completed', finding_count: 0, rule_judgment_count: 4, blocking_flags: [] },
          },
        },
      },
    } as unknown as SuperAgentRun

    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const adTeamLead = graph.nodes.find((node) => node.node_id === 'node_lane_gnc_committee_ad_group')
    const acTeamLead = graph.nodes.find((node) => node.node_id === 'node_lane_gnc_committee_ac_group')
    expect(adTeamLead?.node_type).toBe('team_lead')
    expect(acTeamLead?.node_type).toBe('team_lead')
    expect(adTeamLead?.label).toBe('AD 姿态确定')
    expect(acTeamLead?.label).toBe('AC 姿态控制')

    const adUnits = graph.nodes.filter(
      (node) => node.node_id.startsWith('node_lane_gnc_committee_ad_group_') && node.node_type === 'agent',
    )
    const acUnits = graph.nodes.filter(
      (node) => node.node_id.startsWith('node_lane_gnc_committee_ac_group_') && node.node_type === 'agent',
    )
    expect(adUnits.length).toBeGreaterThan(0)
    expect(acUnits.length).toBeGreaterThan(0)
    expect(adUnits.every((node) => node.parent_node_id === 'node_lane_gnc_committee_ad_group')).toBe(true)
    expect(acUnits.every((node) => node.parent_node_id === 'node_lane_gnc_committee_ac_group')).toBe(true)

    const committeeStepId = `node_lane_gnc_step_${GNC_COMMITTEE_COMMITTEE_STEP_INDEX}`
    expect(graph.edges.some((edge) => edge.source === committeeStepId && edge.target === 'node_lane_gnc_committee_ad_group')).toBe(true)
    expect(graph.edges.some((edge) => edge.source === committeeStepId && edge.target === 'node_lane_gnc_committee_ac_group')).toBe(true)
    expect(graph.edges.some((edge) => (
      edge.target === 'node_lane_gnc_step_3'
      && edge.source.startsWith('node_lane_gnc_committee_ad_group_')
    ))).toBe(true)
    expect(graph.edges.some((edge) => (
      edge.target === 'node_lane_gnc_step_3'
      && (edge.source === 'node_lane_gnc_committee_ac_group' || edge.source.startsWith('node_lane_gnc_committee_ac_group_'))
    ))).toBe(true)
  })

  it('forks AD timing/install from the same phase source instead of serial chain', () => {
    const run = {
      ...reviewPlusRun(),
      requested_route: 'gnc_review_only',
      route_decision: {
        route: 'gnc_review_only',
        confidence: 0.9,
        reasons: ['GNC 专项'],
        required_tools: ['run_gnc_review'],
        skipped_tools: [],
        gnc_review_id: 'gnc_test',
      },
      skill_traces: [
        {
          skill_id: 'run_gnc_review',
          agent_id: 'gnc',
          status: 'running',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
      ],
      gnc_review_result: {
        status: 'running',
        review_scope: 'ad_only',
        ad_group_result: {
          conclusion: { verdict: 'pending', summary: 'AD 组进行中' },
          stage_results: {
            req_err: { status: 'completed', finding_count: 0, rule_judgment_count: 1, blocking_flags: [] },
            timing: { status: 'running', finding_count: 0, rule_judgment_count: 0, blocking_flags: [] },
            install: { status: 'pending', finding_count: 0, rule_judgment_count: 0, blocking_flags: [] },
          },
        },
      },
    } as unknown as SuperAgentRun

    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const reqErrId = 'node_lane_gnc_committee_ad_group_req_err'
    const timingId = 'node_lane_gnc_committee_ad_group_timing'
    const installId = 'node_lane_gnc_committee_ad_group_install'
    const joinId = 'node_lane_gnc_committee_ad_group_join_1'

    expect(graph.nodes.some((node) => node.node_id === joinId && node.node_type === 'merge')).toBe(true)
    expect(graph.edges.some((edge) => edge.source === reqErrId && edge.target === timingId)).toBe(true)
    expect(graph.edges.some((edge) => edge.source === reqErrId && edge.target === installId)).toBe(true)
    expect(graph.edges.some((edge) => edge.source === timingId && edge.target === installId)).toBe(false)
    expect(graph.edges.some((edge) => edge.source === timingId && edge.target === joinId)).toBe(true)
    expect(graph.edges.some((edge) => edge.source === installId && edge.target === joinId)).toBe(true)

    const timingNode = graph.nodes.find((node) => node.node_id === timingId)
    expect(timingNode?.subtitle || '').toContain('并行')
  })

  it('builds AD/AC nested nodes from committee_review trace when top-level ad_group_result is absent', () => {
    const run = {
      ...reviewPlusRun(),
      requested_route: 'gnc_review_only',
      route_decision: {
        route: 'gnc_review_only',
        confidence: 0.9,
        reasons: ['GNC 专项'],
        required_tools: ['run_gnc_review'],
        skipped_tools: [],
        gnc_review_id: 'gnc_test',
      },
      skill_traces: [
        {
          skill_id: 'run_gnc_review',
          agent_id: 'gnc',
          status: 'completed',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
      ],
      gnc_review_result: {
        status: 'completed',
        review_scope: 'ad_ac',
        traces: [
          {
            step: 'committee_review',
            summary: {
              discipline_reviews: {
                ad_group: {
                  conclusion: { verdict: 'conditionally_approved', summary: 'AD 组完成' },
                  stage_results: {
                    req_err: { status: 'completed', finding_count: 0, rule_judgment_count: 1, blocking_flags: [] },
                  },
                },
                ac_group: {
                  conclusion: { verdict: 'approved', summary: 'AC 组通过' },
                  stage_results: {
                    control_law: { status: 'completed', finding_count: 0, rule_judgment_count: 2, blocking_flags: [] },
                  },
                },
              },
              findings: [{ title: '示例发现' }],
            },
          },
        ],
      },
    } as unknown as SuperAgentRun

    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    expect(graph.nodes.find((node) => node.node_id === 'node_lane_gnc_committee_ad_group')?.label).toBe('AD 姿态确定')
    expect(graph.nodes.find((node) => node.node_id === 'node_lane_gnc_committee_ac_group')?.label).toBe('AC 姿态控制')
    expect(graph.nodes.some((node) => node.node_id === 'node_lane_gnc_committee_ad_group_req_err')).toBe(true)
    expect(graph.nodes.some((node) => node.node_id === 'node_lane_gnc_committee_ac_group_control_law')).toBe(true)

    const viewModel = buildSuperAgentProcessingViewModel(run)
    expect(viewModel.initialExpandedTeamLeadIds).toEqual(expect.arrayContaining([
      'node_lane_gnc',
      'node_lane_gnc_committee_ad_group',
      'node_lane_gnc_committee_ac_group',
    ]))
    expect(resolveGncInitialExpandedTeamLeadIds(run)).toEqual(viewModel.initialExpandedTeamLeadIds)

    const gncLane = viewModel.flowGraph.lanes.find((lane) => lane.id === 'gnc')
    const committeeNode = gncLane?.nodes[GNC_COMMITTEE_COMMITTEE_STEP_INDEX]
    expect(committeeNode?.subtitle || '').toMatch(/AD 姿态确定/)
    expect(committeeNode?.subtitle || '').toMatch(/AC 姿态控制/)
    expect(committeeNode?.subtitle || '').not.toMatch(/四专家/)
  })

  it('renders AD/AC placeholder nested nodes when gnc review started but result not synced', () => {
    const run = {
      ...reviewPlusRun(),
      requested_route: 'gnc_review_only',
      route_decision: {
        route: 'gnc_review_only',
        confidence: 0.9,
        reasons: ['GNC 专项'],
        required_tools: ['run_gnc_review'],
        skipped_tools: [],
        gnc_review_id: 'gnc_test',
      },
      skill_traces: [
        {
          skill_id: 'run_gnc_review',
          agent_id: 'gnc',
          status: 'running',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
      ],
      gnc_review_result: {},
    } as unknown as SuperAgentRun

    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    expect(graph.nodes.find((node) => node.node_id === 'node_lane_gnc_committee_ad_group')?.label).toBe('AD 姿态确定')
    expect(graph.nodes.find((node) => node.node_id === 'node_lane_gnc_committee_ac_group')?.label).toBe('AC 姿态控制')

    const viewModel = buildSuperAgentProcessingViewModel(run)
    expect(viewModel.initialExpandedTeamLeadIds).toEqual(expect.arrayContaining([
      'node_lane_gnc',
      'node_lane_gnc_committee_ad_group',
      'node_lane_gnc_committee_ac_group',
    ]))
  })

  it('does not add gnc committee nested nodes before gnc review route is active', () => {
    const run = {
      ...reviewPlusRun(),
      requested_route: 'gnc_review_only',
      gnc_review_result: {},
    } as unknown as SuperAgentRun

    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    expect(graph.nodes.some((node) => node.node_id.startsWith('node_lane_gnc_committee_'))).toBe(false)
  })

  it('gnc node detail keeps trace output business-readable without raw json or internal ids', () => {
    const run = {
      ...reviewPlusRun(),
      requested_route: 'gnc_review_only',
      route_decision: {
        route: 'gnc_review_only',
        confidence: 0.9,
        reasons: ['GNC 专项'],
        required_tools: ['run_gnc_review'],
        skipped_tools: [],
        gnc_review_id: 'gnc_test',
      },
      skill_traces: [
        {
          skill_id: 'run_gnc_review',
          agent_id: 'data-agent:gnc_internal_orchestrator',
          status: 'completed',
          input_summary: {},
          output_summary: { finding_count: 1 },
          warnings: [],
          elapsed_ms: 0,
        },
      ],
      gnc_review_result: {
        status: 'completed',
        traces: [
          {
            step: 'committee_review',
            summary: JSON.stringify({
              agent_id: 'quality_engineer',
              summary: '四专家结论已汇总',
              finding_count: 1,
            }),
          },
        ],
      },
    } as unknown as SuperAgentRun

    const nodeId = `node_lane_gnc_step_${GNC_COMMITTEE_COMMITTEE_STEP_INDEX}`
    const detail = buildNodeDetail(nodeId, run)
    const panel = buildNodeDetailPanelModel(detail)
    const panelText = [
      ...panel.businessSummary,
      ...panel.reviewSections.flatMap((section) => section.lines),
      ...panel.diagnosticSections.flatMap((section) => section.lines),
    ].join(' ')
    const traceText = resolveSuperAgentNodeLlmTraces(nodeId, run)
      .flatMap((record) => [
        record.agentName,
        record.toolName || '',
        ...record.inputLines,
        ...record.outputLines,
        ...record.findings,
        ...record.warnings,
      ])
      .join(' ')

    expect(panelText).toContain('专家组审查')
    expect(panelText).toContain('四专家结论已汇总')
    expect(`${panelText} ${traceText}`).not.toMatch(/^\{|agent_id|quality_engineer|data-agent:gnc_internal_orchestrator|committee_review/i)
  })

  it('hybrid route shows gnc extension nodes without faking completed status', () => {
    const run = {
      ...reviewPlusRun(),
      requested_route: 'hybrid',
      route_decision: {
        route: 'hybrid',
        confidence: 0.9,
        reasons: ['Review-Plus + GNC'],
        required_tools: ['run_review_plus', 'run_gnc_review'],
        skipped_tools: [],
        gnc_review_id: 'gnc_hybrid',
      },
      skill_traces: [
        {
          skill_id: 'run_review_plus',
          agent_id: 'review_plus',
          status: 'running',
          input_summary: {},
          output_summary: { finding_count: 2 },
          warnings: [],
          elapsed_ms: 0,
        },
        {
          skill_id: 'run_gnc_review',
          agent_id: 'gnc',
          status: 'completed',
          input_summary: {},
          output_summary: { finding_count: 3 },
          warnings: [],
          elapsed_ms: 0,
        },
      ],
      gnc_review_result: {
        status: 'completed',
        findings: [{ title: '控制周期不一致' }],
        conflicts: [{ summary: '接口指标冲突' }],
        chief_decision: { overall_recommendation: '建议补充仿真' },
      },
      classification: {
        ...(reviewPlusRun().classification as object),
        review_plan: { smart_primary_path: 'hybrid' } as never,
      },
    } as unknown as SuperAgentRun
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const gncLabels = graph.nodes
      .filter((node) => node.node_id.startsWith('node_lane_gnc_step_'))
      .map((node) => ({ label: node.label, status: node.status, subtitle: node.subtitle || '' }))
    expect(gncLabels.some((node) => node.label === '专家组审查（AD/AC/规则）')).toBe(true)
    expect(gncLabels.some((node) => node.label === 'GNC 委员会扩展审查')).toBe(true)
    expect(gncLabels.some((node) => node.label === 'GNC 跨文档一致性')).toBe(true)
    const hybridNodes = gncLabels.filter((node) => node.label === 'GNC 委员会扩展审查' || node.label === 'GNC 跨文档一致性')
    for (const node of hybridNodes) {
      expect(node.status).toBe('pending')
      expect(node.subtitle).toMatch(/规划中/)
    }
    expect(graph.nodes.some((node) => node.node_id.startsWith('node_lane_review-plus'))).toBe(true)
  })

  it('keeps smart committee experts as single canvas nodes', () => {
    const graph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    const labels = graph.nodes.map((node) => node.label)
    expect(labels).toContain('风险问题审查 Agent')
    expect(labels.filter((label) => label === '风险问题审查 Agent')).toHaveLength(1)
    expect(labels).not.toContain('接收材料')
    expect(labels).not.toContain('执行审查')
    expect(labels).not.toContain('输出结论')
  })
})

describe('superAgentProcessingViewModel sequential lane status', () => {
  it('does not mark return step completed while item review is still running', () => {
    const run = {
      ...reviewPlusRun(),
      status: 'running',
      skill_traces: [
        {
          skill_id: 'run_review_plus',
          agent_id: 'review_plus',
          status: 'completed',
          input_summary: {},
          output_summary: { finding_count: 12 },
          warnings: [],
          elapsed_ms: 0,
        },
      ],
    } as unknown as SuperAgentRun

    const task = {
      ...runningReviewPlusTask(),
      status: 'reviewing',
      events: [
        { type: 'material_classification_completed', sequence: 1, created_at: '' },
        { type: 'scenario_detection_completed', sequence: 2, created_at: '' },
        { type: 'document_structuring_completed', sequence: 3, created_at: '' },
        { type: 'chief_orchestration_completed', sequence: 4, created_at: '' },
        { type: 'rule_extraction_completed', sequence: 5, created_at: '' },
        { type: 'rule_section_mapping_completed', sequence: 6, created_at: '' },
        { type: 'item_review_started', sequence: 7, created_at: '' },
      ],
    } as ReviewPlusTaskDetail

    const viewModel = buildSuperAgentProcessingViewModel(run, { reviewPlusTask: task })
    const lane = viewModel.flowGraph.lanes.find((item) => item.id === 'review-plus')
    const reviewNode = lane?.nodes.find((node) => node.id === 'review-plus-stage-item_review')
    const returnNode = lane?.nodes.find((node) => node.id === 'review-plus-stage-report_output')

    expect(reviewNode?.status).toBe('running')
    expect(returnNode?.status).toBe('pending')
  })

  it('does not block super agent flow on coverage attention flags without confirm UI', () => {
    const run = {
      ...reviewPlusRun(),
      status: 'running',
      source_review_id: 'rp_test',
    } as unknown as SuperAgentRun

    const task = {
      ...runningReviewPlusTask(),
      status: 'reviewing',
      events: [
        { type: 'material_classification_completed', sequence: 1, created_at: '' },
        { type: 'scenario_detection_completed', sequence: 2, created_at: '' },
        { type: 'document_structuring_completed', sequence: 3, created_at: '' },
        { type: 'chief_orchestration_completed', sequence: 4, created_at: '' },
        { type: 'rule_extraction_completed', sequence: 5, created_at: '' },
        { type: 'rule_section_mapping_completed', sequence: 6, created_at: '' },
        { type: 'item_review_completed', sequence: 7, created_at: '' },
      ],
      coverage_matrix: {
        rows: [{ requires_human_confirmation: true }],
      },
    } as ReviewPlusTaskDetail

    const viewModel = buildSuperAgentProcessingViewModel(run, { reviewPlusTask: task })
    const lane = viewModel.flowGraph.lanes.find((item) => item.id === 'review-plus')
    const processItem = viewModel.processItems
      .find((item) => item.id === 'delegate')
      ?.children
      ?.find((item) => item.id === 'lane-review-plus')

    expect(lane?.status).not.toBe('awaiting_confirm')
    expect(lane?.nodes.find((node) => node.id === 'review-plus-stage-item_review')?.status).toBe('completed')
    expect(processItem?.findings?.some((item) => item.includes('审查结果页复核'))).toBe(true)
  })
})

describe('superAgentProcessingViewModel merge and conclusion consistency', () => {
  it('marks merge completed when run is completed even if a branch awaits confirmation', () => {
    const run = {
      ...reviewPlusRun(),
      status: 'completed',
      review_plus_result: { finding_count: 33 },
      skill_traces: [
        {
          skill_id: 'bootstrap_review_plus_task',
          agent_id: 'bootstrap',
          status: 'completed',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
        {
          skill_id: 'structure_materials',
          agent_id: 'structure',
          status: 'completed',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
        {
          skill_id: 'run_review_plus',
          agent_id: 'review_plus',
          status: 'completed',
          input_summary: {},
          output_summary: { finding_count: 33 },
          warnings: [],
          elapsed_ms: 0,
        },
      ],
    } as unknown as SuperAgentRun

    const task = {
      ...runningReviewPlusTask(),
      status: 'completed',
      events: [
        { type: 'material_classification_completed', sequence: 1, created_at: '' },
        { type: 'document_parsing_completed', sequence: 2, created_at: '' },
        { type: 'document_structuring_completed', sequence: 3, created_at: '' },
        { type: 'chief_orchestration_completed', sequence: 4, created_at: '' },
        { type: 'rule_extraction_completed', sequence: 5, created_at: '' },
        { type: 'rule_section_mapping_completed', sequence: 6, created_at: '' },
        { type: 'item_review_completed', sequence: 7, created_at: '' },
        { type: 'traceability_completed', sequence: 8, created_at: '' },
        { type: 'cross_document_review_completed', sequence: 9, created_at: '' },
        { type: 'report_composition_completed', sequence: 10, created_at: '' },
      ],
      coverage_matrix: {
        rows: [{ requires_human_confirmation: true }],
      },
    } as ReviewPlusTaskDetail

    const viewModel = buildSuperAgentProcessingViewModel(run, { reviewPlusTask: task })
    const merge = viewModel.processItems.find((item) => item.id === 'merge')
    const conclusion = viewModel.processItems.find((item) => item.id === 'conclusion')

    expect(viewModel.flowGraph.merge.status).toBe('completed')
    expect(merge?.status).toBe('completed')
    expect(merge?.summary).toBe('专项分支结果已汇合')
    expect(conclusion?.status).toBe('completed')
  })
})

describe('superAgentProcessingViewModel smart committee labels', () => {
  it('labels running stage with review execution instead of file-group review', () => {
    const viewModel = buildSuperAgentProcessingViewModel(smartCommitteeRun(), {
      reviewPlusTask: runningReviewPlusTask(),
    })

    expect(viewModel.currentStage).toContain('审查执行')
    expect(viewModel.currentStage).not.toContain('文件组审查')
    expect(viewModel.processItems.find((item) => item.id === 'delegate')?.tags).not.toContain('动态专家组')
    expect(viewModel.processItems.some((item) => item.id === 'review_prepare')).toBe(true)
    expect(viewModel.processItems.some((item) => item.id === 'understand')).toBe(false)
  })
})

describe('superAgentProcessingViewModel node detail panel', () => {
  it('shows dispatch business summary instead of tool traces on first screen', () => {
    const run = {
      ...smartCommitteeRun(),
      skill_traces: [
        ...(smartCommitteeRun().skill_traces || []),
        {
          skill_id: 'bootstrap_review_plus_task',
          agent_id: 'data-agent:bootstrap',
          tool_name: 'bootstrap_review_plus_task',
          status: 'completed',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
      ],
    } as unknown as SuperAgentRun
    const detail = buildNodeDetail('node_dispatch', run)
    const panel = buildNodeDetailPanelModel(detail, '已选 1 位专家')
    const traces = resolveSuperAgentNodeLlmTraces('node_dispatch', run)

    expect(detail?.sections.some((section) => section.kind === 'summary')).toBe(true)
    expect(panel.businessSummary.join(' ')).toMatch(/调度结论|已选择|待选择/)
    expect(panel.businessSummary.join(' ')).not.toMatch(/bootstrap_review_plus_task|structure_materials/)
    expect(panel.reviewSections.some((section) => section.title === '专家清单')).toBe(true)
    expect(traces.some((trace) => trace.toolName === 'bootstrap_review_plus_task')).toBe(true)
    expect(panel.diagnosticSections.length).toBeGreaterThan(0)
  })

  it('includes expert review output summary for canvas expert nodes', () => {
    const run = {
      ...smartCommitteeRun(),
      review_plus_result: {
        smart_task_board: {
          tasks: [
            {
              task_id: 'format_gate:document_consistency_reviewer',
              kind: 'format_gate',
              specialist_id: 'document_consistency_reviewer',
              title: '文档一致性审查 Agent',
              status: 'completed',
              output_summary: { passed: true, check_item_count: 4, evidence_count: 68 },
            },
            {
              task_id: 'smart_specialist:risk_issue_reviewer',
              kind: 'smart_specialist_review',
              specialist_id: 'risk_issue_reviewer',
              title: '风险问题审查 Agent',
              status: 'completed',
              output_summary: {
                review: {
                  findings: ['发现接口描述不一致', '发现风险项未闭环'],
                  evidence_summary: '引用 3 条证据',
                },
              },
            },
          ],
        },
      },
    } as unknown as SuperAgentRun

    const nodeId = 'node_lane_smart_specialist_risk_issue_reviewer_step_0'
    const detail = buildNodeDetail(nodeId, run)
    const panel = buildNodeDetailPanelModel(detail)
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const expertNode = graph.nodes.find((node) => node.node_id === nodeId)

    expect(detail?.label).toBe('风险问题审查 Agent')
    expect(detail?.status).toBe('awaiting_confirm')
    expect(panel.businessSummary.join(' ')).toMatch(/风险问题审查 Agent|发现 2 项/)
    expect(expertNode?.status).toBe('awaiting_confirm')
    expect(expertNode?.subtitle).toMatch(/发现 2 项/)
    expect(panel.reviewSections.flatMap((section) => section.lines).join(' ')).toMatch(/接口描述不一致|证据引用/)
  })

  it('includes gate precheck output section in node detail panel', () => {
    const run = {
      ...smartCommitteeRun(),
      review_plus_result: {
        smart_task_board: {
          tasks: [
            {
              task_id: 'format_gate:document_consistency_reviewer',
              kind: 'format_gate',
              specialist_id: 'document_consistency_reviewer',
              title: '文档一致性审查 Agent',
              status: 'completed',
              output_summary: {
                passed: true,
                check_item_count: 4,
                evidence_count: 68,
                warnings: ['页码连续性待确认'],
              },
            },
          ],
        },
      },
    } as unknown as SuperAgentRun

    const panel = buildNodeDetailPanelModel(buildNodeDetail('node_gate_format', run))
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const gateNode = graph.nodes.find((node) => node.node_id === 'node_gate_format')
    expect(panel.businessSummary.join(' ')).toMatch(/预审结果：/)
    expect(panel.phaseSections.some((section) => section.title === '预审输出')).toBe(true)
    expect([
      ...panel.businessSummary,
      ...panel.phaseSections.flatMap((section) => section.lines),
    ].join(' ')).toMatch(/结论：预审通过|结论：需补充|预审结果：/)
    expect([
      ...panel.businessSummary,
      ...panel.phaseSections.flatMap((section) => section.lines),
    ].join(' ')).toMatch(/检查项 4 个|证据 68 条/)
    expect(gateNode?.subtitle).toMatch(/预审通过|需补充|阻断/)
    expect(gateNode?.subtitle).toMatch(/4 条检查项|68 条证据/)
  })

  it('parses nested format gate review summary from backend task board output', () => {
    const run = {
      ...smartCommitteeRun(),
      review_plus_result: {
        smart_task_board: {
          tasks: [
            {
              task_id: 'format_gate:document_format_reviewer',
              kind: 'format_gate',
              specialist_id: 'document_format_reviewer',
              title: '文档格式审查 Agent',
              status: 'completed',
              output_summary: {
                gate_status: 'limited',
                review: {
                  findings: [{ title: '版本号缺失', severity: 'major' }],
                  summary: {
                    evidence_count: 42,
                    check_item_count: 6,
                    finding_count: 1,
                  },
                },
              },
            },
          ],
        },
      },
    } as unknown as SuperAgentRun

    const panel = buildNodeDetailPanelModel(buildNodeDetail('node_gate_format', run))
    const text = panel.phaseSections.flatMap((section) => section.lines).join(' ')
    expect(text).toMatch(/结论：需补充/)
    expect(text).toMatch(/检查项 6 个|证据 42 条/)
    expect(text).toMatch(/版本号缺失/)
    expect(text).not.toContain('[object Object]')
  })

  it('falls back to structured bundle stats for gate output when task output is sparse', () => {
    const run = smartCommitteeRun()
    const panel = buildNodeDetailPanelModel(buildNodeDetail('node_gate_format', run))
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const gateNode = graph.nodes.find((node) => node.node_id === 'node_gate_format')

    expect(panel.businessSummary.join(' ')).toMatch(/预审结果：/)
    expect(panel.phaseSections.some((section) => section.title === '预审输出')).toBe(true)
    expect([
      ...panel.businessSummary,
      ...panel.phaseSections.flatMap((section) => section.lines),
    ].join(' ')).toMatch(/检查项 3 个|证据 68 条/)
    expect([
      ...panel.businessSummary,
      ...panel.phaseSections.flatMap((section) => section.lines),
    ].join(' ')).toMatch(/缺失 2 项|缺失项 2 个|需补充/)
    expect(gateNode?.subtitle).toMatch(/3 条检查项|68 条证据/)
  })

  it('reads format gate output from phase_artifacts task board during live run', () => {
    const run = {
      ...smartCommitteeRun(),
      phase_artifacts: {
        document_review: {
          smart_task_board: {
            tasks: [
              {
                task_id: 'format_gate:document_consistency_reviewer',
                kind: 'format_gate',
                specialist_id: 'document_consistency_reviewer',
                title: '文档一致性审查 Agent',
                status: 'completed',
                output_summary: {
                  passed: true,
                  check_item_count: 5,
                  evidence_count: 70,
                },
              },
            ],
          },
        },
      },
    } as unknown as SuperAgentRun

    const panel = buildNodeDetailPanelModel(buildNodeDetail('node_gate_format', run))
    const text = [
      ...panel.businessSummary,
      ...panel.phaseSections.flatMap((section) => section.lines),
    ].join(' ')
    expect(text).toMatch(/预审结果：预审通过/)
    expect(text).toMatch(/检查项 5 个|证据 70 条/)
    expect(text).not.toContain('[object Object]')
  })

  it('shows gate fallback business lines when format gate spec is absent', () => {
    const base = smartCommitteeRun()
    const run = {
      ...base,
      classification: {
        ...base.classification,
        smart_review_plan: {
          primary_path: 'smart_committee',
          task_specs: [
            {
              task_id: 'smart_specialist:risk_issue_reviewer',
              kind: 'smart_specialist_review',
              specialist_id: 'risk_issue_reviewer',
              title: '风险问题审查 Agent',
            },
          ],
        },
      },
    } as unknown as SuperAgentRun

    const detail = buildNodeDetail('node_gate_format', run)
    const panel = buildNodeDetailPanelModel(detail)
    expect(panel.businessSummary.join(' ')).toMatch(/预审结果：/)
    expect(panel.businessSummary.join(' ')).toMatch(/等待格式预审结果|已完成材料可审查性检查/)
    expect(panel.phaseSections.some((section) => section.title === '预审输出')).toBe(true)
  })

  it('includes dispatch output section in node detail panel', () => {
    const run = smartCommitteeRun()
    const panel = buildNodeDetailPanelModel(buildNodeDetail('node_dispatch', run))
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const dispatchNode = graph.nodes.find((node) => node.node_id === 'node_dispatch')

    expect(panel.phaseSections.some((section) => section.title === '调度输出')).toBe(true)
    expect(panel.phaseSections.flatMap((section) => section.lines).join(' ')).toMatch(/已选专家|路径：/)
    expect(dispatchNode?.subtitle).toMatch(/已选 1 位专家|门禁/)
  })

  it('maps critical and major findings to warning or error display tones', () => {
    const major = resolveReviewOutcomeStatus('completed', 3, 'major')
    const critical = resolveReviewOutcomeStatus('completed', 2, 'critical')
    expect(major.displayStatus).toBe('awaiting_confirm')
    expect(major.outcomeLabel).toMatch(/发现 3 项 · 需关注/)
    expect(critical.displayStatus).toBe('failed')
    expect(critical.outcomeLabel).toMatch(/含严重问题/)
  })

  it('enriches expert findings from specialist_reviews when task board output is sparse', () => {
    const run = {
      ...smartCommitteeRun(),
      review_plus_result: {
        specialist_reviews: [
          {
            agent_id: 'risk_issue_reviewer',
            agent_name: '风险问题审查 Agent',
            finding_count: 4,
            findings: [
              { title: '接口描述不一致', severity: 'major' },
              { title: '风险项未闭环', severity: 'critical' },
            ],
          },
        ],
        smart_task_board: {
          tasks: [
            {
              task_id: 'format_gate:document_consistency_reviewer',
              kind: 'format_gate',
              status: 'completed',
              output_summary: { passed: true },
            },
            {
              task_id: 'smart_specialist:risk_issue_reviewer',
              kind: 'smart_specialist_review',
              specialist_id: 'risk_issue_reviewer',
              title: '风险问题审查 Agent',
              status: 'completed',
              output_summary: {},
            },
          ],
        },
      },
    } as unknown as SuperAgentRun

    const nodeId = 'node_lane_smart_specialist_risk_issue_reviewer_step_0'
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const expertNode = graph.nodes.find((node) => node.node_id === nodeId)

    expect(expertNode?.status).toBe('failed')
    expect(expertNode?.subtitle).toMatch(/发现 4 项 · 含严重问题/)
  })

  it('includes chief merge summary for node_merge', () => {
    const run = {
      ...smartCommitteeRun(),
      review_plus_result: {
        finding_count: 5,
        conflict_count: 1,
        specialist_reviews: [
          {
            agent_id: 'risk_issue_reviewer',
            findings: [
              { title: '接口描述不一致', severity: 'major' },
              { title: '风险项未闭环', severity: 'critical' },
            ],
          },
        ],
        arbiter_summary: {
          consensus_summary: '总体符合，需关注接口一致性',
          conflicts: { group_a: 'severity mismatch' },
          recommendations: { priority: '先修复接口描述' },
        },
        replan_suggestions: ['补充联试记录'],
      },
    } as unknown as SuperAgentRun

    const detail = buildNodeDetail('node_merge', run)
    const panel = buildNodeDetailPanelModel(detail)

    expect(panel.businessSummary.join(' ')).toMatch(/综合结论|总体符合/)
    expect(panel.businessSummary.join(' ')).toMatch(/冲突组 1 个/)
    expect(panel.reviewSections.some((section) => section.title === '裁决依据')).toBe(true)
    expect(panel.reviewSections.flatMap((section) => section.lines).join(' ')).toMatch(/证据覆盖|严重度|置信度/)
    expect(panel.reviewSections.some((section) => section.title === '后续建议')).toBe(true)
    expect(panel.phaseSections.some((section) => section.title === '综合输出')).toBe(true)
    expect(panel.phaseSections.flatMap((section) => section.lines).join(' ')).toMatch(/问题 5 项|冲突组 1 个|最终建议/)
    expect(panel.phaseSections.flatMap((section) => section.lines).join(' ')).toMatch(/严重度：/)
  })

  it('includes synthesize report output section with coverage and limited state', () => {
    const run = {
      ...smartCommitteeRun(),
      status: 'limited',
      review_plus_result: {
        finding_count: 3,
        citation_coverage: 0.72,
        evidence_coverage: 0.61,
        limited: true,
      },
      quality_report: {
        ...smartCommitteeRun().quality_report,
        overall_score: 0.78,
        evidence_quality_score: 0.61,
      },
    } as unknown as SuperAgentRun

    const panel = buildNodeDetailPanelModel(buildNodeDetail('node_synthesize', run))
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const synthNode = graph.nodes.find((node) => node.node_id === 'node_synthesize')

    expect(panel.phaseSections.some((section) => section.title === '报告输出')).toBe(true)
    expect(panel.phaseSections.flatMap((section) => section.lines).join(' ')).toMatch(/报告状态：可导出|质量分 78%/)
    expect(panel.phaseSections.flatMap((section) => section.lines).join(' ')).toMatch(/引用覆盖 72%|证据覆盖 61%/)
    expect(panel.phaseSections.flatMap((section) => section.lines).join(' ')).toMatch(/limited：是/)
    expect(synthNode?.subtitle).toMatch(/limited 报告|证据 61%/)
  })

  it('keeps llm traces in diagnostics layer not business summary', () => {
    const run = {
      ...smartCommitteeRun(),
      skill_traces: [
        ...(smartCommitteeRun().skill_traces || []),
        {
          skill_id: 'bootstrap_review_plus_task',
          agent_id: 'data-agent:bootstrap',
          tool_name: 'bootstrap_review_plus_task',
          status: 'completed',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
        {
          skill_id: 'structure_materials',
          agent_id: 'data-agent:structure',
          tool_name: 'structure_materials',
          status: 'completed',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
      ],
    } as unknown as SuperAgentRun
    const panel = buildNodeDetailPanelModel(buildNodeDetail('node_dispatch', run))
    const traces = resolveSuperAgentNodeLlmTraces('node_dispatch', run)
    const traceText = traces.map((trace) => `${trace.agentName} ${trace.toolName || ''}`).join(' ')

    expect(traceText).toMatch(/bootstrap_review_plus_task|structure_materials/)
    expect(panel.businessSummary.join(' ')).not.toMatch(/bootstrap_review_plus_task|structure_materials|审查任务建档|型号资料结构化/)
    expect(panel.reviewSections.flatMap((section) => section.lines).join(' ')).not.toMatch(/bootstrap_review_plus_task/)
  })

  it('keeps canvas labels and subtitles free of raw trace identifiers', () => {
    const graph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    for (const node of graph.nodes) {
      const text = `${node.label} ${node.subtitle || ''}`
      expect(text).not.toMatch(/bootstrap_review_plus_task|structure_materials|run_review_plus/)
      expect(text).not.toMatch(/TaskSpec|TaskBoard|execution_mode/i)
    }
  })

  it('does not render [object Object] in non-agent node detail panel lines', () => {
    const run = {
      ...smartCommitteeRun(),
      review_plus_result: {
        smart_task_board: {
          tasks: [
            {
              task_id: 'format_gate:document_consistency_reviewer',
              kind: 'format_gate',
              status: 'completed',
              output_summary: { review: { summary: { nested: { value: 1 } } } },
            },
            {
              task_id: 'smart_specialist:risk_issue_reviewer',
              kind: 'smart_specialist_review',
              specialist_id: 'risk_issue_reviewer',
              title: '风险问题审查 Agent',
              status: 'completed',
              output_summary: { review: { findings: [] } },
            },
          ],
        },
        finding_count: 0,
        arbiter_summary: { consensus_summary: '总体符合' },
      },
    } as unknown as SuperAgentRun

    for (const nodeId of ['node_gate_format', 'node_dispatch', 'node_merge', 'node_synthesize'] as const) {
      const panel = buildNodeDetailPanelModel(buildNodeDetail(nodeId, run))
      const allText = [
        ...panel.businessSummary,
        ...panel.reviewSections.flatMap((section) => section.lines),
        ...panel.phaseSections.flatMap((section) => section.lines),
      ].join(' ')
      expect(allText).not.toContain('[object Object]')
    }
  })

  it('does not render [object Object] in node detail panel lines', () => {
    const run = {
      ...smartCommitteeRun(),
      review_plus_result: {
        smart_task_board: {
          tasks: [
            {
              task_id: 'smart_specialist:risk_issue_reviewer',
              kind: 'smart_specialist_review',
              specialist_id: 'risk_issue_reviewer',
              title: '风险问题审查 Agent',
              status: 'completed',
              execution_mode: 'generic_llm_harness',
              input_summary: {
                objective: '风险问题审查 Agent',
                material_count: 1,
                evidence_count: 68,
                check_item_count: 4,
              },
              output_summary: {
                review: {
                  findings: [
                    {
                      title: '发现接口描述不一致',
                      severity: 'major',
                      evidence_refs: [{ evidence_id: 'ev-1' }],
                    },
                  ],
                  evidence_summary: '引用 3 条证据',
                },
              },
            },
          ],
        },
      },
    } as unknown as SuperAgentRun

    const nodeId = 'node_lane_smart_specialist_risk_issue_reviewer_step_0'
    const panel = buildNodeDetailPanelModel(buildNodeDetail(nodeId, run))
    const allText = [
      ...panel.businessSummary,
      ...panel.reviewSections.flatMap((section) => section.lines),
      ...panel.phaseSections.flatMap((section) => section.lines),
      ...panel.diagnosticSections.flatMap((section) => section.lines),
    ].join(' ')

    expect(allText).not.toContain('[object Object]')
    expect(allText).toMatch(/任务目标|风险问题审查 Agent/)
    expect(allText).toMatch(/1 份材料|68 条证据|4 条检查项/)
    expect(allText).toMatch(/接口描述不一致|严重度/)
    expect(allText).toMatch(/通用 LLM 专家审查/)
  })

  it('formats generic_llm_harness execution mode label in Chinese', () => {
    expect(formatExecutionModeLabel('generic_llm_harness')).toBe('通用 LLM 专家审查')
  })

  it('excludes format_gate and arbiter from expert agent nodes', () => {
    const graph = buildSuperAgentFlowGraph(smartCommitteeRun(), runningReviewPlusTask())
    const agentLabels = graph.nodes
      .filter((node) => node.node_type === 'agent')
      .map((node) => node.label)
    expect(agentLabels).toEqual(['风险问题审查 Agent'])
    expect(agentLabels).not.toContain('总师综合评判')
    expect(agentLabels.every((label) => label !== '格式预审' && label !== '送审材料门禁')).toBe(true)
  })

  it('normalizes canvas step keys to node ids for detail panel lookup', () => {
    expect(normalizeSuperAgentCanvasNodeId('format_gate')).toBe('node_gate_format')
    expect(normalizeSuperAgentCanvasNodeId('synthesize')).toBe('node_synthesize')
    expect(normalizeSuperAgentCanvasNodeId('node_merge')).toBe('node_merge')
  })

  it('shows merge node subtitle with aggregated findings on canvas', () => {
    const run = {
      ...smartCommitteeRun(),
      review_plus_result: {
        finding_count: 4,
        conflict_count: 1,
        arbiter_summary: {
          consensus_summary: '总体符合，需关注接口一致性',
        },
      },
    } as unknown as SuperAgentRun

    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const mergeNode = graph.nodes.find((node) => node.node_id === 'node_merge')
    expect(mergeNode?.subtitle).toMatch(/汇总 4 条发现|总体符合/)
  })
})

describe('superAgentProcessingViewModel smart DAG dependency caps', () => {
  function smartRunWithTaskBoard(tasks: Record<string, unknown>[], extra: Partial<SuperAgentRun> = {}) {
    return {
      ...smartCommitteeRun(),
      ...extra,
      review_plus_result: {
        smart_task_board: { tasks },
        finding_count: 2,
        arbiter_summary: { consensus_summary: '总体符合' },
      },
    } as unknown as SuperAgentRun
  }

  it('blocks experts merge and synthesize when gate is blocked', () => {
    const run = smartRunWithTaskBoard([
      {
        task_id: 'format_gate:document_consistency_reviewer',
        kind: 'format_gate',
        specialist_id: 'document_consistency_reviewer',
        title: '文档一致性审查 Agent',
        status: 'failed',
        output_summary: { passed: false, gate_status: 'blocked' },
      },
      {
        task_id: 'smart_specialist:risk_issue_reviewer',
        kind: 'smart_specialist_review',
        specialist_id: 'risk_issue_reviewer',
        title: '风险问题审查 Agent',
        status: 'completed',
        output_summary: { review: { findings: [] } },
      },
      {
        task_id: 'arbiter_summary:committee',
        kind: 'arbiter_summary',
        status: 'completed',
      },
    ])
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const expert = graph.nodes.find((node) => node.label === '风险问题审查 Agent')
    const merge = graph.nodes.find((node) => node.node_id === 'node_merge')
    const synthesize = graph.nodes.find((node) => node.node_id === 'node_synthesize')

    expect(expert?.status).not.toBe('completed')
    expect(merge?.status).not.toBe('completed')
    expect(synthesize?.status).not.toBe('completed')
    expect(expert?.subtitle).toMatch(/前置门禁未通过|等待前置/)
    expect(merge?.subtitle).toMatch(/前置门禁未通过|等待专家|等待前置/)
    expect(synthesize?.subtitle).toMatch(/等待总师|等待前置|前置门禁/)
  })

  it('does not mark gate or experts completed while dispatch is running', () => {
    const run = {
      ...smartCommitteeRun(),
      skill_traces: [
        {
          skill_id: 'smart_review_committee',
          agent_id: 'data-agent:smart_review_orchestrator',
          tool_name: 'run_smart_review_committee',
          status: 'running',
          input_summary: {},
          output_summary: {},
          warnings: [],
          elapsed_ms: 0,
        },
      ],
    } as unknown as SuperAgentRun
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const dispatch = graph.nodes.find((node) => node.node_id === 'node_dispatch')
    const gate = graph.nodes.find((node) => node.node_id === 'node_gate_format')
    const expert = graph.nodes.find((node) => node.label === '风险问题审查 Agent')

    expect(dispatch?.status).toBe('running')
    expect(gate?.status).not.toBe('completed')
    expect(expert?.status).not.toBe('completed')
  })

  it('does not mark merge or synthesize completed when experts are partially done', () => {
    const run = smartRunWithTaskBoard([
      {
        task_id: 'format_gate:document_consistency_reviewer',
        kind: 'format_gate',
        status: 'completed',
        output_summary: { passed: true, check_item_count: 4, evidence_count: 68 },
      },
      {
        task_id: 'smart_specialist:risk_issue_reviewer',
        kind: 'smart_specialist_review',
        specialist_id: 'risk_issue_reviewer',
        title: '风险问题审查 Agent',
        status: 'completed',
        output_summary: { review: { findings: [] } },
      },
      {
        task_id: 'smart_specialist:data_quality_reviewer',
        kind: 'smart_specialist_review',
        specialist_id: 'data_quality_reviewer',
        title: '数据质量审查 Agent',
        status: 'running',
        output_summary: {},
      },
    ])
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const merge = graph.nodes.find((node) => node.node_id === 'node_merge')
    const synthesize = graph.nodes.find((node) => node.node_id === 'node_synthesize')

    expect(merge?.status).not.toBe('completed')
    expect(synthesize?.status).not.toBe('completed')
    expect(merge?.subtitle).toMatch(/等待专家审查完成后汇总/)
  })

  it('does not mark synthesize completed while merge is pending', () => {
    const run = {
      ...smartCommitteeRun(),
      review_plus_result: {
        smart_task_board: {
          tasks: [
            {
              task_id: 'format_gate:document_consistency_reviewer',
              kind: 'format_gate',
              status: 'completed',
              output_summary: { passed: true },
            },
            {
              task_id: 'smart_specialist:risk_issue_reviewer',
              kind: 'smart_specialist_review',
              specialist_id: 'risk_issue_reviewer',
              title: '风险问题审查 Agent',
              status: 'completed',
              output_summary: { review: { findings: [] } },
            },
            {
              task_id: 'arbiter_summary:committee',
              kind: 'arbiter_summary',
              status: 'running',
            },
          ],
        },
        finding_count: 0,
      },
    } as unknown as SuperAgentRun
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const merge = graph.nodes.find((node) => node.node_id === 'node_merge')
    const synthesize = graph.nodes.find((node) => node.node_id === 'node_synthesize')

    expect(merge?.status).toBe('running')
    expect(synthesize?.status).not.toBe('completed')
    expect(synthesize?.subtitle).toMatch(/等待总师综合评判/)
  })

  it('allows experts to run in parallel after gate completes', () => {
    const run = smartRunWithTaskBoard([
      {
        task_id: 'format_gate:document_consistency_reviewer',
        kind: 'format_gate',
        status: 'completed',
        output_summary: { passed: true, check_item_count: 4, evidence_count: 68 },
      },
      {
        task_id: 'smart_specialist:risk_issue_reviewer',
        kind: 'smart_specialist_review',
        specialist_id: 'risk_issue_reviewer',
        title: '风险问题审查 Agent',
        status: 'completed',
        output_summary: { review: { findings: [] } },
      },
      {
        task_id: 'smart_specialist:data_quality_reviewer',
        kind: 'smart_specialist_review',
        specialist_id: 'data_quality_reviewer',
        title: '数据质量审查 Agent',
        status: 'running',
        output_summary: {},
      },
    ])
    const graph = buildSuperAgentFlowGraph(run, runningReviewPlusTask())
    const completedExpert = graph.nodes.find((node) => node.label === '风险问题审查 Agent')
    const runningExpert = graph.nodes.find((node) => node.label === '数据质量审查 Agent')

    expect(completedExpert?.status).toBe('completed')
    expect(runningExpert?.status).toBe('running')
  })

  it('caps node status when upstream dependencies are incomplete', () => {
    expect(capNodeStatusByDependencies('completed', ['running'])).toBe('pending')
    expect(capNodeStatusByDependencies('running', ['blocked'])).toBe('blocked')
    expect(capNodeStatusByDependencies('completed', ['completed'])).toBe('completed')
  })
})
