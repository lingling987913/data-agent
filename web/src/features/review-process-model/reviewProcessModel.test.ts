import { describe, expect, it } from 'vitest'
import {
  buildGncReviewProcessModel,
  buildGncStageSubtitleFromModel,
} from '@/features/review-process-model/adapters/gncReviewProcessAdapter'
import {
  buildReviewPlusReviewProcessModel,
  REVIEW_PLUS_PROCESS_STAGE_DEFS,
} from '@/features/review-process-model/adapters/reviewPlusProcessAdapter'
import {
  buildSmartReviewProcessModel,
  SMART_REVIEW_PROCESS_STAGE_DEFS,
} from '@/features/review-process-model/adapters/smartReviewProcessAdapter'
import {
  buildProcessLaneFromModel,
  resolveProcessStageDeepTasks,
} from '@/features/review-process-model/superAgentLaneAdapter'

describe('reviewProcessModel adapters', () => {
  it('maps GNC backend steps into six user-facing stages with AD/AC subflows', () => {
    const model = buildGncReviewProcessModel({
      stepStatuses: [
        'completed',
        'completed',
        'running',
        'pending',
        'pending',
        'pending',
        'pending',
        'pending',
        'pending',
        'pending',
      ],
      requiresArbitration: false,
      committee: { review_scope: 'ad_ac' },
    })

    expect(model.processKind).toBe('gnc')
    expect(model.stages).toHaveLength(6)
    expect(model.stages.map((stage) => stage.label)).toEqual([
      '材料接收与任务建立',
      '文档解析与证据准备',
      '专家组审查（AD/AC/规则）',
      '问题合稿与 RID 台账',
      '总师裁定与仲裁',
      '报告归档 / 闭环',
    ])
    expect(model.stages[1].isCurrent).toBe(true)
    expect(model.stages[2].subflowLanes?.length).toBe(2)
    expect(model.stages[2].subflowLanes?.[0].label).toMatch(/AD/)
    expect(model.stages[2].subflowLanes?.[1].label).toMatch(/AC/)
    expect(model.stages[2].steps).toHaveLength(1)
    expect(model.stages[1].steps.length).toBeGreaterThan(1)
  })

  it('maps Review-Plus pipeline into user-facing stages with item review subtasks', () => {
    const model = buildReviewPlusReviewProcessModel({
      stepStatuses: {
        material_classification: 'completed',
        scenario_detection: 'completed',
        document_structuring: 'completed',
        chief_orchestration: 'completed',
        rule_extraction: 'completed',
        rule_section_mapping: 'running',
        item_review: 'pending',
        traceability: 'pending',
        cross_document_review: 'pending',
        report_composition: 'pending',
      },
      sourceReviewId: 'rp_test',
      findingCount: 5,
    })

    expect(model.processKind).toBe('review_plus')
    expect(model.stages).toHaveLength(REVIEW_PLUS_PROCESS_STAGE_DEFS.length)
    expect(model.stages.map((stage) => stage.label)).toEqual([
      '材料接收与分类',
      '文档结构化与预审',
      '规则抽取与证据映射',
      '逐项符合性审查',
      '追溯与跨文档核验',
      '报告输出',
    ])
    expect(model.stages[0].subtitle).toContain('rp_test')
    expect(model.stages[2].isCurrent).toBe(true)

    const lane = buildProcessLaneFromModel('review-plus', model, {
      title: '子任务 · 文件组审查',
      processItemId: 'lane-review-plus',
    })
    expect(lane.nodes).toHaveLength(6)
    expect(lane.nodes.map((node) => node.label)).not.toContain('材料与规则准备')
  })

  it('maps smart committee into generic stages with expert subflow lanes', () => {
    const model = buildSmartReviewProcessModel({
      prepareStatus: 'completed',
      formatGateStatus: 'completed',
      formatGateSubtitle: '预审通过 · 4 条检查项',
      committeeStatus: 'running',
      mergeStatus: 'pending',
      synthesizeStatus: 'pending',
      expertTasks: [
        {
          taskId: 'risk_issue_reviewer',
          title: '风险问题审查 Agent',
          status: 'running',
          findingCount: 2,
          subtitle: '发现 2 项',
        },
      ],
    })

    expect(model.processKind).toBe('smart_committee')
    expect(model.stages).toHaveLength(SMART_REVIEW_PROCESS_STAGE_DEFS.length)
    expect(model.stages.map((stage) => stage.label)).toEqual([
      '材料接收与准备',
      '格式预审与门禁',
      '专家并行审查',
      '总师综合评判',
      '质量复核与报告',
    ])
    expect(model.stages[2].subflowLanes?.[0].label).toBe('风险问题审查 Agent')
    expect(model.currentStageLabel).toBe('专家并行审查')
  })

  it('exposes committee stage deep tasks from subflow lanes', () => {
    const model = buildGncReviewProcessModel({
      stepStatuses: Array(10).fill('pending').map((_, index) => (index < 5 ? 'completed' : index === 5 ? 'running' : 'pending')),
      committee: { review_scope: 'ad_ac' },
    })
    const committeeIndex = model.stages.findIndex((stage) => stage.stageKey === 'committee_review')
    const deepTasks = resolveProcessStageDeepTasks('gnc', committeeIndex, model)
    expect(deepTasks.length).toBeGreaterThan(0)
    expect(deepTasks.some((task) => task.label.includes('AD'))).toBe(true)
    expect(deepTasks.some((task) => task.label.includes('AC'))).toBe(true)
  })

  it('builds readable GNC stage subtitles from model', () => {
    const model = buildGncReviewProcessModel({
      stepStatuses: ['completed', 'running', ...Array(8).fill('pending')],
      committee: { review_scope: 'ad_ac' },
    })
    const subtitle = buildGncStageSubtitleFromModel('document_evidence_prep', model)
    expect(subtitle.length).toBeGreaterThan(0)
  })
})
