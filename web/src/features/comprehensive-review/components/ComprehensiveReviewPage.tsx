'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import ComprehensiveReviewChat from '@/features/comprehensive-review/components/ComprehensiveReviewChat'
import ComprehensiveReviewHistoryPanel from '@/features/comprehensive-review/components/ComprehensiveReviewHistoryPanel'
import DeleteTaskConfirmDialog from '@/features/shared/components/DeleteTaskConfirmDialog'
import {
  buildMarkdownMaterialsFromPreview,
  getComprehensiveReviewMineruConfig,
} from '@/features/comprehensive-review/utils/comprehensiveReviewMaterials'
import {
  buildAgentReply,
  buildComprehensiveReviewMessages,
  createChatMessage,
  type ComprehensiveReviewMessage,
} from '@/features/comprehensive-review/utils/comprehensiveReviewMessages'
import { restoreComprehensiveReviewFromRun } from '@/features/comprehensive-review/utils/comprehensiveReviewRunRestore'
import {
  createSuperAgentRun,
  deleteSuperAgentRun,
  getSuperAgentRun,
  interruptSuperAgentRun,
  listSuperAgentRuns,
  parseMaterialsPreview,
  resumeSuperAgentRun,
  updateSuperAgentRun,
} from '@/features/super-agent/api'
import type { CreateSuperAgentRunInput, ParsePreviewResponse, SuperAgentRoute, SuperAgentRun } from '@/features/super-agent/types'
import { routeFromClassification } from '@/features/super-agent/utils/routeFromClassification'
import {
  clearRunIdFromUrl,
  getRunIdFromUrl,
  replaceRunIdInUrl,
} from '@/features/super-agent/utils/superAgentWizardRecovery'
import { COMPREHENSIVE_REVIEW_TERMS } from '@/lib/aeroTerminology'

const POLL_INTERVAL_MS = 2500
const STALE_RUNNING_MS = 120_000
const COMPREHENSIVE_REVIEW_PATH = '/comprehensive-review'

const INITIAL_MANUAL_MESSAGES: ComprehensiveReviewMessage[] = [
  createChatMessage(
    'assistant',
    '综合审查 Agent',
    '你好，我是综合审查 Agent。请在下方输入审查目标并附加文件，我会先按 .env 中配置的 MinerU 解析模式生成 Markdown，再自动执行 GNC 或文件组审查。',
    { status: 'awaiting_confirm', chips: ['等待指令', '支持多文件'] },
  ),
]

function isStaleRunning(run: SuperAgentRun | null): boolean {
  if (!run || run.status !== 'running') return false
  const updatedAt = Date.parse(run.updated_at || run.created_at || '')
  if (Number.isNaN(updatedAt)) return false
  return Date.now() - updatedAt > STALE_RUNNING_MS
}

function shouldPoll(run: SuperAgentRun | null): boolean {
  return Boolean(run && run.status === 'running')
}

function resolveComprehensiveRoute(
  selectedRoute: SuperAgentRoute,
  preview: ParsePreviewResponse,
): SuperAgentRoute {
  if (selectedRoute !== 'auto') return selectedRoute
  return routeFromClassification(
    preview.classification?.recommended_route || 'auto',
    preview.classification,
  )
}

function buildComprehensiveDraftRunInput(): CreateSuperAgentRunInput {
  return {
    name: `${COMPREHENSIVE_REVIEW_TERMS.defaultRunName} ${new Date().toLocaleDateString('zh-CN')}`,
    objective: COMPREHENSIVE_REVIEW_TERMS.objectivePlaceholder,
    processing_mode: 'OPTIMAL',
    input_mode: 'upload',
    source_review_id: '',
    requested_route: 'auto',
    review_mode: 'full',
    execute: false,
    materials: [],
  }
}

export default function ComprehensiveReviewPage() {
  const [files, setFiles] = useState<File[]>([])
  const [objective, setObjective] = useState<string>(COMPREHENSIVE_REVIEW_TERMS.objectivePlaceholder)
  const [selectedRoute, setSelectedRoute] = useState<SuperAgentRoute>('auto')
  const mineruConfig = useMemo(() => getComprehensiveReviewMineruConfig(), [])
  const [preview, setPreview] = useState<ParsePreviewResponse | null>(null)
  const [run, setRun] = useState<SuperAgentRun | null>(null)
  const [selectedRunId, setSelectedRunId] = useState('')
  const [historyRuns, setHistoryRuns] = useState<SuperAgentRun[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyRefreshing, setHistoryRefreshing] = useState(false)
  const [deleteTargetRun, setDeleteTargetRun] = useState<SuperAgentRun | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deletingRunId, setDeletingRunId] = useState('')
  const [creatingTask, setCreatingTask] = useState(false)
  const [interruptBusy, setInterruptBusy] = useState(false)
  const [draftMessage, setDraftMessage] = useState('')
  const [manualMessages, setManualMessages] = useState<ComprehensiveReviewMessage[]>(INITIAL_MANUAL_MESSAGES)
  const [busy, setBusy] = useState(false)
  const [resumeBusy, setResumeBusy] = useState(false)
  const [error, setError] = useState('')
  const [pollingEnabled, setPollingEnabled] = useState(true)
  const initialUrlRunLoaded = useRef(false)

  const refreshHistory = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false
    try {
      if (silent) setHistoryRefreshing(true)
      else setHistoryLoading(true)
      const nextRuns = await listSuperAgentRuns()
      setHistoryRuns(nextRuns)
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载历史任务失败'
      if (!silent) setError(message)
    } finally {
      if (silent) setHistoryRefreshing(false)
      else setHistoryLoading(false)
    }
  }, [])

  const applyRestoredRun = useCallback((nextRun: SuperAgentRun) => {
    const restored = restoreComprehensiveReviewFromRun(nextRun)
    setSelectedRunId(nextRun.run_id)
    setRun(restored.run)
    setObjective(restored.objective)
    setSelectedRoute(restored.selectedRoute)
    setPreview(restored.preview)
    setManualMessages(restored.manualMessages)
    setFiles([])
    setError(restored.error)
    setPollingEnabled(true)
    replaceRunIdInUrl(nextRun.run_id, COMPREHENSIVE_REVIEW_PATH)
  }, [])

  const selectRun = useCallback(async (target: SuperAgentRun | string) => {
    const runId = typeof target === 'string' ? target : target.run_id
    if (!runId) return
    setError('')
    try {
      const nextRun = typeof target === 'string' ? await getSuperAgentRun(runId) : target
      applyRestoredRun(nextRun)
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载历史任务失败'
      setError(message)
      toast.error(message)
    }
  }, [applyRestoredRun])

  const resetToNewTask = useCallback(() => {
    setSelectedRunId('')
    setRun(null)
    setPreview(null)
    setFiles([])
    setDraftMessage('')
    setObjective(COMPREHENSIVE_REVIEW_TERMS.objectivePlaceholder)
    setSelectedRoute('auto')
    setManualMessages(INITIAL_MANUAL_MESSAGES)
    setError('')
    setPollingEnabled(true)
    clearRunIdFromUrl(COMPREHENSIVE_REVIEW_PATH)
  }, [])

  const applyNewDraftRun = useCallback((draft: SuperAgentRun) => {
    setSelectedRunId(draft.run_id)
    setRun(draft)
    setPreview(null)
    setFiles([])
    setDraftMessage('')
    setObjective(COMPREHENSIVE_REVIEW_TERMS.objectivePlaceholder)
    setSelectedRoute('auto')
    setManualMessages(INITIAL_MANUAL_MESSAGES)
    setError('')
    setPollingEnabled(true)
    replaceRunIdInUrl(draft.run_id, COMPREHENSIVE_REVIEW_PATH)
  }, [])

  const handleNewTask = useCallback(async () => {
    setCreatingTask(true)
    setError('')
    try {
      const draft = await createSuperAgentRun(buildComprehensiveDraftRunInput())
      applyNewDraftRun(draft)
      setHistoryRuns((current) => {
        const without = current.filter((item) => item.run_id !== draft.run_id)
        return [draft, ...without]
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : '新建任务失败'
      setError(message)
      toast.error(message)
    } finally {
      setCreatingTask(false)
    }
  }, [applyNewDraftRun])

  useEffect(() => {
    void refreshHistory()
  }, [refreshHistory])

  useEffect(() => {
    if (initialUrlRunLoaded.current) return
    initialUrlRunLoaded.current = true
    const runId = getRunIdFromUrl()
    if (runId) void selectRun(runId)
  }, [selectRun])

  useEffect(() => {
    if (!run || !shouldPoll(run) || !pollingEnabled) return
    const runId = run.run_id
    let cancelled = false
    const timer = window.setInterval(async () => {
      try {
        const next = await getSuperAgentRun(runId)
        if (!cancelled) {
          setRun(next)
          setHistoryRuns((current) => current.map((item) => (item.run_id === next.run_id ? next : item)))
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '刷新综合审查进度失败')
      }
    }, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [run, pollingEnabled])

  const canResume = Boolean(
    run
    && (run.status === 'interrupted' || run.status === 'failed' || isStaleRunning(run))
  )

  const canManualInterrupt = Boolean(run?.status === 'running')

  const messages = useMemo(
    () => buildComprehensiveReviewMessages({
      manualMessages,
      files,
      preview,
      run,
      error,
      mineruLabel: mineruConfig.displayLabel,
    }),
    [manualMessages, files, preview, run, error, mineruConfig.displayLabel],
  )

  const handleStart = useCallback(async (objectiveOverride?: string) => {
    if (!files.length) return
    const overrideText = typeof objectiveOverride === 'string' ? objectiveOverride : ''
    const reviewObjective = (overrideText || objective).trim() || COMPREHENSIVE_REVIEW_TERMS.objectivePlaceholder
    if (!mineruConfig.parserType || !mineruConfig.parseMode) {
      const message = '请先在 .env 中配置 NEXT_PUBLIC_COMPREHENSIVE_REVIEW_MINERU_PARSER 和 NEXT_PUBLIC_COMPREHENSIVE_REVIEW_MINERU_PARSE_MODE'
      setError(message)
      toast.error(message)
      return
    }
    setBusy(true)
    setError('')
    setPreview(null)
    setPollingEnabled(true)
    const draftRunId = run?.status === 'draft' ? run.run_id : ''
    try {
      const nextPreview = await parseMaterialsPreview(
        files,
        'OPTIMAL',
        reviewObjective,
        null,
        {
          parserType: mineruConfig.parserType,
          mineruParseMode: mineruConfig.parseMode,
        },
      )
      setPreview(nextPreview)
      const materials = buildMarkdownMaterialsFromPreview(nextPreview)
      if (!materials.length || materials.every((item) => !item.content?.trim())) {
        throw new Error('MinerU 解析未生成可用于审查的 Markdown 内容')
      }
      const requestedRoute = resolveComprehensiveRoute(selectedRoute, nextPreview)
      const runPayload: CreateSuperAgentRunInput = {
        name: `${COMPREHENSIVE_REVIEW_TERMS.defaultRunName} ${new Date().toLocaleDateString('zh-CN')}`,
        objective: reviewObjective,
        processing_mode: 'OPTIMAL',
        input_mode: 'upload',
        source_review_id: '',
        requested_route: requestedRoute,
        review_mode: 'full',
        execute: true,
        materials,
        classification: nextPreview.classification,
      }
      const nextRun = draftRunId
        ? await updateSuperAgentRun(draftRunId, runPayload)
        : await createSuperAgentRun(runPayload)
      applyRestoredRun(nextRun)
      setHistoryRuns((current) => {
        const without = current.filter((item) => item.run_id !== nextRun.run_id)
        return [nextRun, ...without]
      })
      toast.success('综合审查已启动')
    } catch (err) {
      const message = err instanceof Error ? err.message : '综合审查启动失败'
      setError(message)
      toast.error(message)
    } finally {
      setBusy(false)
    }
  }, [applyRestoredRun, files, mineruConfig.parseMode, mineruConfig.parserType, objective, run, selectedRoute])

  const handleSendMessage = useCallback(async () => {
    const text = draftMessage.trim()
    if (!text && !files.length) return
    const nextObjective = text || objective
    if (text) {
      setObjective(nextObjective)
      setManualMessages((current) => [
        ...current,
        createChatMessage('user', '你', text, { status: 'completed' }),
      ])
    }
    setDraftMessage('')

    const shouldStart = files.length > 0 && (!run || run.status === 'draft') && !preview && !busy
    if (shouldStart) {
      setManualMessages((current) => [
        ...current,
        createChatMessage(
          'assistant',
          '综合审查 Agent',
          '收到，我将使用当前附件启动综合审查：先按 .env 中配置的 MinerU 模式解析，再把 Markdown 交给综合审查链路。',
          { status: 'running', chips: ['启动审查', mineruConfig.displayLabel] },
        ),
      ])
      await handleStart(nextObjective)
      return
    }

    setManualMessages((current) => [
      ...current,
      buildAgentReply({ text, files, preview, run, canResume, mineruLabel: mineruConfig.displayLabel }),
    ])
  }, [busy, canResume, draftMessage, files, handleStart, mineruConfig.displayLabel, objective, preview, run])

  const handleResume = useCallback(async () => {
    if (!run) return
    setResumeBusy(true)
    setError('')
    setPollingEnabled(true)
    try {
      const resumed = await resumeSuperAgentRun(run.run_id)
      applyRestoredRun(resumed)
      void refreshHistory({ silent: true })
      toast.success('已继续审查')
    } catch (err) {
      const message = err instanceof Error ? err.message : '继续审查失败'
      setError(message)
      toast.error(message)
    } finally {
      setResumeBusy(false)
    }
  }, [applyRestoredRun, refreshHistory, run])

  const handleInterrupt = useCallback(() => {
    setPollingEnabled(false)
    setRun(null)
    setPreview(null)
    setSelectedRunId('')
    setError('')
    clearRunIdFromUrl(COMPREHENSIVE_REVIEW_PATH)
    toast.message('已中断当前前端审查会话，可在左侧历史任务中重新打开')
  }, [])

  const handleManualInterrupt = useCallback(async () => {
    if (!run?.run_id || run.status !== 'running') return
    if (!window.confirm('确认中断当前审查？中断后可点击「继续审查」恢复。')) return
    setInterruptBusy(true)
    setError('')
    try {
      const interrupted = await interruptSuperAgentRun(run.run_id)
      setPollingEnabled(false)
      setRun(interrupted)
      setHistoryRuns((current) => current.map((item) => (
        item.run_id === interrupted.run_id ? interrupted : item
      )))
      toast.success('已手动中断，可继续审查恢复')
    } catch (err) {
      const message = err instanceof Error ? err.message : '手动中断失败'
      setError(message)
      toast.error(message)
    } finally {
      setInterruptBusy(false)
    }
  }, [run])

  const handleDeleteRequest = useCallback((target: SuperAgentRun) => {
    setDeleteTargetRun(target)
    setDeleteDialogOpen(true)
  }, [])

  const handleDeleteCancel = useCallback(() => {
    if (deletingRunId) return
    setDeleteDialogOpen(false)
    setDeleteTargetRun(null)
  }, [deletingRunId])

  const handleDeleteConfirm = useCallback(async (force: boolean) => {
    if (!deleteTargetRun) return
    const runId = deleteTargetRun.run_id
    setDeletingRunId(runId)
    try {
      const result = await deleteSuperAgentRun(runId, { force })
      if (!result.deleted) {
        toast.error('任务不存在或已被删除')
        return
      }
      if (selectedRunId === runId) resetToNewTask()
      setHistoryRuns((current) => current.filter((item) => item.run_id !== runId))
      void refreshHistory({ silent: true })
      toast.success('任务已删除')
      setDeleteDialogOpen(false)
      setDeleteTargetRun(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : '删除任务失败'
      toast.error(message)
    } finally {
      setDeletingRunId('')
    }
  }, [deleteTargetRun, refreshHistory, resetToNewTask, selectedRunId])

  return (
    <div className="mx-auto max-w-[1480px] px-4 py-5">
      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <ComprehensiveReviewHistoryPanel
          runs={historyRuns}
          selectedRunId={selectedRunId}
          loading={historyLoading}
          refreshing={historyRefreshing}
          deletingRunId={deletingRunId}
          creatingTask={creatingTask}
          onSelect={(item) => { void selectRun(item) }}
          onDelete={handleDeleteRequest}
          onRefresh={() => { void refreshHistory({ silent: true }) }}
          onNewTask={() => { void handleNewTask() }}
        />
        <ComprehensiveReviewChat
          files={files}
          objective={objective}
          selectedRoute={selectedRoute}
          draftMessage={draftMessage}
          messages={messages}
          run={run}
          busy={busy}
          canResume={canResume}
          resumeBusy={resumeBusy}
          canManualInterrupt={canManualInterrupt}
          interruptBusy={interruptBusy}
          onObjectiveChange={setObjective}
          onSelectedRouteChange={setSelectedRoute}
          onDraftMessageChange={setDraftMessage}
          onFilesChange={setFiles}
          onStart={handleStart}
          onSendMessage={handleSendMessage}
          onResume={handleResume}
          onInterrupt={handleInterrupt}
          onManualInterrupt={() => { void handleManualInterrupt() }}
        />
      </div>
      <DeleteTaskConfirmDialog
        run={deleteTargetRun}
        open={deleteDialogOpen}
        deleting={Boolean(deletingRunId)}
        onCancel={handleDeleteCancel}
        onConfirm={(force) => { void handleDeleteConfirm(force) }}
      />
    </div>
  )
}
