import type {
  MaterialClassification,
  ParsePreviewResponse,
  ReviewModeSelection,
  SuperAgentRun,
} from '@/features/super-agent/types'

export type WizardStep = 1 | 2 | 3 | 4 | 5

/** 语义阶段键，与 wizard_step 数字映射一致。 */
export type WizardPhase =
  | 'upload'
  | 'classify_and_route'
  | 'document_parse'
  | 'document_review'
  | 'review_results'

export const WIZARD_STEP_TO_PHASE: Record<WizardStep, WizardPhase> = {
  1: 'upload',
  2: 'classify_and_route',
  3: 'document_parse',
  4: 'document_review',
  5: 'review_results',
}

export const WIZARD_PHASE_TO_STEP: Record<WizardPhase, WizardStep> = {
  upload: 1,
  classify_and_route: 2,
  document_parse: 3,
  document_review: 4,
  review_results: 5,
}

/** 向导步骤展示文案（与 stepper / breadcrumb 保持一致）。 */
export const WIZARD_STEP_LABELS = [
  '上传材料',
  '识别与路由',
  '文档解析',
  '文档审查',
  '审查结果',
] as const

export function resolveWizardStepLabels(_options?: {
  step?: WizardStep
  runStatus?: SuperAgentRun['status']
  busy?: boolean
}): string[] {
  return [...WIZARD_STEP_LABELS]
}

export function formatWizardStepBreadcrumb(options?: Parameters<typeof resolveWizardStepLabels>[0]): string {
  return resolveWizardStepLabels(options).join(' → ')
}

/** 根据 run 里程碑与用户当前步骤，推断 stepper 上最远可点击步骤。 */
export function resolveMaxReachableWizardStep(
  currentStep: WizardStep,
  run: SuperAgentRun | null | undefined,
): WizardStep {
  if (!run) return currentStep

  let milestone: WizardStep = 1
  if (run.status === 'completed' || run.status === 'limited') {
    milestone = 5
  } else if (run.status === 'running') {
    milestone = 4
  } else if (run.status === 'failed' || run.status === 'interrupted') {
    milestone = 4
  } else {
    milestone = resolveWizardStep(run)
  }

  return Math.max(currentStep, milestone) as WizardStep
}

export interface WizardStepNavInput {
  target: WizardStep
  currentStep: WizardStep
  maxReachableStep: WizardStep
  runStatus?: SuperAgentRun['status']
}

export function canNavigateToWizardStep(input: WizardStepNavInput): { allowed: boolean; reason?: string } {
  const { target, currentStep, maxReachableStep, runStatus } = input

  if (target === currentStep) {
    return { allowed: false, reason: '当前步骤' }
  }
  if (target > maxReachableStep) {
    return { allowed: false, reason: '尚未到达该步骤' }
  }
  if (runStatus === 'running' && currentStep === 4 && target < 4) {
    return { allowed: false, reason: '审查进行中，请等待完成后再回退' }
  }

  return { allowed: true }
}

export function resolveWizardStepNavHint(
  input: WizardStepNavInput & { label: string },
): string {
  const check = canNavigateToWizardStep(input)
  if (!check.allowed) {
    return check.reason || input.label
  }
  if (input.target < input.currentStep) {
    return `返回「${input.label}」查看或从此步骤重新开始`
  }
  return `前往「${input.label}」`
}

export function wizardStepToPhase(step: WizardStep): WizardPhase {
  return WIZARD_STEP_TO_PHASE[step]
}

export function wizardPhaseToStep(phase: WizardPhase): WizardStep {
  return WIZARD_PHASE_TO_STEP[phase]
}

export const RUN_ID_QUERY_KEY = 'runid'
export const CURRENT_RUN_STORAGE_KEY = 'super-agent-current-run-id'

const EXECUTION_RUNNING_STATUSES = new Set(['running', 'interrupted', 'failed'])
const EXECUTION_RESULT_STATUSES = new Set(['completed', 'limited'])
const REVIEW_RERUN_STATUSES = new Set(['completed', 'limited', 'failed', 'interrupted'])

/** wizard PATCH 仅 draft 可写；已完成/失败 run 应走 POST /review 重跑。 */
export function canPersistWizardCheckpoint(run: SuperAgentRun | null | undefined): boolean {
  return run?.status === 'draft'
}

/** 是否可在同一 run 上复用 parse artifact 重新审查。 */
export function canRerunReviewOnRun(run: SuperAgentRun | null | undefined): boolean {
  return Boolean(run?.run_id && REVIEW_RERUN_STATUSES.has(run.status))
}

export function hasRunParseArtifact(
  run: SuperAgentRun | null | undefined,
  parsePreview?: ParsePreviewResponse | null,
): boolean {
  if (parsePreview) return true
  if (hasPersistedParsePreview(run ?? ({} as SuperAgentRun))) return true
  const artifact = run?.structured_bundle?.parse_artifact
  return Boolean(artifact && Object.keys(artifact).length > 0)
}

/** 仅从 URL 查询参数读取 runid；无 runid 时不读 localStorage。 */
export function getRunIdFromUrl(search = typeof window !== 'undefined' ? window.location.search : ''): string {
  return new URLSearchParams(search).get(RUN_ID_QUERY_KEY)?.trim() || ''
}

/** @deprecated 使用 {@link getRunIdFromUrl}；保留别名，行为与 URL 读取一致。 */
export function getRecoverableRunId(): string {
  if (typeof window === 'undefined') return ''
  return getRunIdFromUrl(window.location.search)
}

export function clearPersistedRunId() {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(CURRENT_RUN_STORAGE_KEY)
}

export function clearRunIdFromUrl(pathname = '/super-agent') {
  if (typeof window === 'undefined') return
  clearPersistedRunId()
  window.history.replaceState(null, '', pathname)
}

export function buildSuperAgentRunUrl(runId: string, pathname = '/super-agent'): string {
  const params = new URLSearchParams()
  params.set(RUN_ID_QUERY_KEY, runId)
  return `${pathname}?${params.toString()}`
}

export function persistRunId(runId: string) {
  if (typeof window === 'undefined' || !runId) return
  window.localStorage.setItem(CURRENT_RUN_STORAGE_KEY, runId)
}

export function replaceRunIdInUrl(runId: string, pathname = '/super-agent') {
  if (typeof window === 'undefined' || !runId) return
  persistRunId(runId)
  window.history.replaceState(null, '', buildSuperAgentRunUrl(runId, pathname))
}

/** 服务端 run 是否已持久化步骤 2 识别结果（步骤 3 parse-preview 门禁）。 */
export function hasPersistedClassificationOnRun(run: SuperAgentRun): boolean {
  const stored = run.classification
  if (stored?.doc_type) return true
  const roles = stored?.material_roles
  if (Array.isArray(roles) && roles.length > 0) return true
  return Boolean(run.route_decision?.classification?.doc_type)
}

function classificationPostParseFields(
  stored: Record<string, unknown>,
): Pick<
  MaterialClassification,
  | 'initial_recommended_route'
  | 'final_recommended_route'
  | 'route_decision_source'
  | 'post_parse_route'
  | 'post_parse_reason'
> {
  return {
    initial_recommended_route: stored.initial_recommended_route
      ? String(stored.initial_recommended_route)
      : undefined,
    final_recommended_route: stored.final_recommended_route
      ? String(stored.final_recommended_route)
      : undefined,
    route_decision_source: stored.route_decision_source
      ? String(stored.route_decision_source)
      : undefined,
    post_parse_route: stored.post_parse_route as MaterialClassification['post_parse_route'],
    post_parse_reason: stored.post_parse_reason ? String(stored.post_parse_reason) : undefined,
  }
}

export function classificationFromRun(run: SuperAgentRun): MaterialClassification | null {
  const fromRoute = run.route_decision?.classification
  if (fromRoute?.doc_type) {
    return {
      ...fromRoute,
      ...classificationPostParseFields(fromRoute as unknown as Record<string, unknown>),
    }
  }
  const stored = run.classification
  if (stored?.doc_type) {
    return {
      doc_type: String(stored.doc_type || '工程设计文档'),
      domain: String(stored.domain || '综合'),
      recommended_route: String(stored.recommended_route || run.requested_route || 'auto'),
      reason: String(stored.reason || run.objective || '已从已保存任务恢复审查方案'),
      confidence: typeof stored.confidence === 'number' ? stored.confidence : undefined,
      material_roles: Array.isArray(stored.material_roles)
        ? (stored.material_roles as MaterialClassification['material_roles'])
        : undefined,
      slot_completeness: stored.slot_completeness as MaterialClassification['slot_completeness'],
      missing_slots: Array.isArray(stored.missing_slots)
        ? (stored.missing_slots as string[])
        : undefined,
      review_plus_ready: typeof stored.review_plus_ready === 'boolean' ? stored.review_plus_ready : undefined,
      parse_plan: stored.parse_plan as MaterialClassification['parse_plan'],
      review_plan: stored.review_plan as MaterialClassification['review_plan'],
      review_mode_selection: stored.review_mode_selection as ReviewModeSelection | undefined,
      ...classificationPostParseFields(stored as unknown as Record<string, unknown>),
    }
  }
  return null
}

export function reviewModeCardFromRun(run: SuperAgentRun): ReviewModeSelection {
  const classification = classificationFromRun(run)
  const stored = classification?.review_mode_selection || classification?.review_plan?.review_mode_selection
  if (stored === 'standard' || stored === 'specialized' || stored === 'smart') {
    return stored
  }
  if (run.requested_route === 'review_plus') return 'standard'
  if (run.requested_route === 'gnc_review_only' || run.requested_route === 'gnc_review') return 'specialized'
  return 'smart'
}

export function processingModeFromRun(run: SuperAgentRun): string {
  const classification = classificationFromRun(run)
  const fromPlan = classification?.parse_plan?.default_processing_mode
  if (fromPlan) return fromPlan
  return run.processing_mode || 'OPTIMAL'
}

function hasPersistedParsePreview(run: SuperAgentRun): boolean {
  const preview = run.parse_preview as ParsePreviewResponse | undefined
  if (!preview) return false
  if (Array.isArray(preview.materials) && preview.materials.length > 0) return true
  const count = preview.summary?.material_count
  return typeof count === 'number' && count > 0
}

function hasPersistedClassification(run: SuperAgentRun): boolean {
  return hasPersistedClassificationOnRun(run)
}

function hasNonEmptyRecord(value: unknown): boolean {
  return Boolean(value && typeof value === 'object' && Object.keys(value as Record<string, unknown>).length > 0)
}

function hasSubstantiveReviewPlusResult(run: SuperAgentRun): boolean {
  const result = run.review_plus_result
  if (!hasNonEmptyRecord(result)) return false

  const record = result as Record<string, unknown>
  if (Number(record.finding_count) > 0) return true

  const report = record.report as Record<string, unknown> | undefined
  if (hasNonEmptyRecord(report)) {
    const findings = report?.findings
    if (Array.isArray(findings) && findings.length > 0) return true
    if (
      report?.satisfied_count != null
      || report?.not_satisfied_count != null
      || report?.insufficient_evidence_count != null
      || report?.critical_count != null
    ) {
      return true
    }
    if (String(report?.markdown || '').trim()) return true
  }

  const findings = record.findings
  if (Array.isArray(findings) && findings.length > 0) return true

  const specialistReviews = record.specialist_reviews
  if (Array.isArray(specialistReviews) && specialistReviews.length > 0) return true

  const smartTaskBoard = record.smart_task_board as Record<string, unknown> | undefined
  if (hasNonEmptyRecord(smartTaskBoard?.metadata) || hasNonEmptyRecord(smartTaskBoard?.tasks)) {
    return true
  }

  return false
}

function hasSubstantiveGncReviewResult(run: SuperAgentRun): boolean {
  const result = run.gnc_review_result
  if (!hasNonEmptyRecord(result)) return false

  const record = result as Record<string, unknown>
  const findings = record.findings
  if (Array.isArray(findings) && findings.length > 0) return true
  if (String(record.report_markdown || '').trim()) return true
  if (hasNonEmptyRecord(record.report)) return true
  if (hasNonEmptyRecord(record.editorial_synthesis)) return true
  if (hasNonEmptyRecord(record.chief_decision)) return true

  return false
}

/** run 是否已有可回看的结果工作台产物（completed/limited、结果阶段或审查报告等）。 */
export function hasTerminalReviewOutcome(run: SuperAgentRun): boolean {
  if (EXECUTION_RESULT_STATUSES.has(run.status)) return true
  if (run.wizard_step === 5) return true
  if (run.current_phase === 'review_results') return true
  if (run.completed_steps?.includes('review_results')) return true

  if (String(run.report_markdown || '').trim()) return true
  if (hasNonEmptyRecord(run.report_artifact)) return true

  if (hasSubstantiveReviewPlusResult(run)) return true
  if (hasSubstantiveGncReviewResult(run)) return true

  const reviewResultsArtifact = run.phase_artifacts?.review_results
  return hasNonEmptyRecord(reviewResultsArtifact)
}

function migrateLegacyPersistedStep(run: SuperAgentRun, persisted: number): WizardStep {
  if (run.status !== 'draft') {
    return persisted as WizardStep
  }
  if (persisted === 5 || hasTerminalReviewOutcome(run)) {
    return 5
  }
  // 旧版 step 4（确认解析过程和结果）→ 新版 step 3（文档解析）
  if (persisted >= 4 && hasPersistedParsePreview(run)) {
    return 3
  }
  return persisted as WizardStep
}

/** 根据 run 状态推断向导应展示的步骤（优先使用持久化的 wizard_step）。 */
export function resolveWizardStep(run: SuperAgentRun): WizardStep {
  if (hasTerminalReviewOutcome(run)) {
    return 5
  }
  if (run.status === 'running') {
    return 4
  }
  if (run.status === 'interrupted' || run.status === 'failed') {
    // 解析预览已就绪时允许回到步骤 3 修改方案后重新审查
    if (hasPersistedParsePreview(run)) {
      return 3
    }
    return 4
  }

  // draft：显式 wizard_step 优先（支持用户回退后刷新仍停留在较早步骤）
  if (run.status === 'draft') {
    const persisted = run.wizard_step
    if (typeof persisted === 'number' && persisted >= 1 && persisted <= 5) {
      return migrateLegacyPersistedStep(run, persisted)
    }
  }

  // 解析预览已就绪且审查未结束：停留在步骤 3，等待用户确认后再进入审查
  if (hasPersistedParsePreview(run)) {
    return 3
  }

  const persisted = run.wizard_step
  if (typeof persisted === 'number' && persisted >= 1 && persisted <= 5) {
    return migrateLegacyPersistedStep(run, persisted)
  }

  const hasMaterials = Boolean(run.materials.length || run.source_review_id)
  if (!hasMaterials) return 1

  // 步骤 3：文档解析（已有识别结果，尚未完成或需确认解析预览）
  if (hasPersistedClassification(run) || hasPersistedParsePreview(run)) {
    return 3
  }
  return 2
}

export function parsePreviewFromRun(run: SuperAgentRun): ParsePreviewResponse | null {
  const raw = run.parse_preview as ParsePreviewResponse | undefined
  if (!hasPersistedParsePreview(run) || !raw) return null
  return raw
}

export interface RestoredWizardState {
  step: WizardStep
  classification: MaterialClassification | null
  parsePreview: ParsePreviewResponse | null
  hasPersistedMaterials: boolean
}

export function restoreWizardStateFromRun(run: SuperAgentRun): RestoredWizardState {
  return {
    step: resolveWizardStep(run),
    classification: classificationFromRun(run),
    parsePreview: parsePreviewFromRun(run),
    hasPersistedMaterials: Boolean(run.materials.length || run.source_review_id),
  }
}

/** 恢复后是否需要服务端补跑识别（步骤 ≥2 且 run 未持久化 classification）。 */
export function needsServerClassify(run: SuperAgentRun, restored: RestoredWizardState): boolean {
  if (EXECUTION_RESULT_STATUSES.has(run.status) || hasTerminalReviewOutcome(run)) {
    return false
  }
  return restored.step >= 2 && !hasPersistedClassificationOnRun(run) && Boolean(run.materials.length)
}

/** 恢复后是否需要服务端补跑解析预览（步骤 3 且无 parse_preview；方案须已在步骤 2 persist）。 */
export function needsServerParsePreview(run: SuperAgentRun, restored: RestoredWizardState): boolean {
  return restored.step >= 3 && !restored.parsePreview && Boolean(run.materials.length)
}

/** 步骤 2 识别完成后是否应展示结果（等待用户确认后再进入步骤 3）。 */
export function shouldShowClassifyResults(step: WizardStep, classification: MaterialClassification | null): boolean {
  return step === 2 && Boolean(classification?.doc_type)
}

export interface ParsePreviewAutoStartInput {
  step: WizardStep
  hasClassification: boolean
  fileCount: number
  persistedMaterialCount: number
  hasParsePreview: boolean
  parseInFlight: boolean
  autoStartConsumed: boolean
}

/** 步骤 3 是否应自动触发一次 parse-preview（进入步骤、模式变更后重置 consumed）。 */
export function shouldAutoStartParsePreview(input: ParsePreviewAutoStartInput): boolean {
  if (input.step !== 3) return false
  if (input.autoStartConsumed) return false
  if (input.hasParsePreview) return false
  if (input.parseInFlight) return false
  if (!input.hasClassification) return false
  if (input.fileCount === 0 && input.persistedMaterialCount === 0) return false
  return true
}

/** 步骤 3 解析进行中或等待自动启动时应展示加载 UI，避免「准备解析」与「正在解析」来回闪。 */
export function shouldShowParseLoadingUi(
  step: WizardStep,
  parsePreview: ParsePreviewResponse | null,
  parseBusy: boolean,
  hasError: boolean,
): boolean {
  if (parsePreview) return false
  if (parseBusy) return true
  return step === 3 && !hasError
}

/** 步骤 3 仅在自动启动失败等需人工介入时展示手动开始按钮。 */
export function shouldShowParseStartCta(
  step: WizardStep,
  parsePreview: ParsePreviewResponse | null,
  parseBusy: boolean,
  hasError = false,
): boolean {
  return step === 3 && !parsePreview && !parseBusy && hasError
}
