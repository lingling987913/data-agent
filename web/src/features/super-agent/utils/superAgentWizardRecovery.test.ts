import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SuperAgentRun } from '@/features/super-agent/types'
import {
  CURRENT_RUN_STORAGE_KEY,
  clearPersistedRunId,
  clearRunIdFromUrl,
  getRecoverableRunId,
  getRunIdFromUrl,
  hasPersistedClassificationOnRun,
  needsServerClassify,
  resolveWizardStep,
  parsePreviewFromRun,
  restoreWizardStateFromRun,
  shouldAutoStartParsePreview,
  shouldShowClassifyResults,
  shouldShowParseLoadingUi,
  shouldShowParseStartCta,
  formatWizardStepBreadcrumb,
  resolveWizardStepLabels,
  WIZARD_STEP_LABELS,
  resolveMaxReachableWizardStep,
  canNavigateToWizardStep,
  canPersistWizardCheckpoint,
  canRerunReviewOnRun,
  resolveWizardStepNavHint,
  reviewModeCardFromRun,
  processingModeFromRun,
  hasRunParseArtifact,
  hasTerminalReviewOutcome,
} from './superAgentWizardRecovery'

function draftRun(overrides: Partial<SuperAgentRun> = {}): SuperAgentRun {
  return {
    run_id: 'run-test',
    name: 'test',
    objective: 'test',
    status: 'draft',
    processing_mode: 'OPTIMAL',
    input_mode: 'upload',
    source_review_id: '',
    requested_route: 'auto',
    review_mode: 'full',
    materials: [],
    route_decision: null,
    structured_bundle: {
      materials: [],
      parser_traces: [],
      section_tree: {},
      evidence_pool: {},
      chunks: [],
      check_items: [],
      stats: {},
      warnings: [],
    },
    review_plus_result: {},
    gnc_review_result: {},
    trace_report: { degradation_summary: [] },
    quality_report: { warnings: [] },
    skill_traces: [],
    error: '',
    wizard_step: 0,
    created_at: '',
    updated_at: '',
    ...overrides,
  } as SuperAgentRun
}

describe('run id recovery policy', () => {
  const storage = new Map<string, string>()
  let replaceState: ReturnType<typeof vi.fn>
  let locationSearch: string

  beforeEach(() => {
    storage.clear()
    locationSearch = ''
    replaceState = vi.fn()
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value)
        },
        removeItem: (key: string) => {
          storage.delete(key)
        },
      },
      location: {
        get search() {
          return locationSearch
        },
        pathname: '/super-agent',
      },
      history: { replaceState },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('getRunIdFromUrl reads runid from search params only', () => {
    expect(getRunIdFromUrl('?runid=abc-123')).toBe('abc-123')
    expect(getRunIdFromUrl('?foo=bar')).toBe('')
    expect(getRunIdFromUrl('?runid=')).toBe('')
  })

  it('getRecoverableRunId ignores localStorage when URL has no runid', () => {
    storage.set(CURRENT_RUN_STORAGE_KEY, 'stale-run-id')
    locationSearch = ''
    expect(getRecoverableRunId()).toBe('')
  })

  it('getRecoverableRunId prefers URL over localStorage', () => {
    storage.set(CURRENT_RUN_STORAGE_KEY, 'stale-run-id')
    locationSearch = '?runid=url-run-id'
    expect(getRecoverableRunId()).toBe('url-run-id')
  })

  it('clearPersistedRunId removes stored run id', () => {
    storage.set(CURRENT_RUN_STORAGE_KEY, 'old-run')
    clearPersistedRunId()
    expect(storage.has(CURRENT_RUN_STORAGE_KEY)).toBe(false)
  })

  it('clearRunIdFromUrl clears storage and strips query from pathname', () => {
    storage.set(CURRENT_RUN_STORAGE_KEY, 'old-run')
    locationSearch = '?runid=old-run'
    clearRunIdFromUrl('/super-agent')
    expect(storage.has(CURRENT_RUN_STORAGE_KEY)).toBe(false)
    expect(replaceState).toHaveBeenCalledWith(null, '', '/super-agent')
  })
})

describe('resolveWizardStep', () => {
  it('respects persisted wizard_step 2 even when classification exists', () => {
    const run = draftRun({
      wizard_step: 2,
      materials: [{ name: 'a.pdf', content: 'x' }],
      classification: {
        doc_type: '工程设计文档',
        domain: '综合',
        recommended_route: 'auto',
        reason: 'test',
      },
    })
    expect(resolveWizardStep(run)).toBe(2)
  })

  it('returns step 3 when wizard_step is 3 without parse preview', () => {
    const run = draftRun({
      wizard_step: 3,
      materials: [{ name: 'a.pdf', content: 'x' }],
      classification: {
        doc_type: '工程设计文档',
        domain: '综合',
        recommended_route: 'auto',
        reason: 'test',
      },
    })
    expect(resolveWizardStep(run)).toBe(3)
    expect(restoreWizardStateFromRun(run).parsePreview).toBeNull()
  })

  it('returns step 3 when parse preview is persisted', () => {
    const run = draftRun({
      wizard_step: 3,
      materials: [{ name: 'a.pdf', content: 'x' }],
      parse_preview: {
        classification: {},
        materials: [{ file_name: 'a.pdf', role: 'primary_doc' }],
        summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      },
    })
    expect(resolveWizardStep(run)).toBe(3)
  })

  it('returns step 2 when user navigated back despite parse preview on draft run', () => {
    const run = draftRun({
      wizard_step: 2,
      materials: [{ name: 'a.pdf', content: 'x' }],
      classification: {
        doc_type: '工程设计文档',
        domain: '综合',
        recommended_route: 'auto',
        reason: 'test',
      },
      parse_preview: {
        classification: {},
        materials: [{ file_name: 'a.pdf', role: 'primary_doc' }],
        summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      },
    })
    expect(resolveWizardStep(run)).toBe(2)
  })

  it('migrates legacy wizard_step 4 with parse preview to step 3', () => {
    const run = draftRun({
      wizard_step: 4,
      materials: [{ name: 'a.pdf', content: 'x' }],
      parse_preview: {
        classification: {},
        materials: [{ file_name: 'a.pdf', role: 'primary_doc' }],
        summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      },
    })
    expect(resolveWizardStep(run)).toBe(3)
  })

  it('returns step 4 while review is running', () => {
    const run = draftRun({
      wizard_step: 4,
      status: 'running',
      materials: [{ name: 'a.pdf', content: 'x' }],
    })
    expect(resolveWizardStep(run)).toBe(4)
  })

  it('returns step 3 when parse preview exists but review failed', () => {
    const run = draftRun({
      wizard_step: 4,
      status: 'failed',
      materials: [{ name: 'a.pdf', content: 'x' }],
      parse_preview: {
        classification: {},
        materials: [{ file_name: 'a.pdf', role: 'primary_doc' }],
        summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      },
    })
    expect(resolveWizardStep(run)).toBe(3)
  })

  it('returns step 5 when review is completed', () => {
    const run = draftRun({
      wizard_step: 5,
      status: 'completed',
      materials: [{ name: 'a.pdf', content: 'x' }],
    })
    expect(resolveWizardStep(run)).toBe(5)
  })

  it('returns step 5 for completed run with parse preview', () => {
    const parsePreview = {
      classification: {},
      materials: [{ file_name: 'a.pdf', role: 'primary_doc' }],
      summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
    }
    expect(
      resolveWizardStep(
        draftRun({
          status: 'completed',
          wizard_step: 5,
          materials: [{ name: 'a.pdf', content: 'x' }],
          parse_preview: parsePreview,
        }),
      ),
    ).toBe(5)
    expect(
      resolveWizardStep(
        draftRun({
          status: 'limited',
          wizard_step: 5,
          materials: [{ name: 'a.pdf', content: 'x' }],
          parse_preview: parsePreview,
        }),
      ),
    ).toBe(5)
  })

  it('returns step 5 for draft run persisted on step 5 with review artifacts', () => {
    const parsePreview = {
      classification: {},
      materials: [{ file_name: 'a.pdf', role: 'primary_doc' }],
      summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
    }
    const run = draftRun({
      status: 'draft',
      wizard_step: 5,
      materials: [{ name: 'a.pdf', content: 'x' }],
      parse_preview: parsePreview,
      review_plus_result: {
        report: { satisfied_count: 3, not_satisfied_count: 1 },
      },
    })
    expect(resolveWizardStep(run)).toBe(5)
  })

  it('returns step 5 for draft run with report_markdown even when wizard_step is 4', () => {
    const run = draftRun({
      status: 'draft',
      wizard_step: 4,
      materials: [{ name: 'a.pdf', content: 'x' }],
      parse_preview: {
        classification: {},
        materials: [{ file_name: 'a.pdf', role: 'primary_doc' }],
        summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      },
      report_markdown: '# 审查报告\n\n结论：通过',
    })
    expect(resolveWizardStep(run)).toBe(5)
  })

  it('returns step 5 for failed run with parse preview and review result for readback', () => {
    const run = draftRun({
      wizard_step: 4,
      status: 'failed',
      materials: [{ name: 'a.pdf', content: 'x' }],
      parse_preview: {
        classification: {},
        materials: [{ file_name: 'a.pdf', role: 'primary_doc' }],
        summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      },
      review_plus_result: {
        report: {
          findings: [{ finding_id: 'R-001', judgment: 'not_satisfied', title: '问题项' }],
        },
      },
    })
    expect(resolveWizardStep(run)).toBe(5)
  })
})

describe('wizard step gates', () => {
  it('shows classify results on step 2 after recognition', () => {
    expect(
      shouldShowClassifyResults(2, {
        doc_type: '工程设计文档',
        domain: '综合',
        recommended_route: 'auto',
        reason: 'test',
      }),
    ).toBe(true)
    expect(shouldShowClassifyResults(2, null)).toBe(false)
  })

  it('returns step 2 when materials exist but classification is not persisted', () => {
    const run = draftRun({
      wizard_step: 0,
      materials: [{ name: 'a.pdf', content: 'x' }],
    })
    expect(resolveWizardStep(run)).toBe(2)
    expect(restoreWizardStateFromRun(run).classification).toBeNull()
    expect(hasPersistedClassificationOnRun(run)).toBe(false)
    expect(needsServerClassify(run, restoreWizardStateFromRun(run))).toBe(true)
  })

  it('does not trigger classify for completed runs or terminal review outcomes', () => {
    const completed = draftRun({
      status: 'completed',
      wizard_step: 5,
      materials: [{ name: 'a.pdf', content: 'x' }],
    })
    expect(needsServerClassify(completed, restoreWizardStateFromRun(completed))).toBe(false)

    const draftWithResults = draftRun({
      status: 'draft',
      wizard_step: 5,
      materials: [{ name: 'a.pdf', content: 'x' }],
      review_plus_result: {
        report: { satisfied_count: 2 },
      },
    })
    expect(needsServerClassify(draftWithResults, restoreWizardStateFromRun(draftWithResults))).toBe(false)
  })

  it('returns step 3 (document parse) when classification exists without parse preview', () => {
    const run = draftRun({
      wizard_step: 0,
      materials: [{ name: 'a.pdf', content: 'x' }],
      classification: {
        doc_type: '工程设计文档',
        domain: '综合',
        recommended_route: 'auto',
        reason: 'test',
      },
    })
    expect(resolveWizardStep(run)).toBe(3)
  })

  it('shows parse loading UI on step 3 before preview arrives', () => {
    expect(shouldShowParseLoadingUi(3, null, false, false)).toBe(true)
    expect(shouldShowParseLoadingUi(3, null, true, false)).toBe(true)
    expect(shouldShowParseLoadingUi(3, null, false, true)).toBe(false)
  })

  it('shows parse start CTA on step 3 only after an error', () => {
    expect(shouldShowParseStartCta(3, null, false, false)).toBe(false)
    expect(shouldShowParseStartCta(3, null, false, true)).toBe(true)
    expect(shouldShowParseStartCta(3, null, true, true)).toBe(false)
    expect(
      shouldShowParseStartCta(
        3,
        {
          classification: {
            doc_type: '工程设计文档',
            domain: '综合',
            recommended_route: 'auto',
            reason: 'test',
          },
          materials: [],
          summary: { material_count: 0, parsed_ok: 0, degraded_count: 0 },
        },
        false,
        false,
      ),
    ).toBe(false)
  })

  it('auto-starts parse preview once on step 3', () => {
    const base = {
      step: 3 as const,
      hasClassification: true,
      fileCount: 2,
      persistedMaterialCount: 0,
      hasParsePreview: false,
      parseInFlight: false,
      autoStartConsumed: false,
    }
    expect(shouldAutoStartParsePreview(base)).toBe(true)
    expect(shouldAutoStartParsePreview({ ...base, autoStartConsumed: true })).toBe(false)
    expect(shouldAutoStartParsePreview({ ...base, parseInFlight: true })).toBe(false)
    expect(shouldAutoStartParsePreview({ ...base, hasParsePreview: true })).toBe(false)
    expect(shouldAutoStartParsePreview({ ...base, step: 2 })).toBe(false)
  })

  it('restores stale checkpoint parse_preview so v2 panel can show reparse CTA', () => {
    const run = draftRun({
      wizard_step: 3,
      materials: [{ name: 'a.pdf', content: 'x' }],
      classification: {
        doc_type: '工程设计文档',
        domain: '综合',
        recommended_route: 'auto',
        reason: 'test',
      },
      parse_preview: {
        classification: {
          doc_type: '工程设计文档',
          domain: '综合',
          recommended_route: 'auto',
          reason: 'test',
        },
        materials: [
          {
            file_name: 'a.pdf',
            role: 'subject_document',
            role_confidence: 0.9,
            role_reason: '',
            parsing_tier: 'standard',
            parser_type: 'auto',
            processing_mode: 'OPTIMAL',
            parse_status: 'ok',
            parser_name: 'mineru',
            content_preview: '| 提出方 | 内容 |',
            content_length: 19888,
            line_count: 55,
            warnings: [],
            parser_trace: [],
            document_ir_stats: { layout_block_count: 55 },
          },
        ],
        summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      },
    })
    expect(parsePreviewFromRun(run)).toBe(run.parse_preview)
    expect(restoreWizardStateFromRun(run).parsePreview).toBe(run.parse_preview)
  })

  it('keeps completed runs on result view while preserving parse preview for inspection', () => {
    const run = draftRun({
      status: 'completed',
      wizard_step: 5,
      materials: [{ name: 'a.pdf', content: 'x' }],
      parse_preview: {
        classification: {
          doc_type: '工程设计文档',
          domain: '综合',
          recommended_route: 'auto',
          reason: 'test',
        },
        materials: [
          {
            file_name: 'a.pdf',
            role: 'subject_document',
            role_confidence: 0.9,
            role_reason: '',
            parsing_tier: 'standard',
            parser_type: 'auto',
            processing_mode: 'OPTIMAL',
            parse_status: 'ok',
            parser_name: 'mineru',
            content_preview: '| 提出方 | 内容 |',
            content_length: 19888,
            line_count: 55,
            warnings: [],
            parser_trace: [],
          },
        ],
        summary: { material_count: 1, parsed_ok: 1, degraded_count: 0 },
      },
    })
    const restored = restoreWizardStateFromRun(run)
    expect(restored.step).toBe(5)
    expect(restored.parsePreview).toBe(run.parse_preview)
  })
})

describe('wizard step labels', () => {
  it('uses product step names for the default breadcrumb', () => {
    expect(WIZARD_STEP_LABELS).toEqual([
      '上传材料',
      '识别与路由',
      '文档解析',
      '文档审查',
      '审查结果',
    ])
    expect(formatWizardStepBreadcrumb()).toBe(
      '上传材料 → 识别与路由 → 文档解析 → 文档审查 → 审查结果',
    )
  })

  it('keeps fixed labels while review is running on step 4', () => {
    expect(
      resolveWizardStepLabels({ step: 4, runStatus: 'running' }),
    ).toEqual([
      '上传材料',
      '识别与路由',
      '文档解析',
      '文档审查',
      '审查结果',
    ])
    expect(
      formatWizardStepBreadcrumb({ step: 4, runStatus: 'running' }),
    ).toBe('上传材料 → 识别与路由 → 文档解析 → 文档审查 → 审查结果')
  })
})

describe('wizard step navigation', () => {
  it('max reachable step follows run milestones and current step', () => {
    expect(resolveMaxReachableWizardStep(1, null)).toBe(1)
    expect(
      resolveMaxReachableWizardStep(
        2,
        draftRun({
          materials: [{ name: 'a.pdf', content: 'x' }],
          wizard_step: 2,
        }),
      ),
    ).toBe(2)
    expect(
      resolveMaxReachableWizardStep(
        3,
        draftRun({
          status: 'completed',
          wizard_step: 5,
          materials: [{ name: 'a.pdf', content: 'x' }],
        }),
      ),
    ).toBe(5)
    expect(
      resolveMaxReachableWizardStep(
        3,
        draftRun({
          status: 'running',
          wizard_step: 4,
          materials: [{ name: 'a.pdf', content: 'x' }],
        }),
      ),
    ).toBe(4)
  })

  it('blocks navigating back while review is running on step 4', () => {
    expect(
      canNavigateToWizardStep({
        target: 3,
        currentStep: 4,
        maxReachableStep: 4,
        runStatus: 'running',
      }),
    ).toEqual({
      allowed: false,
      reason: '审查进行中，请等待完成后再回退',
    })
    expect(
      canNavigateToWizardStep({
        target: 4,
        currentStep: 4,
        maxReachableStep: 4,
        runStatus: 'running',
      }),
    ).toEqual({ allowed: false, reason: '当前步骤' })
  })

  it('allows navigating within reached steps after review completes', () => {
    expect(
      canNavigateToWizardStep({
        target: 3,
        currentStep: 5,
        maxReachableStep: 5,
        runStatus: 'completed',
      }),
    ).toEqual({ allowed: true })
    expect(
      canNavigateToWizardStep({
        target: 5,
        currentStep: 3,
        maxReachableStep: 5,
        runStatus: 'completed',
      }),
    ).toEqual({ allowed: true })
    expect(
      resolveWizardStepNavHint({
        target: 3,
        currentStep: 5,
        maxReachableStep: 5,
        runStatus: 'completed',
        label: '文档解析',
      }),
    ).toBe('返回「文档解析」查看或从此步骤重新开始')
  })

  it('disables unreached future steps', () => {
    expect(
      canNavigateToWizardStep({
        target: 4,
        currentStep: 2,
        maxReachableStep: 2,
        runStatus: 'draft',
      }),
    ).toEqual({ allowed: false, reason: '尚未到达该步骤' })
  })
})

describe('execution plan recovery', () => {
  it('restores review mode card and processing mode from persisted plans', () => {
    const run = draftRun({
      requested_route: 'auto',
      processing_mode: 'HIGH_SPEED',
      classification: {
        doc_type: '单文档',
        domain: '综合',
        recommended_route: 'smart',
        reason: 'test',
        review_mode_selection: 'standard',
        parse_plan: {
          default_processing_mode: 'OPTIMAL',
          default_parser_type: 'auto',
          files: [],
        },
        review_plan: {
          route: 'review_plus',
          recommended_route: 'smart',
          review_mode_selection: 'standard',
          required_tools: ['run_review_plus'],
          skipped_tools: [],
          bootstrap_review_plus: false,
          run_structure_parse: true,
          reuse_review_plus_parse: false,
          confidence: 0.9,
          reasons: [],
          downgrade_reasons: [],
          review_plus_ready: false,
        },
      },
    })
    expect(reviewModeCardFromRun(run)).toBe('standard')
    expect(processingModeFromRun(run)).toBe('OPTIMAL')
  })
})

describe('completed run re-review helpers', () => {
  it('blocks wizard checkpoint for non-draft runs', () => {
    expect(canPersistWizardCheckpoint(draftRun({ status: 'draft' }))).toBe(true)
    expect(canPersistWizardCheckpoint(draftRun({ status: 'completed' }))).toBe(false)
    expect(canPersistWizardCheckpoint(draftRun({ status: 'running' }))).toBe(false)
  })

  it('allows review rerun for completed and failed runs', () => {
    expect(canRerunReviewOnRun(draftRun({ status: 'completed' }))).toBe(true)
    expect(canRerunReviewOnRun(draftRun({ status: 'limited' }))).toBe(true)
    expect(canRerunReviewOnRun(draftRun({ status: 'failed' }))).toBe(true)
    expect(canRerunReviewOnRun(draftRun({ status: 'interrupted' }))).toBe(true)
    expect(canRerunReviewOnRun(draftRun({ status: 'draft' }))).toBe(false)
    expect(canRerunReviewOnRun(null)).toBe(false)
  })

  it('detects parse artifact from preview or structured bundle', () => {
    const withPreview = draftRun({
      status: 'completed',
      parse_preview: {
        materials: [{ file_name: 'a.md', role: 'subject_document', parsing_tier: 'standard', processing_mode: 'OPTIMAL' }],
        summary: { material_count: 1, parsed_ok: 1, parsed_failed: 0 },
      },
    })
    expect(hasRunParseArtifact(withPreview, null)).toBe(true)

    const withBundle = draftRun({
      status: 'completed',
      structured_bundle: {
        materials: [],
        parser_traces: [],
        section_tree: {},
        evidence_pool: {},
        chunks: [],
        check_items: [],
        stats: {},
        warnings: [],
        parse_artifact: { pipeline_step: 'document_parse', materials: [] },
      },
    })
    expect(hasRunParseArtifact(withBundle, null)).toBe(true)

    const withoutArtifact = draftRun({ status: 'completed' })
    expect(hasRunParseArtifact(withoutArtifact, null)).toBe(false)
  })
})
