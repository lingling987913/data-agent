/** 产品运行态术语 — 前端展示文案单一来源 */

export const APP_TERMS = {
  brandName: '数据智能体',
  brandAbbr: '智审',
  tagline: '智能体审查工作台',
  pageTitle: '数据智能体 — 智能审查工作台',
  pageDescription: '工程文档智能审查工作台',
} as const

export const GATEKEEPING_TERMS = {
  label: '送审包准入',
  statusLabel: '准入状态',
  check: '送审包准入检查',
  recheck: '重新准入检查',
  rechecked: '准入复检',
  passed: '准入通过',
  blocked: '准入阻断',
  blockedStage: '准入阻断',
  limitedPass: '有条件准入',
  passWithNote: '带说明通过',
  notPassedHint: '送审包未通过准入检查，请补齐必备材料或修正角色后重试。',
  loadFailed: '准入状态加载失败',
  checking: '正在核对送审包准入状态。',
  notReturned: '准入状态尚未返回。',
  closureGate: '需求闭环准入判定',
  notPassedApi: '准入未通过',
  autoCheckHint: '上传材料后将自动执行送审包准入检查',
  packageTitle: '送审包准入',
  checkActionHint: '检查准入结果并启动审查',
  verifyBeforeStart: '核对准入结果后启动文件组审查',
  executeCheck: '判定材料角色并执行送审包准入检查',
} as const

export const REVIEW_PLUS_TERMS = {
  workbench: '文件组审查工作台',
  nav: '文件组审查',
  defaultName: '文件组审查',
  moduleLabel: '文件组审查',
  createTitle: '创建文件组审查任务',
  flowTitle: '文件组审查流程',
  sourceIdLabel: '审查任务 ID',
} as const

export const REVIEW_CAPABILITY_TERMS = {
  gncExpert: 'GNC 专家审查',
  smartDynamic: '智能动态审查',
  fileGroup: '文件组审查',
  /** 三种平级审查能力，由智能审查 / 综合审查入口自动路由 */
  peerItems: ['GNC 专家审查', '智能动态审查', '文件组审查'] as const,
} as const

export const COMPREHENSIVE_REVIEW_TERMS = {
  nav: '综合审查',
  homeTitle: '综合审查',
  homeForm: '对话',
  homeSubtitle: '以对话方式描述审查目标并附加文件，系统自动解析并路由至合适的审查路径',
  homeTags: REVIEW_CAPABILITY_TERMS.peerItems,
  workbench: '综合审查工作台',
  defaultRunName: '综合审查任务',
  objectivePlaceholder: '请描述本次审查目标，例如：对上传材料执行综合符合性审查并输出风险结论。',
} as const

export const SUPER_AGENT_TERMS = {
  nav: '智能审查',
  homeTitle: '智能审查',
  homeForm: '工作台',
  homeSubtitle: '以向导工作台上传材料、识别场景并执行审查，系统自动路由至合适的审查路径',
  homeTags: REVIEW_CAPABILITY_TERMS.peerItems,
  consoleTitle: '智能审查控制台',
  defaultRunName: '智能审查任务',
  wizardTitle: '智能审查工作台',
  skillTraces: '技能执行轨迹',
  benchmark: '基准测试',
  selectRun: '请选择一个执行任务',
  noRuns: '暂无执行任务',
  createRun: '新建执行任务',
} as const

/** 智能审查处理过程 — 航天业务术语 */
export const SUPER_AGENT_PROCESSING_TERMS = {
  llmTraceTitle: 'LLM 处理记录',
  noLlmTrace: '暂无 LLM 处理记录',
  phaseSummary: '阶段概要',
  agentExecution: '智能体执行',
  toolCall: '工具调用',
  inputSummary: '输入摘要',
  outputSummary: '输出摘要',
  stageFindings: '阶段性输出',
  relatedEvidence: '关联证据',
  receiveDelegation: '接收审查任务分派',
  clauseMaterialMapping: '标准条款与型号资料映射',
  formReviewOpinion: '形成审查意见',
  returnConclusion: '回传审查结论',
  materialClassification: '型号资料分类识别',
  complianceJudgment: '符合性判读',
  coverageMatrix: '条款覆盖矩阵',
  parallelDelegation: '并行任务分派',
  mergeResults: '子任务结果汇合',
  synthesizeConclusion: '综合审查结论',
} as const

/** 智能体路由 — API 枚举值 → 展示文案 */
export const ROUTE_LABELS: Record<string, string> = {
  auto: '自动',
  smart: '通用审查',
  review_plus: '文件组审查',
  gnc_review: 'GNC 审查',
  gnc_review_only: 'GNC 专项',
  structure_only: '结构化解析',
  hybrid: '混合审查',
}

/** 审查场景 — 材料分类推荐路由 → 展示文案 */
export const SCENE_LABELS: Record<string, string> = {
  auto: '智能综合审查',
  smart: '智能综合审查',
  review_plus: '标准设计审查',
  gnc_review_only: 'GNC 专项审查',
  gnc_review: 'GNC 专项审查',
  hybrid: '混合审查',
  structure_only: '结构化解析',
}

/** 处理模式 — API 枚举值 → 展示文案 */
export const PROCESSING_MODE_LABELS: Record<string, string> = {
  OPTIMAL: '均衡模式',
  HIGH_ACCURACY: '高精度模式',
  HIGH_SPEED: '高速模式',
}

/** 审查模式 */
export const REVIEW_MODE_LABELS: Record<string, string> = {
  full: '完整审查',
  single_doc: '单文档',
  multi_doc: '多文档',
}

/** 解析器类型 — API 枚举值 → 展示文案 */
export const PARSER_TYPE_LABELS: Record<string, string> = {
  auto: '自动选择',
  local: '本地解析',
  mineru: 'MinerU 本地',
  mineru_agent: 'MinerU 联网',
  mineru_via_pdf: 'MinerU 联网',
  ragflow: 'RAGFlow',
}

/** Super Agent / Agent 运行状态 */
export const AGENT_RUN_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  running: '运行中',
  interrupted: '已中断',
  completed: '已完成',
  failed: '失败',
  limited: '有限完成',
  skipped: '已跳过',
}

export function resolveUiLabel(
  labels: Record<string, string>,
  key: string | undefined | null,
  fallback = '—',
): string {
  const normalized = String(key || '').trim()
  if (!normalized) return fallback
  return labels[normalized] ?? normalized
}

/** 耗时毫秒 → 中文展示 */
export function formatElapsedMs(ms: number | undefined | null): string {
  if (typeof ms !== 'number' || Number.isNaN(ms)) return '—'
  if (ms < 1000) return `${ms} 毫秒`
  return `${(ms / 1000).toFixed(1)} 秒`
}
