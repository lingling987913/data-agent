'use client'

import { GATEKEEPING_TERMS } from '@/lib/aeroTerminology'

/**
 * Review-Plus V2 工作台详情
 *
 * 页面骨架与交互节奏对齐 GNC 评审工作台（review），
 * 数据与操作全部走 /api/v1/aero/review-plus-reviews 链路。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  classifyReviewPlusMaterials,
  confirmReviewPlusTraceLink,
  continueReviewPlus,
  getReviewPlusDetail,
  getReviewPlusGatekeeping,
  getReviewPlusReportMarkdown,
  parseReviewPlusMaterials,
  recheckReviewPlusGatekeeping,
  rejectReviewPlusTraceLink,
  reparseReviewPlusMaterial,
  restartReviewPlus,
  startReviewPlus,
  updateReviewPlusMaterialRole,
  uploadReviewPlusMaterials,
} from '@/features/review-plus-v2/api'
import DocumentPreviewModal from '@/features/review-plus-v2/components/DocumentPreviewModal'
import ReviewPlusEvidenceCompareOverlay from '@/features/review-plus-v2/components/ReviewPlusEvidenceCompareOverlay'
import ReviewPlusMoreTabsMenu from '@/features/review-plus-v2/components/ReviewPlusMoreTabsMenu'
import ReviewPlusDocumentPackagePanel from '@/features/review-plus-v2/components/ReviewPlusDocumentPackagePanel'
import ActionEmptyState from '@/features/review-plus-v2/components/workbench/ActionEmptyState'
import ReviewPlusCheckItemsTab from '@/features/review-plus-v2/components/workbench/ReviewPlusCheckItemsTab'
import ReviewPlusCoverageTab from '@/features/review-plus-v2/components/workbench/ReviewPlusCoverageTab'
import ReviewPlusCrossDocTab from '@/features/review-plus-v2/components/workbench/ReviewPlusCrossDocTab'
import ReviewPlusEventsTab from '@/features/review-plus-v2/components/workbench/ReviewPlusEventsTab'
import ReviewPlusFindingsTab from '@/features/review-plus-v2/components/workbench/ReviewPlusFindingsTab'
import ReviewPlusMaterialPackageModal from '@/features/review-plus-v2/components/ReviewPlusMaterialPackageModal'
import ReviewPlusOverviewTab from '@/features/review-plus-v2/components/workbench/ReviewPlusOverviewTab'
import ReviewPlusProgressHome from '@/features/review-plus-v2/components/workbench/ReviewPlusProgressHome'
import type { ReviewPlusConclusionPanelHandle } from '@/features/review-plus-v2/components/workbench/ReviewPlusConclusionPanel'
import ReviewPlusTraceabilityTab from '@/features/review-plus-v2/components/workbench/ReviewPlusTraceabilityTab'
import { useReviewPlusEvidenceSelection } from '@/features/review-plus-v2/hooks/useReviewPlusEvidenceSelection'
import type { WorkbenchSelection } from '@/features/review-plus-v2/utils/aeroDesignerWorkbenchUtils'
import ReviewPlusReportExportMenu from '@/features/review-plus-v2/components/ReviewPlusReportExportMenu'
import {
  REVIEW_PLUS_PRIMARY_TAB_KEYS,
  REVIEW_PLUS_SECONDARY_TAB_KEYS,
  REVIEW_PLUS_PIPELINE_STEPS,
  REVIEW_PLUS_TAB_LABELS,
  type ReviewPlusWorkbenchTabKey,
  resolveReviewPlusVisibleTabs,
  shouldShowReviewPlusContinueAction,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { getReviewPlusCompletedStepKeys } from '@/features/review-plus-v2/utils/reviewPlusWorkflowGraph'
import {
  formatReviewPlusScenarioLabel,
  isReviewPlusParseComplete,
  isReviewPlusPreReview,
  resolveReviewPlusDefaultWorkbenchTab,
  resolveReviewPlusOverviewTabLabel,
  resolveReviewPlusPhaseChipClass,
  resolveReviewPlusPrimaryProcessAction,
  resolveReviewPlusWorkbenchPhase,
  resolveReviewPlusWorkspaceMode,
  REVIEW_PLUS_PHASE_LABELS,
} from '@/features/review-plus-v2/utils/reviewPlusUx'
import type {
  ReviewPlusGatekeepingResult,
  ReviewPlusMaterialItem,
  ReviewPlusParserType,
  ReviewPlusTaskDetail,
} from '@/features/review-plus-v2/types'
import { STATUS_LABELS } from '@/features/review-plus-v2/types'
import { formatAgentIdLabel } from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'
import { LoadingState } from '@aqua/ui-core'

type TabKey = ReviewPlusWorkbenchTabKey

const VALID_TABS = new Set<TabKey>([
  'overview', 'flow', 'materials', 'check_items', 'findings', 'coverage', 'traceability', 'cross_doc', 'events',
])

const RUNNING_STATUSES = new Set([
  'parsing', 'classifying', 'structuring', 'rule_extracting', 'mapping',
  'reviewing', 'traceability_building', 'reporting', 'gatekeeping',
])

function resolveInitialTab(
  initialTab: string | undefined,
  task?: Pick<ReviewPlusTaskDetail, 'status' | 'events'>,
): TabKey {
  if (!task) {
    if (initialTab === 'report' || initialTab === 'flow') return 'overview'
    if (initialTab && VALID_TABS.has(initialTab as TabKey)) return initialTab as TabKey
    return 'materials'
  }
  return resolveReviewPlusDefaultWorkbenchTab(task, initialTab)
}

function headerActionClass(primary = false): string {
  const base = 'inline-flex min-h-9 items-center justify-center rounded-2xl px-3.5 text-[11px] font-medium transition-colors focus-visible:border-primaryAccent focus-visible:outline-none'
  if (primary) {
    return `${base} bg-brand text-white motion-safe:active:scale-[0.98] disabled:opacity-50`
  }
  return `${base} border border-border/30 text-primary hover:border-brand/40 disabled:opacity-50`
}

function latestWorkflowFailure(task: ReviewPlusTaskDetail): {
  stepLabel: string
  agentLabel: string
  errorCode: string
  errorMessage: string
} | null {
  const failures = (task.events || [])
    .filter((event) => String(event.type || '') === 'workflow_failed')
    .sort((a, b) => Number(b.sequence || 0) - Number(a.sequence || 0))
  const failure = failures[0]
  if (!failure) return null

  const payload = failure.payload || {}
  const failedStep = String(payload.failed_step || payload.step || '')
  const stepLabel = REVIEW_PLUS_PIPELINE_STEPS.find((step) => step.step_key === failedStep)?.label || failedStep || '未定位步骤'
  const agentId = String(payload.agent_id || '')
  return {
    stepLabel,
    agentLabel: agentId ? formatAgentIdLabel(agentId) : '未定位 Agent',
    errorCode: String(payload.error_code || ''),
    errorMessage: String(payload.error_message || payload.error || payload.message || '未记录错误详情'),
  }
}

function StatusGuide({
  task,
  gatekeeping,
  canStart,
  canContinue,
  parseComplete,
  parsing,
  onGoMaterials,
  onGoProgress,
  onGoConclusion,
  onStartReview,
  onContinueReview,
  onParseMaterials,
  starting,
  continuing,
  packageInView = false,
}: {
  task: ReviewPlusTaskDetail
  gatekeeping: ReviewPlusGatekeepingResult | null
  canStart: boolean
  canContinue: boolean
  parseComplete: boolean
  parsing: boolean
  onGoMaterials: () => void
  onGoProgress: () => void
  onGoConclusion: () => void
  onStartReview: () => void
  onContinueReview: () => void
  onParseMaterials: () => void
  starting: boolean
  continuing: boolean
  packageInView?: boolean
}) {
  const status = String(task.status)
  type Guide = {
    stage: string
    text: string
    action?: string
    onClick?: () => void
    color: string
    pulse?: boolean
  }

  let guide: Guide | null = null

  if (status === 'draft' || status === 'materials_uploaded') {
    guide = {
      stage: '送审准备',
      text: '请补齐检查需求、检查单、任务书与被审报告，确认材料角色后执行文档解析。',
      action: packageInView ? undefined : '查看送审包',
      onClick: packageInView ? undefined : onGoMaterials,
      color: 'bg-primaryAccent/8 border-primaryAccent/25 text-primaryAccent',
    }
  } else if (status === 'parsing' || parsing) {
    guide = {
      stage: '文档解析中',
      text: '正在执行 Step 3 材料解析，完成后即可启动文件组审查。',
      color: 'bg-primaryAccent/8 border-primaryAccent/25 text-primaryAccent',
      pulse: true,
    }
  } else if (!parseComplete && (task.materials?.length || 0) > 0 && isReviewPlusPreReview(task)) {
    guide = {
      stage: '待解析',
      text: '材料已上传，请先执行文档解析，再启动文件组审查。',
      action: parsing ? '解析中...' : '解析材料',
      onClick: onParseMaterials,
      color: 'bg-warning/8 border-warning/20 text-warning',
    }
  } else if (status === 'failed') {
    return null
  } else if (status === 'completed') {
    return null
  } else if (status === 'limited_pass') {
    guide = {
      stage: '受限停止',
      text: gatekeeping?.gate_summary || '审查链路已受限停止，请回到送审包补齐检查需求、检查单或材料角色后重新启动。',
      action: '检查送审包',
      onClick: onGoMaterials,
      color: 'bg-warning/8 border-warning/20 text-warning',
    }
  } else if (gatekeeping?.gate_status === 'blocked') {
    guide = {
      stage: GATEKEEPING_TERMS.blockedStage,
      text: gatekeeping.gate_summary || GATEKEEPING_TERMS.notPassedHint,
      action: '检查送审包',
      onClick: onGoMaterials,
      color: 'bg-destructive/5 border-destructive/20 text-destructive',
    }
  } else if (canContinue) {
    return null
  } else if (canStart) {
    guide = {
      stage: '可开始处理',
      text: '送审包已就绪，可开始本轮多文档符合性审查。',
      action: starting ? '开始中...' : '开始处理',
      onClick: onStartReview,
      color: 'bg-primaryAccent/8 border-primaryAccent/25 text-primaryAccent',
    }
  }

  if (!guide) return null

  return (
    <div className={`flex flex-col gap-3 rounded-lg border px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between ${guide.color}`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-md border border-current/20 bg-white/50 px-2 py-0.5 text-[10px] font-semibold">
          {guide.stage}
        </span>
        <span className="text-[11px] font-medium">{guide.text}</span>
        {guide.pulse ? <span className="w-1.5 h-1.5 rounded-full bg-current motion-safe:animate-pulse" /> : null}
      </div>
      {guide.action && guide.onClick ? (
        <button
          type="button"
          onClick={guide.onClick}
          disabled={(starting && guide.action === '开始中...') || (continuing && guide.action === '继续中...')}
          className="px-3 py-1 text-[10px] font-medium rounded-md bg-white/60 hover:bg-white/80 border border-current/20 transition-colors disabled:opacity-50"
        >
          {guide.action} →
        </button>
      ) : null}
    </div>
  )
}


interface Props {
  reviewId: string
  initialTab?: string
  initialAction?: string
}

export default function ReviewPlusV2WorkbenchDetail({ reviewId, initialTab = '', initialAction = '' }: Props) {
  const [task, setTask] = useState<ReviewPlusTaskDetail | null>(null)
  const [gatekeeping, setGatekeeping] = useState<ReviewPlusGatekeepingResult | null>(null)
  const [activeTab, setActiveTab] = useState<TabKey>(() => resolveInitialTab(initialTab))
  // task 加载后由 effect 同步默认 Tab
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [starting, setStarting] = useState(false)
  const [continuing, setContinuing] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [parserType, setParserType] = useState<ReviewPlusParserType>('auto')
  const [preview, setPreview] = useState<{ title: string; content: string } | null>(null)
  const [reportMarkdown, setReportMarkdown] = useState('')
  const [error, setError] = useState('')
  const [refreshError, setRefreshError] = useState('')
  const [findingsJudgmentFilter, setFindingsJudgmentFilter] = useState<'all' | 'not_satisfied' | 'insufficient_evidence' | 'not_applicable' | 'not_checked' | 'satisfied'>('all')
  const [highlightCheckItemId, setHighlightCheckItemId] = useState<string | undefined>()
  const [evidenceOverlay, setEvidenceOverlay] = useState<WorkbenchSelection | null>(null)
  const [packageModalOpen, setPackageModalOpen] = useState(false)
  const contentScrollRef = useRef<HTMLDivElement | null>(null)
  const conclusionPanelRef = useRef<ReviewPlusConclusionPanelHandle | null>(null)
  const prevStatusRef = useRef('')

  const evidenceBuilders = useReviewPlusEvidenceSelection(
    task ?? { materials: [] },
  )

  const loadTask = useCallback(async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const detail = await getReviewPlusDetail(reviewId)
      setTask(detail)
      setError('')
      setRefreshError('')
      if (detail.gatekeeping_result) setGatekeeping(detail.gatekeeping_result)
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载任务失败'
      if (silent) {
        setRefreshError(message)
        return
      }
      setError(message)
      setTask(null)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [reviewId])

  const loadGatekeeping = useCallback(async (force = false) => {
    try {
      const data = force
        ? await recheckReviewPlusGatekeeping(reviewId)
        : await getReviewPlusGatekeeping(reviewId)
      setGatekeeping(data)
    } catch {
      /* optional */
    }
  }, [reviewId])

  const loadReportMarkdown = useCallback(async () => {
    try {
      const md = await getReviewPlusReportMarkdown(reviewId)
      setReportMarkdown(md)
    } catch {
      setReportMarkdown(task?.report_markdown || task?.report?.markdown || '')
    }
  }, [reviewId, task?.report?.markdown, task?.report_markdown])

  const resolvedReportMarkdown = reportMarkdown || task?.report_markdown || task?.report?.markdown || ''

  const scrollToFullReport = useCallback(() => {
    setActiveTab('overview')
    window.requestAnimationFrame(() => {
      conclusionPanelRef.current?.expandFullReport()
    })
  }, [])

  const handleConfirmTraceLink = useCallback(async (linkId: string, rationale?: string) => {
    await confirmReviewPlusTraceLink(reviewId, linkId, { rationale })
    await loadTask(true)
  }, [loadTask, reviewId])

  const handleRejectTraceLink = useCallback(async (linkId: string, rationale: string) => {
    await rejectReviewPlusTraceLink(reviewId, linkId, { rationale })
    await loadTask(true)
  }, [loadTask, reviewId])

  const handleOpenEvidenceFromCoverage = useCallback((row: Parameters<typeof evidenceBuilders.buildFromCoverage>[0]) => {
    const selection = evidenceBuilders.buildFromCoverage(row)
    if (selection) {
      setEvidenceOverlay(selection)
      toast.success('已定位关联证据原文')
    }
  }, [evidenceBuilders])

  const handleOpenEvidenceFromFinding = useCallback((finding: Parameters<typeof evidenceBuilders.buildFromFinding>[0]) => {
    const selection = evidenceBuilders.buildFromFinding(finding)
    if (selection) {
      setEvidenceOverlay(selection)
      toast.success('已定位关联证据原文')
    }
  }, [evidenceBuilders])

  const handleOpenEvidenceFromTraceability = useCallback((row: Record<string, unknown>) => {
    const selection = evidenceBuilders.buildFromTraceability(row)
    if (selection) {
      setEvidenceOverlay(selection)
      toast.success('已定位关联证据原文')
    }
  }, [evidenceBuilders])

  const handleOpenEvidenceFromCrossDoc = useCallback((item: Record<string, unknown>) => {
    const selection = evidenceBuilders.buildFromCrossDoc(item)
    if (selection) {
      setEvidenceOverlay(selection)
      toast.success('已定位关联证据原文')
    }
  }, [evidenceBuilders])

  useEffect(() => {
    setLoading(true)
    void loadTask()
    void loadGatekeeping(false)
  }, [loadGatekeeping, loadTask])

  useEffect(() => {
    if (!task || initialTab) return
    setActiveTab(resolveInitialTab('', task))
  }, [initialTab, task])

  useEffect(() => {
    if (!task) return undefined
    const status = String(task.status)
    const shouldPoll =
      RUNNING_STATUSES.has(status) || shouldShowReviewPlusContinueAction(task)
    if (!shouldPoll) return undefined
    const timer = window.setInterval(() => { void loadTask(true) }, 8000)
    return () => window.clearInterval(timer)
  }, [loadTask, task])

  useEffect(() => {
    if (!task) return
    if (prevStatusRef.current === task.status) return
    const prevStatus = prevStatusRef.current
    prevStatusRef.current = String(task.status)
    if (task.status === 'completed' && prevStatus && prevStatus !== 'completed') {
      setActiveTab('overview')
    }
  }, [task])

  useEffect(() => {
    if (!task) return
    if (resolveReviewPlusWorkspaceMode(task) === 'package') return
    if (activeTab === 'materials') setActiveTab('overview')
  }, [activeTab, task])

  useEffect(() => {
    if (task?.status === 'completed') {
      void loadReportMarkdown()
    }
  }, [loadReportMarkdown, task?.status])

  const parseComplete = useMemo(
    () => (task ? isReviewPlusParseComplete(task) : false),
    [task],
  )

  const handleParseMaterials = useCallback(async (forceReparse = false) => {
    try {
      setParsing(true)
      setError('')
      await parseReviewPlusMaterials(reviewId, { forceReparse })
      await loadTask(true)
      await loadGatekeeping(true)
      toast.success('材料解析完成')
    } catch (err) {
      setError(err instanceof Error ? err.message : '材料解析失败')
      throw err
    } finally {
      setParsing(false)
    }
  }, [loadGatekeeping, loadTask, reviewId])

  const canContinue = useMemo(
    () => (task ? shouldShowReviewPlusContinueAction(task) : false),
    [task],
  )

  const canStart = useMemo(() => {
    if (!task?.materials?.length) return false
    if (!parseComplete) return false
    if (canContinue) return false
    if (['blocked', 'limited_pass'].includes(String(task.status))) return false
    if (gatekeeping?.gate_status === 'blocked') return false
    if (RUNNING_STATUSES.has(String(task.status))) return false
    return !['completed', 'reviewing', 'reporting'].includes(String(task.status))
  }, [canContinue, gatekeeping?.gate_status, parseComplete, task])

  const tabConfig = useMemo(() => {
    if (!task) {
      return {
        tabItems: [] as Array<[TabKey, string, boolean?]>,
        status: '',
        isPreReview: false,
        isExecuting: false,
        visibleTabs: new Set<TabKey>(),
      }
    }

    const status = String(task.status)
    const isPreReview = ['draft', 'materials_uploaded', 'classified', 'ready', 'limited_pass'].includes(status)
    const isExecuting = RUNNING_STATUSES.has(status) || canContinue
    const completedSteps = getReviewPlusCompletedStepKeys(task)
    const visibleTabs = resolveReviewPlusVisibleTabs(task, completedSteps)
    const checkItemCount = task.check_items?.length || 0
    const crossDocCount = task.cross_document_review_items?.length || 0
    const coverageRowCount = task.coverage_matrix?.summary?.row_count
      ?? task.coverage_matrix?.rows?.length
      ?? 0

    const tabDefs: Array<[TabKey, string, boolean?]> = [
      ['overview', resolveReviewPlusOverviewTabLabel(task)],
      ['findings', `${REVIEW_PLUS_TAB_LABELS.findings} (${task.findings?.length || 0})`],
      ['coverage', `${REVIEW_PLUS_TAB_LABELS.coverage} (${coverageRowCount})`],
      ['materials', REVIEW_PLUS_TAB_LABELS.materials, isPreReview && (!task.materials?.length || gatekeeping?.gate_status === 'blocked')],
      ['cross_doc', `${REVIEW_PLUS_TAB_LABELS.cross_doc} (${crossDocCount})`],
      ['check_items', `${REVIEW_PLUS_TAB_LABELS.check_items} (${checkItemCount})`],
      ['traceability', REVIEW_PLUS_TAB_LABELS.traceability],
      ['events', REVIEW_PLUS_TAB_LABELS.events],
    ]

    const primaryOrder: TabKey[] = ['overview', 'findings', 'cross_doc']
    const sorted = tabDefs
      .filter(([key]) => visibleTabs.has(key))
      .sort((a, b) => {
        const aPrimary = REVIEW_PLUS_PRIMARY_TAB_KEYS.has(a[0])
        const bPrimary = REVIEW_PLUS_PRIMARY_TAB_KEYS.has(b[0])
        if (aPrimary !== bPrimary) return aPrimary ? -1 : 1
        const ai = primaryOrder.indexOf(a[0])
        const bi = primaryOrder.indexOf(b[0])
        const aRank = ai >= 0 ? ai : 100
        const bRank = bi >= 0 ? bi : 100
        return aRank - bRank
      })

    return {
      tabItems: sorted,
      status,
      isPreReview,
      isExecuting,
      visibleTabs,
      completedSteps,
    }
  }, [canContinue, gatekeeping?.gate_status, task])

  useEffect(() => {
    if (!tabConfig.tabItems.length) return
    if (!tabConfig.tabItems.some(([key]) => key === activeTab)) {
      setActiveTab(tabConfig.tabItems[0]?.[0] || 'overview')
    }
  }, [activeTab, tabConfig.tabItems])

  const handleUpload = async (files: FileList | null, preferredRole?: string) => {
    if (!files?.length) return
    const selectedFiles = Array.from(files)
    try {
      setUploading(true)
      await uploadReviewPlusMaterials(reviewId, selectedFiles, parserType)
      if (preferredRole) {
        await Promise.all(
          selectedFiles.map((file) => updateReviewPlusMaterialRole(reviewId, file.name, { role: preferredRole })),
        )
      }
      await loadTask(true)
      await loadGatekeeping(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleReparseMaterial = async (material: ReviewPlusMaterialItem, nextParserType: ReviewPlusParserType) => {
    try {
      setUploading(true)
      await reparseReviewPlusMaterial(reviewId, material.name, nextParserType)
      await loadTask(true)
      await loadGatekeeping(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : '重新解析失败')
    } finally {
      setUploading(false)
    }
  }

  const handleReparseAllMaterials = async (nextParserType: ReviewPlusParserType) => {
    if (!task?.materials?.length) return
    try {
      setUploading(true)
      setError('')
      for (const material of task.materials) {
        await reparseReviewPlusMaterial(reviewId, material.name, nextParserType)
      }
      await loadTask(true)
      await loadGatekeeping(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : '批量重新解析失败')
    } finally {
      setUploading(false)
    }
  }

  const openWorkbenchTab = useCallback((
    tab: TabKey,
    options?: { judgmentFilter?: 'not_satisfied' },
  ) => {
    if (options?.judgmentFilter) {
      setFindingsJudgmentFilter(options.judgmentFilter)
    }
    setActiveTab(tab)
  }, [])

  const handleStartReview = async () => {
    try {
      setStarting(true)
      setError('')
      if (!parseComplete) {
        await handleParseMaterials()
      }
      await startReviewPlus(reviewId)
      await loadTask(true)
      toast.info('已开始处理，请确认送审包材料角色与门禁状态')
    } catch (err) {
      setError(err instanceof Error ? err.message : '开始处理失败')
      await loadGatekeeping(false)
    } finally {
      setStarting(false)
    }
  }

  const handleContinueReview = async () => {
    try {
      setContinuing(true)
      setError('')
      await continueReviewPlus(reviewId)
      await loadTask(true)
      setActiveTab('overview')
      toast.info('已提交继续处理，可在审查进度查看流程状态')
    } catch (err) {
      setError(err instanceof Error ? err.message : '继续处理失败，请稍后重试或联系管理员')
    } finally {
      setContinuing(false)
    }
  }

  const handleRestartReview = async () => {
    const confirmed = typeof window === 'undefined'
      || window.confirm('将清空本轮已生成的审查结果，并从送审包源头重新执行。确认继续？')
    if (!confirmed) return

    try {
      setRestarting(true)
      setError('')
      await restartReviewPlus(reviewId)
      await loadTask(true)
      setActiveTab('overview')
      toast.info('已从源头重新开始处理，可在审查进度查看流程状态')
    } catch (err) {
      setError(err instanceof Error ? err.message : '重新开始处理失败，请稍后重试或联系管理员')
    } finally {
      setRestarting(false)
    }
  }

  const handleRoleChange = async (material: ReviewPlusMaterialItem, role: string) => {
    try {
      await updateReviewPlusMaterialRole(reviewId, material.name, { role })
      await loadTask(true)
      await loadGatekeeping(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新角色失败')
    }
  }

  const handleConfirmRole = async (material: ReviewPlusMaterialItem) => {
    try {
      await updateReviewPlusMaterialRole(reviewId, material.name, {
        role: String(material.role || 'unknown'),
      })
      await loadTask(true)
      await loadGatekeeping(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认角色失败')
    }
  }

  const handleReclassify = async () => {
    try {
      setUploading(true)
      setError('')
      await classifyReviewPlusMaterials(reviewId)
      await loadTask(true)
      await loadGatekeeping(true)
      await handleParseMaterials()
    } catch (err) {
      setError(err instanceof Error ? err.message : '自动判定失败')
    } finally {
      setUploading(false)
    }
  }

  if (loading && !task) {
    return (
      <div className="h-full overflow-y-auto">
        <LoadingState rows={5} />
      </div>
    )
  }

  if (!task) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <ActionEmptyState
          title="审查任务不存在或加载失败"
          description={error || '当前工作台未能读取到任务详情，请返回列表重试。'}
          hint="任务可能已被删除，或后端尚未返回数据。"
        />
      </div>
    )
  }

  const status = tabConfig.status
  const workspaceMode = resolveReviewPlusWorkspaceMode(task)
  const isPackageWorkspace = workspaceMode === 'package'
  const isExecuting = tabConfig.isExecuting
  const visibleTabs = tabConfig.visibleTabs ?? new Set<TabKey>()
  const isPreReview = isReviewPlusPreReview(task)
  const notSatisfiedCount = (task.findings || []).filter((f) => f.judgment === 'not_satisfied').length
  const crossDocCount = task.cross_document_review_items?.length || 0
  const checkItemCount = task.check_items?.length || 0
  const TAB_ITEMS = tabConfig.tabItems
  const primaryTabItems = TAB_ITEMS.filter(([key]) => REVIEW_PLUS_PRIMARY_TAB_KEYS.has(key))
  const secondaryTabItems = TAB_ITEMS.filter(([key]) => REVIEW_PLUS_SECONDARY_TAB_KEYS.has(key))
  const workbenchPhase = resolveReviewPlusWorkbenchPhase(task, tabConfig.completedSteps ?? new Set())
  const showTabBar = !isPackageWorkspace && (primaryTabItems.length > 1 || secondaryTabItems.length > 0)
  const contentTab: TabKey = activeTab
  const isFailed = status === 'failed'
  const failureInfo = isFailed ? latestWorkflowFailure(task) : null
  const primaryProcessAction = isFailed
    ? null
    : resolveReviewPlusPrimaryProcessAction({
      status,
      canStart,
      canContinue,
    })
  const processBusy = starting || continuing || restarting || parsing
  const gateStatus = gatekeeping?.gate_status
  const hasResultMetrics = status === 'completed' || checkItemCount > 0 || notSatisfiedCount > 0 || crossDocCount > 0
  const showGatekeepingMetric = isPreReview || gateStatus === 'limited' || gateStatus === 'blocked'

  const compactMetrics: Array<{
    label: string
    value: string | number
    tone: string
    tab?: TabKey
    judgmentFilter?: 'not_satisfied'
    onClick?: () => void
  }> = []

  if (hasResultMetrics) {
    compactMetrics.push(
      { label: '检查项', value: checkItemCount, tone: 'text-primary' },
      {
        label: '不满足',
        value: notSatisfiedCount,
        tone: notSatisfiedCount > 0 ? 'text-destructive' : 'text-primary',
        tab: visibleTabs.has('findings') ? 'findings' : undefined,
        judgmentFilter: 'not_satisfied',
      },
      {
        label: '跨文档问题',
        value: crossDocCount,
        tone: crossDocCount > 0 ? 'text-destructive' : 'text-primary',
        tab: visibleTabs.has('cross_doc') ? 'cross_doc' : undefined,
      },
    )
  }

  if (showGatekeepingMetric) {
    compactMetrics.push({
      label: GATEKEEPING_TERMS.label,
      value: gateStatus === 'passed' ? '通过'
        : gateStatus === 'limited' ? '受限'
          : gateStatus === 'blocked' ? '阻断' : '—',
      tone: gateStatus === 'blocked' ? 'text-destructive' : 'text-primary',
      onClick: isPackageWorkspace ? undefined : () => setPackageModalOpen(true),
    })
  }

  const packagePanelProps = {
    materials: task.materials,
    gatekeeping,
    parserType,
    uploading,
    parseComplete,
    parsing,
    taskStatus: status,
    onParserTypeChange: setParserType,
    onFilesSelected: (files: FileList | null, preferredRole?: string) => void handleUpload(files, preferredRole),
    onRoleChange: (material: ReviewPlusMaterialItem, role: string) => void handleRoleChange(material, role),
    onConfirmRole: (material: ReviewPlusMaterialItem) => void handleConfirmRole(material),
    onReclassify: () => void handleReclassify(),
    onReparseMaterial: (material: ReviewPlusMaterialItem, nextParserType: ReviewPlusParserType) => void handleReparseMaterial(material, nextParserType),
    onReparseAll: (nextParserType: ReviewPlusParserType) => void handleReparseAllMaterials(nextParserType),
    onPreview: setPreview,
    onRecheckGate: () => void loadGatekeeping(true),
  }

  return (
    <div className="h-full flex flex-col gap-2.5 p-3 sm:p-4 overflow-y-auto md:overflow-hidden">
      <div className="aq-soft-panel rounded-xl p-3 shrink-0 space-y-2.5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="min-w-0 break-words text-[17px] font-medium text-primary sm:text-[18px]">{task.name}</h1>
              <span
                className={`inline-flex shrink-0 rounded-full border px-2.5 py-0.5 text-[10px] font-medium ${resolveReviewPlusPhaseChipClass(workbenchPhase)}`}
                data-testid="review-plus-v2-phase-chip"
                title={`系统状态：${STATUS_LABELS[status] || status}`}
              >
                {REVIEW_PLUS_PHASE_LABELS[workbenchPhase]}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted">
              {formatReviewPlusScenarioLabel(task.scenario) ? (
                <span>{formatReviewPlusScenarioLabel(task.scenario)}</span>
              ) : null}
              <span>材料 {task.materials?.length || 0} 份</span>
              <span>最近更新 {task.updated_at ? new Date(task.updated_at).toLocaleString('zh-CN') : '—'}</span>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => void loadTask(true)}
              className={headerActionClass(false)}
              data-testid="review-plus-v2-refresh"
            >
              刷新
            </button>
            {!isPackageWorkspace ? (
              <button
                type="button"
                onClick={() => setPackageModalOpen(true)}
                className={headerActionClass(false)}
                data-testid="review-plus-v2-open-package"
              >
                送审包
              </button>
            ) : null}
            {primaryProcessAction ? (
              <button
                type="button"
                disabled={processBusy}
                onClick={() => {
                  if (primaryProcessAction.kind === 'start') {
                    void handleStartReview()
                    return
                  }
                  void handleContinueReview()
                }}
                className={headerActionClass(true)}
                data-testid={primaryProcessAction.testId}
              >
                {processBusy ? primaryProcessAction.loadingLabel : primaryProcessAction.label}
              </button>
            ) : null}
            <ReviewPlusReportExportMenu
              task={task}
              reportMarkdown={resolvedReportMarkdown}
              testIdPrefix="review-plus-v2-export"
            />
          </div>
        </div>

        {error ? (
          <p className="text-[11px] text-destructive rounded-lg bg-destructive/5 px-3 py-2 border border-destructive/20">{error}</p>
        ) : null}

        {refreshError ? (
          <p className="text-[11px] text-warning rounded-lg bg-warning/8 px-3 py-2 border border-warning/20">
            刷新失败：{refreshError}。页面仍显示上次成功加载的数据。
          </p>
        ) : null}

        {isFailed ? (
          <p className="rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-2 text-[11px] text-muted">
            流程停在 {failureInfo?.stepLabel || '未定位步骤'}，请点击步骤详情中的失败节点查看日志并继续处理。
          </p>
        ) : null}

        <div className="flex flex-wrap gap-1.5">
          {compactMetrics.length > 0 ? compactMetrics.map((metric) => {
            const canClick = Boolean(metric.tab || metric.onClick)
            const inner = (
              <>
                {metric.label}
                <strong className={`text-[13px] font-medium ${metric.tone}`}>{metric.value}</strong>
              </>
            )
            if (!canClick) {
              return (
                <span
                  key={metric.label}
                  className="inline-flex min-h-8 items-center gap-1.5 rounded-2xl border border-border/30 bg-background px-3 text-[10px] text-muted"
                >
                  {inner}
                </span>
              )
            }
            return (
              <button
                key={metric.label}
                type="button"
                onClick={() => {
                  if (metric.onClick) {
                    metric.onClick()
                    return
                  }
                  openWorkbenchTab(metric.tab!, metric.judgmentFilter ? { judgmentFilter: metric.judgmentFilter } : undefined)
                }}
                className="inline-flex min-h-8 items-center gap-1.5 rounded-2xl border border-border/30 bg-background px-3 text-[10px] text-muted transition-colors hover:border-primaryAccent/40 hover:bg-primaryAccent/5"
              >
                {inner}
              </button>
            )
          }) : null}
        </div>

        {status !== 'completed' && status !== 'failed' ? (
        <StatusGuide
          task={task}
          gatekeeping={gatekeeping}
          canStart={canStart}
          canContinue={canContinue}
          parseComplete={parseComplete}
          parsing={parsing}
          onGoMaterials={() => {
            if (isPackageWorkspace) return
            setPackageModalOpen(true)
          }}
          onGoProgress={() => setActiveTab('overview')}
          onGoConclusion={() => setActiveTab('overview')}
          onStartReview={() => void handleStartReview()}
          onContinueReview={() => void handleContinueReview()}
          onParseMaterials={() => void handleParseMaterials()}
          starting={starting}
          continuing={continuing}
          packageInView={isPackageWorkspace}
        />
        ) : null}

        {task.scenario_reason ? (
          <p className="text-[11px] text-muted leading-relaxed">{task.scenario_reason}</p>
        ) : null}
      </div>

      {isPackageWorkspace ? (
        <div ref={contentScrollRef} className="min-h-0 flex-1 overflow-auto">
          <ReviewPlusDocumentPackagePanel {...packagePanelProps} />
        </div>
      ) : (
        <>
      {showTabBar ? (
      <div className="-mx-1 flex gap-0.5 overflow-x-auto border-b border-border/20 px-1 shrink-0 scrollbar-none">
        {primaryTabItems.map(([key, label, highlight]) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key)}
            className={`relative shrink-0 px-3.5 py-2 text-[11px] font-medium transition-colors ${
              activeTab === key
                ? 'border-b-2 border-primaryAccent text-primaryAccent'
                : 'text-muted/60 hover:text-primary'
            }`}
            data-testid={`review-plus-v2-tab-${key}`}
          >
            {label}
            {highlight ? (
              <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-destructive motion-safe:animate-pulse" aria-hidden />
            ) : null}
          </button>
        ))}
        {secondaryTabItems.length > 0 ? (
          <ReviewPlusMoreTabsMenu
            items={secondaryTabItems}
            activeTab={activeTab}
            onSelect={setActiveTab}
          />
        ) : null}
      </div>
      ) : null}

      <div ref={contentScrollRef} className="min-h-0 flex-1 overflow-auto">
        {TAB_ITEMS.some(([key]) => key === 'overview') || contentTab === 'overview' ? (
          <div className={contentTab === 'overview' ? undefined : 'hidden'} aria-hidden={contentTab !== 'overview'}>
            {workspaceMode === 'progress' ? (
              <ReviewPlusProgressHome
                task={task}
                reviewId={reviewId}
                isExecuting={isExecuting}
                visibleTabs={visibleTabs}
                onOpenTab={(tab, options) => {
                  if (options?.judgmentFilter) setFindingsJudgmentFilter(options.judgmentFilter)
                  setActiveTab(tab)
                }}
                onContinueReview={() => void handleContinueReview()}
                onRestartReview={() => void handleRestartReview()}
                continuing={continuing}
                restarting={restarting}
              />
            ) : (
              <ReviewPlusOverviewTab
                task={task}
                reviewId={reviewId}
                isExecuting={isExecuting}
                visibleTabs={visibleTabs}
                reportMarkdown={resolvedReportMarkdown}
                showConclusionPanel={status === 'completed'}
                conclusionPanelRef={conclusionPanelRef}
                onOpenTab={(tab) => setActiveTab(tab)}
                onExpandFullReport={scrollToFullReport}
              />
            )}
          </div>
        ) : null}

        {TAB_ITEMS.some(([key]) => key === 'findings') ? (
          <div className={contentTab === 'findings' ? 'h-full min-h-[520px]' : 'hidden'} aria-hidden={contentTab !== 'findings'}>
            <ReviewPlusFindingsTab
              checkItems={task.check_items || []}
              findings={task.findings || []}
              coverageRows={task.coverage_matrix?.rows || []}
              initialJudgmentFilter={findingsJudgmentFilter}
              onOpenEvidenceCompare={handleOpenEvidenceFromFinding}
              variant="focus"
              highlightCheckItemId={highlightCheckItemId}
              onLocateInCoverage={(checkItemId) => {
                setHighlightCheckItemId(checkItemId)
                setActiveTab('coverage')
              }}
            />
          </div>
        ) : null}

        {TAB_ITEMS.some(([key]) => key === 'coverage') ? (
          <div className={contentTab === 'coverage' ? undefined : 'hidden'} aria-hidden={contentTab !== 'coverage'}>
            <ReviewPlusCoverageTab
              task={task}
              onOpenEvidenceCompare={handleOpenEvidenceFromCoverage}
              highlightCheckItemId={highlightCheckItemId}
              onCheckItemClick={(checkItemId) => {
                setHighlightCheckItemId(checkItemId)
                setActiveTab('findings')
              }}
            />
          </div>
        ) : null}

        {TAB_ITEMS.some(([key]) => key === 'traceability') ? (
          <div className={contentTab === 'traceability' ? undefined : 'hidden'} aria-hidden={contentTab !== 'traceability'}>
            <ReviewPlusTraceabilityTab
              result={task.traceability_result}
              defaultViewMode="matrix"
              onConfirmTraceLink={handleConfirmTraceLink}
              onRejectTraceLink={handleRejectTraceLink}
              onOpenEvidenceCompare={handleOpenEvidenceFromTraceability}
            />
          </div>
        ) : null}

        {TAB_ITEMS.some(([key]) => key === 'cross_doc') ? (
          <div className={contentTab === 'cross_doc' ? undefined : 'hidden'} aria-hidden={contentTab !== 'cross_doc'}>
            <ReviewPlusCrossDocTab
              items={task.cross_document_review_items || []}
              onOpenEvidenceCompare={handleOpenEvidenceFromCrossDoc}
            />
          </div>
        ) : null}

        {TAB_ITEMS.some(([key]) => key === 'check_items') ? (
          <div className={contentTab === 'check_items' ? undefined : 'hidden'} aria-hidden={contentTab !== 'check_items'}>
            <ReviewPlusCheckItemsTab
              checkItems={task.check_items || []}
              sectionMappings={task.section_mappings}
            />
          </div>
        ) : null}

        {TAB_ITEMS.some(([key]) => key === 'events') ? (
          <div className={contentTab === 'events' ? undefined : 'hidden'} aria-hidden={contentTab !== 'events'}>
            <ReviewPlusEventsTab events={task.events || []} />
          </div>
        ) : null}
      </div>
        </>
      )}

      <ReviewPlusMaterialPackageModal
        open={packageModalOpen && !isPackageWorkspace}
        onClose={() => setPackageModalOpen(false)}
        {...packagePanelProps}
      />

      {preview ? (
        <DocumentPreviewModal
          title={preview.title}
          content={preview.content}
          onClose={() => setPreview(null)}
        />
      ) : null}

      {evidenceOverlay && task.materials?.length ? (
        <ReviewPlusEvidenceCompareOverlay
          task={task}
          reviewId={reviewId}
          selection={evidenceOverlay}
          onClose={() => setEvidenceOverlay(null)}
          onRefresh={() => loadTask(true)}
        />
      ) : null}
    </div>
  )
}
