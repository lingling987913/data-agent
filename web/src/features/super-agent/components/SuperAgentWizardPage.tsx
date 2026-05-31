'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  Loader2,
  Paperclip,
  RefreshCw,
  Rocket,
  Search,
  Sparkles,
  X,
  XCircle,
} from 'lucide-react'
import { MATERIAL_ROLE_LABELS } from '@/features/review-plus-shared/types'
import {
  PROCESSING_MODE_LABELS,
  ROUTE_LABELS,
  SCENE_LABELS,
  SUPER_AGENT_TERMS,
  resolveUiLabel,
} from '@/lib/aeroTerminology'
import { classifyMaterials, classifyRunMaterials, createSuperAgentRun, getSuperAgentRun, parseMaterialsPreview, parsePreviewFromRun, resumeSuperAgentRun, reviewSuperAgentRun, saveWizardCheckpoint, updateSuperAgentRun } from '@/features/super-agent/api'
import AdaptiveRouterCard from '@/features/super-agent/components/AdaptiveRouterCard'
import ClassifyBusinessSummary from '@/features/super-agent/components/ClassifyBusinessSummary'
import ParseAdmissionSummary from '@/features/super-agent/components/ParseAdmissionSummary'
import PostParseReviewPlanSection from '@/features/super-agent/components/PostParseReviewPlanSection'
import ReviewModeCardPicker from '@/features/super-agent/components/ReviewModeCardPicker'
import ParsePreviewPanel from '@/features/super-agent/components/ParsePreviewPanel'
import SuperAgentProcessingView from '@/features/super-agent/components/SuperAgentProcessingView'
import SuperAgentResultStep from '@/features/super-agent/components/SuperAgentResultStep'
import { buildParseAdmissionSummary } from '@/features/super-agent/utils/parseAdmissionSummary'
import { mergePostParseClassification } from '@/features/super-agent/utils/mergePostParseClassification'
import { filesToMaterials } from '@/features/super-agent/utils/materialFiles'
import {
  fingerprintWizardMaterials,
  materialsWizardInputsChanged,
} from '@/features/super-agent/utils/superAgentMaterialsFingerprint'
import { fallbackClassifyFromFileNames, routeFromClassification } from '@/features/super-agent/utils/routeFromClassification'
import {
  recommendedReviewModeCard,
  resolveCheckpointRoute,
  resolveEffectiveRoute,
  resolveReviewStartRoute,
  routeForReviewModeCardChange,
  type ReviewModeCard,
  type ReviewModeCardId,
} from '@/features/super-agent/utils/reviewRouteResolution'
import {
  DEFAULT_REVIEW_OBJECTIVE,
  DRAFT_REVIEW_OBJECTIVE,
  isPersistableReviewObjective,
  resolveReviewObjective,
} from '@/features/super-agent/utils/reviewObjective'
import {
  buildSuperAgentExportMarkdown,
} from '@/features/super-agent/utils/superAgentProcessingViewModel'
import { buildFallbackSuperAgentRun } from '@/features/super-agent/utils/superAgentResumeState'
import {
  buildSuperAgentRunUrl,
  classificationFromRun,
  clearRunIdFromUrl,
  RUN_ID_QUERY_KEY,
  needsServerClassify,
  canNavigateToWizardStep,
  canPersistWizardCheckpoint,
  canRerunReviewOnRun,
  formatWizardStepBreadcrumb,
  hasPersistedClassificationOnRun,
  hasRunParseArtifact,
  replaceRunIdInUrl,
  resolveMaxReachableWizardStep,
  resolveWizardStepLabels,
  resolveWizardStepNavHint,
  restoreWizardStateFromRun,
  reviewModeCardFromRun,
  processingModeFromRun,
  parsePreviewFromRun as parsePreviewFromPersistedRun,
  shouldAutoStartParsePreview,
  shouldShowParseLoadingUi,
  shouldShowParseStartCta,
  type WizardStep,
} from '@/features/super-agent/utils/superAgentWizardRecovery'
import type {
  CreateSuperAgentRunInput,
  MaterialClassification,
  ParsePreviewResponse,
  SuperAgentMaterialInput,
  SuperAgentRoute,
  SuperAgentRun,
  SaveWizardCheckpointInput,
  ReviewModeSelection,
} from '@/features/super-agent/types'
import { PARSING_TIER_LABELS } from '@/features/super-agent/utils/parsePreviewFormat'

function reviewModeCardToSelection(card: ReviewModeCard): ReviewModeSelection {
  return card === 'special' ? 'specialized' : card
}

function reviewModeSelectionToCard(selection: ReviewModeSelection): ReviewModeCard {
  return selection === 'specialized' ? 'special' : selection
}

interface UploadedFileItem {
  id: string
  file: File
}

const ACCEPTED_EXTENSIONS = '.pdf,.doc,.docx,.xls,.xlsx,.txt,.md,.png,.jpg,.jpeg,.webp'

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function applyRunDerivedWizardState(
  run: SuperAgentRun,
  restored: ReturnType<typeof restoreWizardStateFromRun>,
  setters: {
    setReviewModeCard: (value: ReviewModeCard) => void
    setProcessingMode: (value: string) => void
    setRequestedRoute: (value: SuperAgentRoute) => void
    setReviewObjective: (value: string) => void
  },
) {
  setters.setReviewModeCard(reviewModeSelectionToCard(reviewModeCardFromRun(run)))
  setters.setProcessingMode(processingModeFromRun(run))
  if (restored.classification) {
    setters.setRequestedRoute(
      routeFromClassification(restored.classification.recommended_route, restored.classification),
    )
  } else {
    setters.setRequestedRoute(run.requested_route || 'auto')
  }
  const objective = run.objective?.trim()
  if (objective && !objective.startsWith('等待上传材料')) {
    setters.setReviewObjective(objective)
  }
}

const REVIEW_PLUS_SLOT_ITEMS = [
  { key: 'review_rule', label: '审查规则/检查单' },
  { key: 'task_book', label: '研制任务书' },
  { key: 'subject_material', label: '被审材料' },
] as const

function requiresReviewPlusSlots(
  reviewModeCard: ReviewModeCard,
  requestedRoute: SuperAgentRoute,
): boolean {
  if (reviewModeCard === 'standard') return true
  return requestedRoute === 'review_plus'
}

function isReviewPlusSlotGateBlocked(
  classification: MaterialClassification | null,
  reviewModeCard: ReviewModeCard,
  requestedRoute: SuperAgentRoute,
): boolean {
  if (!requiresReviewPlusSlots(reviewModeCard, requestedRoute)) return false
  if (classification?.review_plus_ready === true) return false
  return Boolean(classification?.missing_slots?.length) || classification?.review_plus_ready === false
}

const POLL_INTERVAL_MS = 2500
const POLL_TIMEOUT_MS = 30 * 60 * 1000

function buildDraftRunInput(): CreateSuperAgentRunInput {
  return {
    name: `${SUPER_AGENT_TERMS.defaultRunName} ${new Date().toLocaleDateString('zh-CN')}`,
    objective: DRAFT_REVIEW_OBJECTIVE,
    processing_mode: 'OPTIMAL',
    input_mode: 'upload',
    source_review_id: '',
    requested_route: 'auto',
    review_mode: 'full',
    execute: false,
    materials: [],
  }
}

async function ensureClassifyPersistedOnRun(
  run: SuperAgentRun,
  classification: MaterialClassification | null,
  patch: Pick<SaveWizardCheckpointInput, 'processing_mode' | 'requested_route'>,
): Promise<{ run: SuperAgentRun; classification: MaterialClassification }> {
  if (hasPersistedClassificationOnRun(run)) {
    const restored = classificationFromRun(run)
    if (!restored?.doc_type) {
      throw new Error('识别结果未同步，请重试智能识别')
    }
    return { run, classification: restored }
  }

  if (classification?.doc_type) {
    if (!canPersistWizardCheckpoint(run)) {
      return { run, classification }
    }
    const updated = await saveWizardCheckpoint(run.run_id, {
      wizard_step: 2,
      classification,
      ...patch,
    })
    if (!updated) {
      throw new Error('保存识别结果失败，无法进入文档解析')
    }
    const restored = classificationFromRun(updated)
    if (!restored?.doc_type) {
      throw new Error('识别结果保存后仍未生效，请重试')
    }
    return { run: updated, classification: restored }
  }

  const classified = await classifyRunMaterials(run.run_id)
  if (!classified.classification?.doc_type) {
    throw new Error('材料智能识别未完成，请稍后重试')
  }
  return { run: classified.run, classification: classified.classification }
}

async function hydrateWizardFromRun(
  existing: SuperAgentRun,
  options?: { localFiles?: UploadedFileItem[] },
): Promise<{
  run: SuperAgentRun
  restored: ReturnType<typeof restoreWizardStateFromRun>
}> {
  let run = existing
  let restored = restoreWizardStateFromRun(run)

  if (needsServerClassify(run, restored)) {
    const result = await classifyRunMaterials(run.run_id)
    run = result.run
    restored = restoreWizardStateFromRun(run)
    restored.classification = result.classification
  }

  return { run, restored }
}

function applyRestoredWizardRefs(
  restored: ReturnType<typeof restoreWizardStateFromRun>,
  refs: {
    classifyStartedRef: MutableRefObject<boolean>
  },
) {
  if (restored.step >= 2 && restored.classification?.doc_type) {
    refs.classifyStartedRef.current = true
  }
}

async function resumePersistedRun(
  run: SuperAgentRun,
  onUpdate: (next: SuperAgentRun) => void,
): Promise<SuperAgentRun> {
  const resumed = await resumeSuperAgentRun(run.run_id)
  onUpdate(resumed)
  return waitForRunCompletion(run.run_id, onUpdate)
}

async function waitForRunCompletion(
  runId: string,
  onUpdate: (run: SuperAgentRun) => void,
): Promise<SuperAgentRun> {
  const started = Date.now()
  while (Date.now() - started < POLL_TIMEOUT_MS) {
    const current = await getSuperAgentRun(runId)
    onUpdate(current)
    if (current.status !== 'running') {
      return current
    }
    await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS))
  }
  throw new Error('审查执行超时，请稍后在控制台查看进度')
}

function StepIndicator({
  step,
  maxReachableStep,
  runStatus,
  busy,
  disabled,
  onStepClick,
}: {
  step: WizardStep
  maxReachableStep: WizardStep
  runStatus?: SuperAgentRun['status']
  busy?: boolean
  disabled?: boolean
  onStepClick?: (target: WizardStep) => void
}) {
  const labels = resolveWizardStepLabels({ step, runStatus, busy })
  return (
    <nav className="mb-6" aria-label="审查进度">
      <ol className="flex flex-wrap items-center justify-center gap-2 sm:gap-3">
        {labels.map((label, index) => {
          const n = (index + 1) as WizardStep
          const active = step === n
          const done = step > n
          const navInput = {
            target: n,
            currentStep: step,
            maxReachableStep,
            runStatus,
          }
          const { allowed } = canNavigateToWizardStep(navInput)
          const clickable = Boolean(onStepClick) && !disabled && allowed
          const hint = resolveWizardStepNavHint({ ...navInput, label })
          const circleClass = active
            ? 'bg-brand text-white'
            : done
              ? 'bg-positive/15 text-positive'
              : 'border border-border/20 bg-background text-muted'
          const labelClass = active
            ? 'font-medium text-primary'
            : done
              ? 'text-muted/70'
              : n <= maxReachableStep
                ? 'text-muted/70'
                : 'text-muted/45'

          return (
            <li key={label} className="flex items-center gap-2">
              {clickable ? (
                <button
                  type="button"
                  onClick={() => onStepClick?.(n)}
                  title={hint}
                  aria-label={hint}
                  aria-current={active ? 'step' : undefined}
                  className={`group flex cursor-pointer items-center gap-2 rounded-full outline-none transition hover:opacity-90 focus-visible:ring-2 focus-visible:ring-brand/40 ${labelClass}`}
                >
                  <span
                    className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-semibold transition group-hover:ring-2 group-hover:ring-brand/20 ${circleClass}`}
                  >
                    {done ? '✓' : n}
                  </span>
                  <span className="text-[11px]">{label}</span>
                </button>
              ) : (
                <div
                  className="flex items-center gap-2"
                  title={hint}
                  aria-label={hint}
                  aria-current={active ? 'step' : undefined}
                  aria-disabled={!allowed || disabled ? true : undefined}
                >
                  <span
                    className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-semibold ${
                      !allowed || disabled ? 'opacity-50' : ''
                    } ${circleClass}`}
                  >
                    {done ? '✓' : n}
                  </span>
                  <span className={`text-[11px] ${!allowed || disabled ? 'opacity-50' : ''} ${labelClass}`}>
                    {label}
                  </span>
                </div>
              )}
              {index < labels.length - 1 ? (
                <span className="hidden h-px w-6 bg-border/20 sm:block" aria-hidden />
              ) : null}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

export default function SuperAgentWizardPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const urlRunId = searchParams.get(RUN_ID_QUERY_KEY)?.trim() || ''
  const [step, setStep] = useState<WizardStep>(1)
  const [files, setFiles] = useState<UploadedFileItem[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [classification, setClassification] = useState<MaterialClassification | null>(null)
  const [classifyProgress, setClassifyProgress] = useState(0)
  const [classifyLines, setClassifyLines] = useState<string[]>([])
  const [parsePreview, setParsePreview] = useState<ParsePreviewResponse | null>(null)
  const [parseProgress, setParseProgress] = useState(0)
  const [parseLines, setParseLines] = useState<string[]>([])
  const [parseBusy, setParseBusy] = useState(false)
  const [reviewModeCard, setReviewModeCard] = useState<ReviewModeCard>('smart')
  const [reviewObjective, setReviewObjective] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [classifyDetailsOpen, setClassifyDetailsOpen] = useState(false)
  const [parseConfigOpen, setParseConfigOpen] = useState(false)
  const [requestedRoute, setRequestedRoute] = useState<SuperAgentRoute>('auto')
  const [processingMode, setProcessingMode] = useState('OPTIMAL')
  const [run, setRun] = useState<SuperAgentRun | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [initializingRun, setInitializingRun] = useState(true)
  const [loadFailedRunId, setLoadFailedRunId] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const classifyStartedRef = useRef(false)
  const parseInFlightRef = useRef(false)
  const parseAutoStartedRef = useRef(false)
  const parseForceReparseRef = useRef(false)
  const parseSessionRef = useRef(0)
  const runParsePreviewRef = useRef<() => Promise<void>>(async () => {})
  const materialsBaselineRef = useRef('')
  const materialsStaleRef = useRef(false)
  const parseStaleRef = useRef(false)

  const persistedMaterials = useMemo(
    () => (run?.materials?.length ? [...run.materials] : []) as SuperAgentMaterialInput[],
    [run?.materials],
  )
  const canEditPersistedMaterials = canPersistWizardCheckpoint(run)
  const hasWizardMaterialInputs = persistedMaterials.length > 0 || files.length > 0

  const syncMaterialsBaseline = useCallback(
    (persisted: SuperAgentMaterialInput[], local: UploadedFileItem[]) => {
      materialsBaselineRef.current = fingerprintWizardMaterials(persisted, local)
      materialsStaleRef.current = false
    },
    [],
  )

  const markMaterialsStale = useCallback(() => {
    const changed = materialsWizardInputsChanged(
      materialsBaselineRef.current,
      persistedMaterials,
      files,
    )
    if (changed) {
      materialsStaleRef.current = true
      parseStaleRef.current = true
    }
  }, [files, persistedMaterials])

  const syncRunIdToBrowser = useCallback(
    (runId: string) => {
      if (!runId) return
      replaceRunIdInUrl(runId)
      router.replace(buildSuperAgentRunUrl(runId), { scroll: false })
    },
    [router],
  )

  const persistWizardCheckpoint = useCallback(
    async (patch: SaveWizardCheckpointInput) => {
      if (!run?.run_id) return null
      if (!canPersistWizardCheckpoint(run)) {
        return run
      }
      try {
        const updated = await saveWizardCheckpoint(run.run_id, patch)
        setRun(updated)
        return updated
      } catch (err) {
        setError(err instanceof Error ? err.message : '保存审查进度失败')
        return null
      }
    },
    [run],
  )

  const createDraftRun = useCallback(async () => {
    const draft = await createSuperAgentRun(buildDraftRunInput())
    syncRunIdToBrowser(draft.run_id)
    setRun(draft)
    setStep(1)
    return draft
  }, [syncRunIdToBrowser])

  const ensureDraftRun = useCallback(async (): Promise<SuperAgentRun> => {
    if (run?.run_id) {
      syncRunIdToBrowser(run.run_id)
      return run
    }
    return createDraftRun()
  }, [createDraftRun, run, syncRunIdToBrowser])

  useEffect(() => {
    let cancelled = false

    const initializeRun = async () => {
      try {
        setInitializingRun(true)
        const runId = urlRunId
        if (runId) {
          try {
            const existing = await getSuperAgentRun(runId)
            if (cancelled) return
            const { run: hydrated, restored } = await hydrateWizardFromRun(existing)
            if (cancelled) return
            syncRunIdToBrowser(hydrated.run_id)
            setRun(hydrated)
            setStep(restored.step)
            applyRunDerivedWizardState(hydrated, restored, {
              setReviewModeCard,
              setProcessingMode,
              setRequestedRoute,
              setReviewObjective,
            })
            const restoredClassification = mergePostParseClassification(
              restored.classification,
              restored.parsePreview?.classification,
            )
            if (restoredClassification) {
              setClassification(restoredClassification)
            }
            if (restored.parsePreview) {
              setParsePreview(restored.parsePreview)
              setParseProgress(100)
              parseAutoStartedRef.current = true
            }
            applyRestoredWizardRefs(restored, { classifyStartedRef })
            syncMaterialsBaseline(
              (hydrated.materials || []) as SuperAgentMaterialInput[],
              [],
            )
            parseStaleRef.current = !restored.parsePreview
            setError('')
            return
          } catch (err) {
            if (!cancelled) {
              const message = err instanceof Error ? err.message : '加载审查任务失败'
              setError(message)
              setRun(buildFallbackSuperAgentRun(runId, message))
              setStep(4)
              setLoadFailedRunId(runId)
            }
            return
          }
        }

        clearRunIdFromUrl()
        setStep(1)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '初始化审查任务失败')
        }
      } finally {
        if (!cancelled) setInitializingRun(false)
      }
    }

    void initializeRun()
    return () => {
      cancelled = true
    }
    // 仅随 URL runid 初始化，避免 router 引用变化重复 setStep(restored.step)
  }, [urlRunId])

  useEffect(() => {
    if (!run?.run_id || run.status !== 'running') return
    let cancelled = false

    const poll = async () => {
      try {
        const current = await getSuperAgentRun(run.run_id)
        if (cancelled) return
        setRun(current)
        if (current.status !== 'running') setBusy(false)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '刷新审查进度失败')
      }
    }

    const timer = window.setInterval(poll, POLL_INTERVAL_MS)
    void poll()
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [run?.run_id, run?.status])

  const addFiles = useCallback((incoming: FileList | File[]) => {
    const list = Array.from(incoming)
    if (!list.length) return
    setFiles((current) => {
      const existing = new Set(current.map((item) => `${item.file.name}-${item.file.size}`))
      const next = [...current]
      for (const file of list) {
        const key = `${file.name}-${file.size}`
        if (existing.has(key)) continue
        next.push({ id: `${key}-${Date.now()}`, file })
        existing.add(key)
      }
      return next
    })
    queueMicrotask(() => markMaterialsStale())
  }, [markMaterialsStale])

  const removeFile = useCallback((id: string) => {
    setFiles((current) => current.filter((item) => item.id !== id))
    queueMicrotask(() => markMaterialsStale())
  }, [markMaterialsStale])

  const removePersistedMaterial = useCallback(
    async (name: string) => {
      if (!run?.run_id || !canEditPersistedMaterials) return
      const next = persistedMaterials.filter((item) => item.name !== name)
      try {
        setBusy(true)
        const updated = await saveWizardCheckpoint(run.run_id, {
          wizard_step: 1,
          materials: next,
        })
        if (!updated) return
        setRun(updated)
        setClassification(null)
        setParsePreview(null)
        classifyStartedRef.current = false
        parseAutoStartedRef.current = false
        materialsStaleRef.current = true
        parseStaleRef.current = true
      } catch (err) {
        setError(err instanceof Error ? err.message : '移除材料失败')
      } finally {
        setBusy(false)
      }
    },
    [canEditPersistedMaterials, files, persistedMaterials, run?.run_id, syncMaterialsBaseline],
  )

  const replaceAllMaterials = useCallback(async () => {
    setFiles([])
    materialsStaleRef.current = true
    parseStaleRef.current = true
    if (!run?.run_id || !canEditPersistedMaterials) return
    try {
      setBusy(true)
      const updated = await saveWizardCheckpoint(run.run_id, { wizard_step: 1, materials: [] })
      if (updated) {
        setRun(updated)
        setClassification(null)
        setParsePreview(null)
        classifyStartedRef.current = false
        parseAutoStartedRef.current = false
      }
      syncMaterialsBaseline([], [])
    } catch (err) {
      setError(err instanceof Error ? err.message : '清空材料失败')
    } finally {
      setBusy(false)
    }
  }, [canEditPersistedMaterials, run?.run_id, syncMaterialsBaseline])

  const recommendedScene = useMemo(
    () => SCENE_LABELS[classification?.recommended_route || 'auto'] || '智能综合审查',
    [classification],
  )

  const effectiveRoute = useMemo(
    () => resolveEffectiveRoute(
      reviewModeCard,
      requestedRoute,
      classification,
      hasRunParseArtifact(run, parsePreview),
    ),
    [classification, parsePreview, requestedRoute, reviewModeCard, run],
  )

  const showReviewPlusFileGroupCopy = useMemo(
    () => effectiveRoute === 'review_plus' || (
      classification?.review_plus_ready === true
      && effectiveRoute !== 'smart'
      && classification?.recommended_route === 'review_plus'
    ),
    [classification?.recommended_route, classification?.review_plus_ready, effectiveRoute],
  )

  const reviewPlusSlotBlocked = useMemo(
    () => isReviewPlusSlotGateBlocked(classification, reviewModeCard, requestedRoute),
    [classification, requestedRoute, reviewModeCard],
  )

  const parsePlan = classification?.parse_plan
  const reviewPlan = classification?.review_plan

  const showSmartObjectiveInput = useMemo(() => {
    if (!classification?.doc_type) return false
    return (
      effectiveRoute === 'smart'
      || classification.recommended_route === 'smart'
      || Boolean(reviewPlan?.downgrade_reasons?.length)
      || (reviewPlusSlotBlocked && reviewModeCard === 'smart')
    )
  }, [classification, effectiveRoute, reviewPlan, reviewPlusSlotBlocked, reviewModeCard])

  const confirmReviewCtaLabel = useMemo(() => {
    if (parseBusy) return '解析进行中…'
    if (!parsePreview) return '等待解析完成'
    if (canRerunReviewOnRun(run)) {
      const route = resolveReviewStartRoute(
        reviewModeCard,
        requestedRoute,
        classification,
        true,
      )
      const routeLabel = ROUTE_LABELS[route] || route
      return `重新开始审查（${routeLabel}）`
    }
    const route = resolveReviewStartRoute(
      reviewModeCard,
      requestedRoute,
      classification,
      true,
    )
    const routeLabel = ROUTE_LABELS[route] || route
    return `确认审查链路并开始审查（${routeLabel}）`
  }, [classification, parseBusy, parsePreview, requestedRoute, reviewModeCard, run])

  const runClassify = useCallback(async () => {
    if (!files.length && !run?.materials?.length) return
    setError('')
    setClassifyProgress(8)
    const materialCount = files.length + (run?.materials?.length || 0)
    setClassifyLines([`正在读取 ${materialCount} 份材料…`])

    const tick = window.setInterval(() => {
      setClassifyProgress((p) => (p >= 92 ? p : p + Math.random() * 8))
    }, 400)

    try {
      const names = files.map((f) => f.file.name)
      setClassifyLines((lines) => [...lines, ...names.map((name) => `✅ 已识别：${name}`)])
      setClassifyProgress(55)

      let result: MaterialClassification
      let materialsForBaseline: SuperAgentMaterialInput[] = (run?.materials || []) as SuperAgentMaterialInput[]
      if (run?.run_id) {
        if (files.length && canPersistWizardCheckpoint(run)) {
          const uploaded = await filesToMaterials(files.map((item) => item.file))
          const mergedMaterials = [...((run.materials || []) as SuperAgentMaterialInput[]), ...uploaded]
          await saveWizardCheckpoint(run.run_id, {
            wizard_step: 2,
            materials: mergedMaterials,
            ...(isPersistableReviewObjective(reviewObjective)
              ? { objective: reviewObjective.trim() }
              : {}),
            processing_mode: processingMode,
          }).then((updated) => {
            if (updated) {
              setRun(updated)
              materialsForBaseline = (updated.materials || []) as SuperAgentMaterialInput[]
              setClassification(null)
              setParsePreview(null)
              parseStaleRef.current = true
            }
          })
          setFiles([])
        }
        try {
          const classified = await classifyRunMaterials(run.run_id)
          result = classified.classification
          setRun(classified.run)
          materialsForBaseline = (classified.run.materials || []) as SuperAgentMaterialInput[]
        } catch {
          result = fallbackClassifyFromFileNames(files.map((f) => f.file))
          setClassifyLines((lines) => [...lines, '🔄 正在匹配审查场景（本地推断）…'])
        }
      } else {
        try {
          result = await classifyMaterials(files.map((f) => f.file))
        } catch {
          result = fallbackClassifyFromFileNames(files.map((f) => f.file))
          setClassifyLines((lines) => [...lines, '🔄 正在匹配审查场景（本地推断）…'])
        }
      }

      setClassification(result)
      setRequestedRoute(routeFromClassification(result.recommended_route, result))
      if (result.parse_plan?.default_processing_mode) {
        setProcessingMode(result.parse_plan.default_processing_mode)
      }
      const roleLines =
        result.material_roles?.map(
          (item) =>
            `✅ ${item.file_name}：${MATERIAL_ROLE_LABELS[item.role] || item.role}${
              item.recommended_parsing_tier
                ? ` · 推荐 ${PARSING_TIER_LABELS[item.recommended_parsing_tier] || item.recommended_parsing_tier}`
                : ''
            }`,
        ) || []
      setClassifyLines((lines) => [
        ...lines,
        `✅ 文档类型：${result.doc_type}`,
        `✅ 专业领域：${result.domain}`,
        '🔄 正在匹配审查场景…',
        `✅ 推荐场景：${SCENE_LABELS[result.recommended_route] || result.recommended_route}`,
        ...roleLines,
      ])
      setClassifyProgress(100)
      materialsStaleRef.current = false
      parseStaleRef.current = true
      if (run?.run_id && canPersistWizardCheckpoint(run)) {
        await saveWizardCheckpoint(run.run_id, {
          wizard_step: 2,
          classification: result,
          requested_route: routeFromClassification(result.recommended_route, result),
          processing_mode: result.parse_plan?.default_processing_mode || processingMode,
          review_mode_selection: reviewModeCardToSelection(reviewModeCard),
        }).then((updated) => {
          if (updated) setRun(updated)
        })
      }
      syncMaterialsBaseline(materialsForBaseline, [])
    } catch (err) {
      setError(err instanceof Error ? err.message : '材料识别失败')
      classifyStartedRef.current = false
    } finally {
      window.clearInterval(tick)
    }
  }, [files, processingMode, reviewModeCard, run?.materials, run?.run_id])

  const handleReviewModeCardChange = useCallback(
    (card: ReviewModeCardId) => {
      const normalizedCard: ReviewModeCard = card === 'specialized' ? 'special' : card
      setReviewModeCard(normalizedCard)
      const selection = reviewModeCardToSelection(normalizedCard)
      const route = routeForReviewModeCardChange(normalizedCard)
      setRequestedRoute(route)
      if (run?.run_id) {
        void persistWizardCheckpoint({
          review_mode_selection: selection,
          requested_route: route,
        })
      }
    },
    [persistWizardCheckpoint, run?.run_id],
  )

  const handleAdaptiveRouterOverride = useCallback(
    (patch: {
      domain_id?: string
      route?: string
      requested_route: SuperAgentRoute
      classification: MaterialClassification
    }) => {
      setClassification(patch.classification)
      setRequestedRoute(patch.requested_route)
      if (run?.run_id) {
        void persistWizardCheckpoint({
          classification: patch.classification,
          requested_route: patch.requested_route,
        })
      }
    },
    [persistWizardCheckpoint, run?.run_id],
  )

  const resetParsePreviewState = useCallback((options?: { bumpSession?: boolean }) => {
    if (options?.bumpSession !== false) {
      parseSessionRef.current += 1
    }
    parseInFlightRef.current = false
    setParsePreview(null)
    setParseProgress(0)
    setParseLines([])
    setParseBusy(false)
  }, [])

  const handleProcessingModeChange = useCallback(
    (nextMode: string) => {
      if (step === 3 && nextMode !== processingMode) {
        parseAutoStartedRef.current = false
        resetParsePreviewState()
      }
      setProcessingMode(nextMode)
    },
    [processingMode, resetParsePreviewState, step],
  )

  const runParsePreview = useCallback(async () => {
    if (parseInFlightRef.current) return
    if (!classification?.doc_type) {
      setError('请先完成材料智能识别')
      setStep(2)
      return
    }
    if (!files.length && !run?.materials?.length) return

    const session = parseSessionRef.current
    parseInFlightRef.current = true
    setError('')
    setParseBusy(true)
    setParseProgress(8)
    setParseLines([`正在解析 ${files.length || run?.materials?.length || 0} 份材料…`])

    const tick = window.setInterval(() => {
      if (session !== parseSessionRef.current) return
      setParseProgress((p) => (p >= 92 ? p : p + Math.random() * 6))
    }, 450)

    try {
      if (parseStaleRef.current) {
        parseForceReparseRef.current = true
      }

      let result: ParsePreviewResponse
      if (run?.run_id) {
        const checkpointRoute = resolveCheckpointRoute(reviewModeCard, requestedRoute)
        const ensured = await ensureClassifyPersistedOnRun(run, classification, {
          processing_mode: processingMode,
          requested_route: checkpointRoute,
        })
        if (session !== parseSessionRef.current) return
        setRun(ensured.run)
        setClassification(ensured.classification)
        if (canPersistWizardCheckpoint(ensured.run)) {
          const checkpoint = await saveWizardCheckpoint(ensured.run.run_id, {
            processing_mode: processingMode,
            requested_route: checkpointRoute,
            wizard_step: 3,
            classification: ensured.classification,
          })
          if (session !== parseSessionRef.current) return
          if (!checkpoint) {
            throw new Error('保存审查方案失败，无法开始解析预览')
          }
          setRun(checkpoint)
        }
        const parsed = await parsePreviewFromRun(ensured.run.run_id, {
          forceReparse: parseForceReparseRef.current,
          onProgress: (job) => {
            if (session !== parseSessionRef.current) return
            if (typeof job.progress === 'number' && job.progress > 0) {
              setParseProgress((current) => Math.max(current, job.progress))
            }
            const message = job.message?.trim()
            if (!message) return
            setParseLines((lines) => {
              if (lines.length && lines[lines.length - 1] === message) return lines
              return [...lines, message]
            })
          },
        })
        parseForceReparseRef.current = false
        if (session !== parseSessionRef.current) return
        result = parsed.preview
        setRun(parsed.run)
      } else if (files.length) {
        result = await parseMaterialsPreview(
          files.map((item) => item.file),
          processingMode,
          resolveReviewObjective(reviewObjective, run?.objective, classification.reason),
          classification,
        )
        if (session !== parseSessionRef.current) return
      } else {
        return
      }
      setParsePreview(result)
      const merged = mergePostParseClassification(classification, result.classification)
      if (merged) {
        setClassification(merged)
      }
      if (run?.run_id && canPersistWizardCheckpoint(run)) {
        await saveWizardCheckpoint(run.run_id, {
          wizard_step: 3,
          processing_mode: processingMode,
          requested_route: resolveCheckpointRoute(reviewModeCard, requestedRoute),
        }).then((updated) => {
          if (session !== parseSessionRef.current) return
          if (updated) setRun(updated)
        })
      }
      setParseLines((lines) => [
        ...lines,
        ...result.materials.map(
          (item) =>
            `✅ ${item.file_name}：${MATERIAL_ROLE_LABELS[item.role] || item.role} · ${PARSING_TIER_LABELS[item.parsing_tier] || item.parsing_tier}（正式 ${PROCESSING_MODE_LABELS[item.processing_mode] || item.processing_mode}）`,
        ),
        `✅ 解析完成：${result.summary.parsed_ok}/${result.summary.material_count} 份成功`,
        ...(result.structure_summary?.structure_ready
          ? [
              `✅ 结构化就绪：${result.structure_summary.section_count} 个章节 · ${result.structure_summary.evidence_count} 条证据`,
            ]
          : []),
      ])
      setParseProgress(100)
      parseStaleRef.current = false
      syncMaterialsBaseline(
        (run?.materials || []) as SuperAgentMaterialInput[],
        files,
      )
      setStep(3)
    } catch (err) {
      if (session !== parseSessionRef.current) return
      setError(err instanceof Error ? err.message : '材料解析预览失败')
      setParseProgress(0)
      setParseLines([])
    } finally {
      window.clearInterval(tick)
      if (session !== parseSessionRef.current) return
      parseInFlightRef.current = false
      setParseBusy(false)
    }
  }, [
    classification,
    files,
    processingMode,
    requestedRoute,
    reviewModeCard,
    run?.materials?.length,
    run?.run_id,
    syncMaterialsBaseline,
  ])

  runParsePreviewRef.current = runParsePreview

  useEffect(() => {
    if (step !== 3) {
      parseAutoStartedRef.current = false
      return
    }
    if (parseStaleRef.current && parsePreview) {
      parseAutoStartedRef.current = false
      resetParsePreviewState()
      parseForceReparseRef.current = true
    }
    if (
      !shouldAutoStartParsePreview({
        step,
        hasClassification: Boolean(classification?.doc_type),
        fileCount: files.length,
        persistedMaterialCount: run?.materials?.length || 0,
        hasParsePreview: Boolean(parsePreview) && !parseStaleRef.current,
        parseInFlight: parseInFlightRef.current,
        autoStartConsumed: parseAutoStartedRef.current,
      })
    ) {
      return
    }
    parseAutoStartedRef.current = true
    void runParsePreviewRef.current()
  }, [step, classification?.doc_type, files.length, run?.materials?.length, parsePreview, processingMode])

  useEffect(() => {
    const materialCount = files.length + (run?.materials?.length || 0)
    if (step !== 2 || materialCount === 0) return
    if (classification?.doc_type && !materialsStaleRef.current) return
    if (classifyStartedRef.current && !materialsStaleRef.current) return
    if (materialsStaleRef.current) {
      classifyStartedRef.current = false
      setClassification(null)
    }
    classifyStartedRef.current = true
    void runClassify()
  }, [step, files.length, run?.materials?.length, classification?.doc_type, runClassify])

  const handleReloadRun = useCallback(async () => {
    const runId = run?.run_id || urlRunId
    if (!runId) return
    try {
      setBusy(true)
      setError('')
      const existing = await getSuperAgentRun(runId)
      const { run: hydrated, restored } = await hydrateWizardFromRun(existing, { localFiles: files })
      syncRunIdToBrowser(hydrated.run_id)
      setRun(hydrated)
      setStep(restored.step)
      setLoadFailedRunId('')
      applyRunDerivedWizardState(hydrated, restored, {
        setReviewModeCard,
        setProcessingMode,
        setRequestedRoute,
        setReviewObjective,
      })
      const restoredClassification = mergePostParseClassification(
        restored.classification,
        restored.parsePreview?.classification,
      )
      if (restoredClassification) {
        setClassification(restoredClassification)
      }
      if (restored.parsePreview) {
        setParsePreview(restored.parsePreview)
        setParseProgress(100)
        parseAutoStartedRef.current = true
      }
      applyRestoredWizardRefs(restored, { classifyStartedRef })
      syncMaterialsBaseline(
        (hydrated.materials || []) as SuperAgentMaterialInput[],
        files,
      )
      parseStaleRef.current = !restored.parsePreview
    } catch (err) {
      const message = err instanceof Error ? err.message : '刷新审查任务失败'
      setError(message)
      setRun(buildFallbackSuperAgentRun(runId, message))
      setStep(4)
      setLoadFailedRunId(runId)
    } finally {
      setBusy(false)
    }
  }, [files, run?.run_id, syncMaterialsBaseline, syncRunIdToBrowser, urlRunId])

  const handleResumeRun = useCallback(async () => {
    if (!run?.run_id) return
    try {
      setBusy(true)
      setError('')
      const finalRun = await resumePersistedRun(run, setRun)
      setRun(finalRun)
      if (finalRun.status === 'failed') {
        setError(finalRun.error || '审查续跑失败')
      } else if (finalRun.status === 'completed' || finalRun.status === 'limited') {
        setStep(5)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '审查续跑失败')
    } finally {
      setBusy(false)
    }
  }, [run])

  const handleStartReview = useCallback(async () => {
    const hasPersistedMaterials = Boolean(run?.materials?.length || run?.source_review_id)
    if (!files.length && !hasPersistedMaterials) return
    try {
      setBusy(true)
      setError('')
      const hasParseArtifact = hasRunParseArtifact(run, parsePreview)
      const route = resolveReviewStartRoute(
        reviewModeCard,
        requestedRoute,
        classification,
        hasParseArtifact,
      )

      if (run?.run_id && (hasParseArtifact || canRerunReviewOnRun(run))) {
        if (!hasParseArtifact) {
          throw new Error('请先完成文档解析（parse artifact 不完整或缺失）')
        }
        const objective = resolveReviewObjective(
          reviewObjective,
          run?.objective,
          classification?.reason,
        )
        setStep(4)
        const started = await reviewSuperAgentRun(run.run_id, {
          requested_route: route,
          review_mode: 'full',
          objective,
          skip_reparse: true,
          force_rerun: canRerunReviewOnRun(run),
        })
        syncRunIdToBrowser(started.run_id)
        setRun(started)
        const finalRun = await waitForRunCompletion(started.run_id, setRun)
        if (finalRun.status === 'failed') {
          throw new Error(finalRun.error || '审查执行失败')
        }
        setRun(finalRun)
        setStep(5)
        return
      }

      const materials = files.length
        ? await filesToMaterials(files.map((item) => item.file))
        : run?.materials || []
      const payload: CreateSuperAgentRunInput = {
        name: `智能审查 ${new Date().toLocaleDateString('zh-CN')}`,
        objective: resolveReviewObjective(
          reviewObjective,
          run?.objective,
          classification?.reason,
        ),
        processing_mode: processingMode,
        input_mode: 'upload',
        source_review_id: run?.source_review_id || '',
        requested_route: route,
        review_mode: 'full',
        execute: true,
        materials,
        classification: classification ?? undefined,
      }
      const started = run?.run_id
        ? await updateSuperAgentRun(run.run_id, payload)
        : await createSuperAgentRun(payload)
      syncRunIdToBrowser(started.run_id)
      setRun(started)
      setStep(4)
      const finalRun = await waitForRunCompletion(started.run_id, setRun)
      if (finalRun.status === 'failed') {
        throw new Error(finalRun.error || '审查执行失败')
      }
      setRun(finalRun)
      setStep(5)
    } catch (err) {
      setError(err instanceof Error ? err.message : '审查执行失败')
    } finally {
      setBusy(false)
    }
  }, [classification, files, parsePreview, processingMode, requestedRoute, reviewModeCard, reviewObjective, run?.materials, run?.objective, run?.parse_preview, run?.run_id, run?.source_review_id, syncRunIdToBrowser])

  const wizardBreadcrumb = useMemo(
    () => formatWizardStepBreadcrumb({ step, runStatus: run?.status, busy }),
    [step, run?.status, busy],
  )
  const showParseLoading = useMemo(
    () => shouldShowParseLoadingUi(step, parsePreview, parseBusy, Boolean(error)),
    [step, parsePreview, parseBusy, error],
  )
  const showParseStartCta = useMemo(
    () => shouldShowParseStartCta(step, parsePreview, parseBusy, Boolean(error)),
    [step, parsePreview, parseBusy, error],
  )
  const parseAdmissionSummary = useMemo(
    () => buildParseAdmissionSummary(parsePreview, { loading: showParseLoading, parseBusy }),
    [parsePreview, showParseLoading, parseBusy],
  )

  const postParsePlanClassification = useMemo(
    () => mergePostParseClassification(classification, parsePreview?.classification),
    [classification, parsePreview?.classification],
  )

  const navigateToWizardStep = useCallback(
    async (
      target: WizardStep,
      options?: {
        restoreParsePreview?: boolean
        persistCheckpoint?: boolean
      },
    ) => {
      setError('')
      setBusy(false)

      if (target <= 2) {
        parseAutoStartedRef.current = false
        resetParsePreviewState()
      }

      if (target === 1) {
        classifyStartedRef.current = false
        setClassifyProgress(0)
        setClassifyLines([])
        if (!materialsStaleRef.current) {
          setClassification(null)
        }
      }

      if (target >= 2) {
        if (!materialsStaleRef.current) {
          const restoredClassification = classification ?? (run ? classificationFromRun(run) : null)
          if (restoredClassification) {
            setClassification(restoredClassification)
            classifyStartedRef.current = true
          }
        } else {
          setClassification(null)
          classifyStartedRef.current = false
        }
      }

      if (target === 3 && options?.restoreParsePreview !== false) {
        if (parseStaleRef.current) {
          parseForceReparseRef.current = true
          parseAutoStartedRef.current = false
        } else {
          const preview = parsePreview ?? (run ? parsePreviewFromPersistedRun(run) : null)
          if (preview) {
            setParsePreview(preview)
            setParseProgress(100)
            parseAutoStartedRef.current = true
            const baseClassification =
              classification ?? (run ? classificationFromRun(run) : null)
            const merged = mergePostParseClassification(baseClassification, preview.classification)
            if (merged) {
              setClassification(merged)
            }
          }
        }
      }

      const shouldPersist =
        options?.persistCheckpoint !== false
        && run?.status === 'draft'
        && run.run_id
        && target < step
      if (shouldPersist) {
        await persistWizardCheckpoint({ wizard_step: target })
      }

      setStep(target)
    },
    [classification, parsePreview, persistWizardCheckpoint, resetParsePreviewState, run, step],
  )

  const maxReachableStep = useMemo(
    () => resolveMaxReachableWizardStep(step, run),
    [step, run],
  )

  const handleWizardStepClick = useCallback(
    (target: WizardStep) => {
      const nav = canNavigateToWizardStep({
        target,
        currentStep: step,
        maxReachableStep,
        runStatus: run?.status,
      })
      if (!nav.allowed) {
        if (nav.reason && nav.reason !== '当前步骤') {
          setError(nav.reason)
        }
        return
      }

      void navigateToWizardStep(target, {
        restoreParsePreview: target === 3 ? true : undefined,
        persistCheckpoint: run?.status === 'draft' ? undefined : false,
      })
    },
    [maxReachableStep, navigateToWizardStep, run?.status, step],
  )

  const resetWizard = useCallback(() => {
    setStep(1)
    setFiles([])
    setClassification(null)
    setClassifyProgress(0)
    setClassifyLines([])
    setParsePreview(null)
    setParseProgress(0)
    setParseLines([])
    setParseBusy(false)
    setReviewModeCard('smart')
    setAdvancedOpen(false)
    setRequestedRoute('auto')
    setProcessingMode('OPTIMAL')
    setRun(null)
    setError('')
    setLoadFailedRunId('')
    classifyStartedRef.current = false
    parseInFlightRef.current = false
    parseAutoStartedRef.current = false
    parseSessionRef.current += 1
    materialsBaselineRef.current = ''
    materialsStaleRef.current = false
    parseStaleRef.current = false
    clearRunIdFromUrl()
    router.replace('/super-agent', { scroll: false })
  }, [router])

  const handleExport = useCallback(() => {
    if (!run) return
    const markdown = buildSuperAgentExportMarkdown(run)
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `审查报告-${run?.run_id || 'draft'}.md`
    anchor.click()
    URL.revokeObjectURL(url)
  }, [run])

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-background">
      <div
        className={`mx-auto flex w-full flex-1 flex-col px-4 py-6 sm:px-6 sm:py-8 ${
          step >= 4 ? 'max-w-7xl' : step === 3 ? 'max-w-[90rem]' : 'max-w-3xl'
        }`}
      >
        <div className="mb-2 text-center">
          <div className="inline-flex items-center gap-2">
            <Rocket className="h-5 w-5 text-primaryAccent" aria-hidden />
            <h1 className="text-lg font-semibold text-primary sm:text-xl">{SUPER_AGENT_TERMS.wizardTitle}</h1>
          </div>
          <p className="mt-1 text-[11px] text-muted/70">{wizardBreadcrumb}</p>
          <p className="mt-2 text-[10px] text-muted/60">
            {initializingRun
              ? urlRunId
                ? '正在加载审查任务…'
                : '准备就绪'
              : run?.run_id
                ? `Run ID：${run.run_id}`
                : 'Run ID：未创建'}
          </p>
        </div>

        <StepIndicator
          step={step}
          maxReachableStep={maxReachableStep}
          runStatus={run?.status}
          busy={busy}
          disabled={initializingRun}
          onStepClick={handleWizardStepClick}
        />

        {error ? (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/20 bg-destructive/10 px-4 py-3 text-[11px] text-destructive">
            <span className="min-w-0 flex-1">{error}</span>
            {loadFailedRunId || ((step === 4 || step === 5) && run?.run_id) ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleReloadRun()}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-destructive/25 bg-background px-2.5 py-1 text-[10px] font-medium text-destructive disabled:opacity-50"
              >
                <RefreshCw className="h-3 w-3" aria-hidden />
                重新加载
              </button>
            ) : null}
          </div>
        ) : null}

        {step === 1 ? (
          <section className="flex flex-1 flex-col rounded-xl border border-border/15 bg-surface p-5 shadow-soft sm:p-6">
            <div
              role="button"
              tabIndex={0}
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragOver(false)
                addFiles(e.dataTransfer.files)
              }}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click()
              }}
              className={`flex min-h-[220px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-10 text-center transition ${
                dragOver
                  ? 'border-primaryAccent/50 bg-primaryAccent/5'
                  : 'border-border/25 bg-background/50 hover:border-primaryAccent/35'
              }`}
            >
              <Paperclip className="h-8 w-8 text-muted/50" aria-hidden />
              <p className="mt-3 text-sm font-medium text-primary">拖拽文件到这里，或点击上传</p>
              <p className="mt-2 text-[11px] text-muted/70">支持 PDF、Word、Excel、TXT、图片</p>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ACCEPTED_EXTENSIONS}
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) addFiles(e.target.files)
                  e.target.value = ''
                }}
              />
            </div>

            {persistedMaterials.length ? (
              <div className="mt-5">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div className="text-[11px] font-medium text-muted">已保存材料（服务器）</div>
                  {canEditPersistedMaterials ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={(e) => {
                        e.stopPropagation()
                        void replaceAllMaterials()
                      }}
                      className="text-[10px] font-medium text-muted hover:text-primary disabled:opacity-50"
                    >
                      替换全部
                    </button>
                  ) : null}
                </div>
                <ul className="space-y-2">
                  {persistedMaterials.map((item) => (
                    <li
                      key={`${item.name}-${item.file_id || item.upload_id || item.file_path}`}
                      className="flex items-center gap-2 rounded-lg border border-border/10 bg-background/70 px-3 py-2"
                    >
                      <FileText className="h-4 w-4 shrink-0 text-primaryAccent" aria-hidden />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12px] text-primary">{item.name}</div>
                        <div className="text-[10px] text-muted/60">
                          {item.file_size ? formatFileSize(item.file_size) : '已上传'}
                          {item.role
                            ? ` · ${MATERIAL_ROLE_LABELS[item.role] || item.role}`
                            : ''}
                        </div>
                      </div>
                      {canEditPersistedMaterials ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            void removePersistedMaterial(item.name)
                          }}
                          className="rounded-md p-1 text-muted hover:bg-border/10 hover:text-primary"
                          aria-label={`移除 ${item.name}`}
                        >
                          <X className="h-4 w-4" aria-hidden />
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
                {!canEditPersistedMaterials ? (
                  <p className="mt-2 text-[10px] text-muted/60">
                    当前任务非草稿状态，已保存材料仅可查看；如需更换材料请新建审查任务。
                  </p>
                ) : null}
              </div>
            ) : null}

            {files.length ? (
              <div className="mt-5">
                <div className="mb-2 text-[11px] font-medium text-muted">待上传文件：</div>
                <ul className="space-y-2">
                  {files.map((item) => (
                    <li
                      key={item.id}
                      className="flex items-center gap-2 rounded-lg border border-border/10 bg-background/70 px-3 py-2"
                    >
                      <FileText className="h-4 w-4 shrink-0 text-primaryAccent" aria-hidden />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12px] text-primary">{item.file.name}</div>
                        <div className="text-[10px] text-muted/60">{formatFileSize(item.file.size)}</div>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          removeFile(item.id)
                        }}
                        className="rounded-md p-1 text-muted hover:bg-border/10 hover:text-primary"
                        aria-label={`移除 ${item.file.name}`}
                      >
                        <X className="h-4 w-4" aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                disabled={!hasWizardMaterialInputs || busy}
                onClick={() => {
                  void (async () => {
                    try {
                      setBusy(true)
                      setError('')
                      const activeRun = await ensureDraftRun()
                      const uploaded = files.length
                        ? await filesToMaterials(files.map((item) => item.file))
                        : []
                      const mergedMaterials = [...persistedMaterials, ...uploaded]
                      const materialsChanged = materialsWizardInputsChanged(
                        materialsBaselineRef.current,
                        mergedMaterials,
                        [],
                      )
                      if (mergedMaterials.length) {
                        const updated = await saveWizardCheckpoint(activeRun.run_id, {
                          wizard_step: 2,
                          materials: mergedMaterials,
                          ...(isPersistableReviewObjective(reviewObjective)
                            ? { objective: reviewObjective.trim() }
                            : {}),
                          processing_mode: processingMode,
                        })
                        if (!updated) return
                        setRun(updated)
                        setFiles([])
                        if (materialsChanged) {
                          setClassification(null)
                          setParsePreview(null)
                          materialsStaleRef.current = true
                          parseStaleRef.current = true
                        }
                      }
                      classifyStartedRef.current = false
                      setStep(2)
                    } catch (err) {
                      setError(err instanceof Error ? err.message : '保存材料失败')
                    } finally {
                      setBusy(false)
                    }
                  })()
                }}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-brand px-5 text-[12px] font-medium text-white disabled:opacity-50"
              >
                下一步
                <ChevronRight className="h-4 w-4" aria-hidden />
              </button>
            </div>
          </section>
        ) : null}

        {step === 2 ? (
          <section className="flex flex-1 flex-col rounded-xl border border-border/15 bg-surface p-5 shadow-soft sm:p-6">
            <div className="mb-4 flex items-center gap-2">
              <Brain className={`h-5 w-5 text-primaryAccent ${classification?.doc_type ? '' : 'animate-pulse'}`} aria-hidden />
              <div>
                <h2 className="text-base font-semibold text-primary">识别与路由</h2>
                <p className="text-[11px] text-muted">
                  {classification?.doc_type
                    ? '识别与初始建议已就绪，请确认材料角色、槽位完整性与解析方案后继续。'
                    : '正在分析材料元数据与内容摘要，识别文档类型、材料角色并生成解析前初始建议（不进行完整解析）。'}
                </p>
              </div>
            </div>

            {!classification?.doc_type ? (
              <div className="flex flex-1 flex-col items-center justify-center py-6">
                <div className="w-full max-w-md">
                  <div className="mb-2 flex justify-between text-[11px] text-muted">
                    <span>识别进度</span>
                    <span className="tabular-nums">{Math.round(classifyProgress)}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-border/15">
                    <div
                      className="h-full rounded-full bg-primaryAccent transition-all duration-300"
                      style={{ width: `${Math.min(100, classifyProgress)}%` }}
                    />
                  </div>
                </div>
                <ul className="mt-6 w-full max-w-md space-y-2 text-[12px] text-muted">
                  {classifyLines.map((line) => (
                    <li key={line} className="flex items-start gap-2">
                      <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primaryAccent" aria-hidden />
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <>
                <ClassifyBusinessSummary
                  classification={classification}
                  effectiveRoute={effectiveRoute}
                  recommendedScene={recommendedScene}
                  reviewPlusSlotBlocked={reviewPlusSlotBlocked}
                  missingSlots={classification.missing_slots}
                  canProceed={!reviewPlusSlotBlocked && Boolean(classification.doc_type)}
                />

                <div className="mt-5">
                  <ReviewModeCardPicker
                    reviewModeCard={reviewModeCard}
                    onChange={handleReviewModeCardChange}
                    recommendedCard={classification ? recommendedReviewModeCard(classification) : undefined}
                  />
                </div>

                {showSmartObjectiveInput ? (
                  <div className="mt-4 rounded-xl border border-border/10 bg-background/70 p-4 text-[12px]">
                    <label className="block">
                      <span className="text-[11px] font-medium text-muted">审查目标 / 要点（智能审查）</span>
                      <textarea
                        value={reviewObjective}
                        onChange={(e) => setReviewObjective(e.target.value)}
                        onBlur={() => {
                          if (!run?.run_id || !reviewObjective.trim()) return
                          void persistWizardCheckpoint({ objective: reviewObjective.trim() })
                        }}
                        rows={3}
                        placeholder="例如：重点检查导航方案与任务书指标一致性、接口定义是否完整…"
                        className="mt-2 w-full rounded-lg border border-border/25 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
                      />
                    </label>
                    <p className="mt-2 text-[10px] text-muted">
                      槽位不全或走智能审查时，填写要点可帮助系统聚焦检查方向（可选但推荐）。
                    </p>
                  </div>
                ) : null}

                <div className="mt-5">
                  <button
                    type="button"
                    onClick={() => setClassifyDetailsOpen((v) => !v)}
                    className="flex w-full items-center gap-2 text-[11px] font-medium text-muted"
                  >
                    {classifyDetailsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    识别详情（路由、槽位、材料角色）
                  </button>
                  {classifyDetailsOpen ? (
                    <div className="mt-3 space-y-4">
                      <div className="rounded-xl border border-border/10 bg-background/70 p-4 text-[12px]">
                        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                          <div className="text-[11px] font-medium text-primary">初始建议</div>
                          {typeof classification.confidence === 'number' ? (
                            <span className="rounded-full bg-background/80 px-2 py-0.5 text-[10px] text-muted">
                              置信度 {Math.round(classification.confidence * 100)}%
                            </span>
                          ) : null}
                        </div>
                        <div className="space-y-2 text-primary">
                          <p className="text-sm font-semibold">
                            初始建议路由：{ROUTE_LABELS[effectiveRoute] || effectiveRoute}
                          </p>
                          <p>文档类型：{classification.doc_type}</p>
                          <p>专业领域：{classification.domain}</p>
                          <p>推荐场景：{recommendedScene}</p>
                        </div>
                      </div>

                      {classification.adaptive_router ? (
                        <AdaptiveRouterCard
                          classification={classification}
                          requestedRoute={requestedRoute}
                          onApplyOverride={handleAdaptiveRouterOverride}
                        />
                      ) : null}

                      {parsePlan || reviewPlan ? (
                        <div
                          className="rounded-xl border border-border/10 bg-background/70 p-4 text-[12px]"
                          data-testid="super-agent-execution-plan-summary"
                        >
                          <div className="mb-2 text-[11px] font-medium text-muted">执行方案摘要</div>
                          <div className="space-y-2 text-primary">
                            {parsePlan ? (
                              <p>
                                解析方案：默认 {PROCESSING_MODE_LABELS[parsePlan.default_processing_mode] || parsePlan.default_processing_mode}
                                {parsePlan.files.length
                                  ? ` · ${parsePlan.files.length} 份材料按角色分级解析`
                                  : ''}
                              </p>
                            ) : null}
                            {reviewPlan ? (
                              <p>
                                解析前建议方案：{ROUTE_LABELS[reviewPlan.route] || reviewPlan.route}
                                {reviewPlan.bootstrap_review_plus && showReviewPlusFileGroupCopy ? ' · 将引导创建文件组任务' : ''}
                                {!showReviewPlusFileGroupCopy && reviewPlan.bootstrap_review_plus ? ' · 将引导创建智能审查载体任务' : ''}
                                {reviewPlan.run_structure_parse ? ' · 含结构化解析' : ''}
                              </p>
                            ) : null}
                          </div>
                          {parsePlan?.files?.length ? (
                            <ul className="mt-2 space-y-1 text-[11px] text-muted">
                              {parsePlan.files.map((item) => (
                                <li key={item.file_name}>
                                  {item.file_name}：{PARSING_TIER_LABELS[item.parsing_tier] || item.parsing_tier} /{' '}
                                  {PROCESSING_MODE_LABELS[item.processing_mode] || item.processing_mode}
                                </li>
                              ))}
                            </ul>
                          ) : null}
                          {reviewPlan?.downgrade_reasons?.length ? (
                            <p className="mt-2 text-[11px] text-amber-700 dark:text-amber-200">
                              {reviewPlan.downgrade_reasons.join('；')}
                            </p>
                          ) : null}
                        </div>
                      ) : null}

                      <div className="rounded-xl border border-border/10 bg-background/70 p-4 text-[12px]">
                        <div className="mb-2 text-[11px] font-medium text-muted">Review-Plus 槽位完整性</div>
                        <ul className="space-y-1.5">
                          {REVIEW_PLUS_SLOT_ITEMS.map((slot) => {
                            const present = classification.slot_completeness?.[slot.key] === true
                            const Icon = present ? CheckCircle2 : XCircle
                            return (
                              <li key={slot.key} className="flex items-start gap-2 text-[11px]">
                                <Icon
                                  className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${present ? 'text-positive' : 'text-destructive/80'}`}
                                  aria-hidden
                                />
                                <span className={present ? 'text-primary' : 'text-muted'}>{slot.label}</span>
                              </li>
                            )
                          })}
                        </ul>
                      </div>

                      {classification.material_roles?.length ? (
                        <div className="rounded-xl border border-border/10 bg-background/70 p-4 text-[12px]">
                          <div className="mb-2 text-[11px] font-medium text-muted">材料角色</div>
                          <ul className="space-y-1.5 text-[11px] text-muted">
                            {classification.material_roles.map((item) => (
                              <li key={item.file_name} className="flex items-start gap-2">
                                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-positive" aria-hidden />
                                <span>
                                  {item.file_name}：{MATERIAL_ROLE_LABELS[item.role] || item.role}
                                  {item.recommended_parsing_tier
                                    ? ` · 推荐 ${PARSING_TIER_LABELS[item.recommended_parsing_tier] || item.recommended_parsing_tier}`
                                    : ''}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                <div className="mt-5">
                  <button
                    type="button"
                    onClick={() => setAdvancedOpen((v) => !v)}
                    className="flex w-full items-center gap-2 text-[11px] font-medium text-muted"
                  >
                    {advancedOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    高级选项
                  </button>
                  {advancedOpen ? (
                    <div className="mt-3 space-y-3 rounded-lg border border-border/10 bg-background/50 p-3">
                      <label className="block">
                        <span className="text-[10px] font-medium text-muted">路由</span>
                        <select
                          value={requestedRoute}
                          onChange={(e) => setRequestedRoute(e.target.value as SuperAgentRoute)}
                          className="mt-1 w-full rounded-lg border border-border/25 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
                        >
                          {/* Primary options align with the three execution routes + auto. */}
                          <optgroup label="主路由">
                            <option value="auto">{ROUTE_LABELS.auto}</option>
                            <option value="smart">{ROUTE_LABELS.smart}</option>
                            <option value="review_plus">{ROUTE_LABELS.review_plus}</option>
                            <option value="gnc_review_only">{ROUTE_LABELS.gnc_review_only}</option>
                          </optgroup>
                          <optgroup label="高级">
                            <option value="structure_only">{ROUTE_LABELS.structure_only}</option>
                            <option value="hybrid">{ROUTE_LABELS.hybrid}</option>
                          </optgroup>
                        </select>
                        <p className="mt-1 text-[10px] text-muted/60">
                          当前：{ROUTE_LABELS[requestedRoute] || requestedRoute}（可手动覆盖自动结果）
                        </p>
                      </label>
                    </div>
                  ) : null}
                </div>

                <div className="mt-6 flex flex-wrap justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      void navigateToWizardStep(1)
                    }}
                    className="inline-flex min-h-10 items-center justify-center rounded-lg border border-border/20 bg-background px-4 text-[12px] font-medium text-primary"
                  >
                    ← 上一步
                  </button>
                  <button
                    type="button"
                    disabled={busy || !classification?.doc_type || reviewPlusSlotBlocked}
                    data-testid="super-agent-classify-next-cta"
                    onClick={() => {
                      void (async () => {
                        try {
                          setBusy(true)
                          setError('')
                          const checkpointRoute = resolveCheckpointRoute(reviewModeCard, requestedRoute)
                          let activeRun = run
                          let activeClassification = classification
                          if (run?.run_id) {
                            const ensured = await ensureClassifyPersistedOnRun(run, classification, {
                              processing_mode: processingMode,
                              requested_route: checkpointRoute,
                            })
                            activeRun = ensured.run
                            activeClassification = ensured.classification
                            setRun(activeRun)
                            setClassification(activeClassification)
                            setRequestedRoute(routeFromClassification(activeClassification.recommended_route, activeClassification))
                            const updated = await persistWizardCheckpoint({
                              wizard_step: 3,
                              classification: activeClassification,
                              processing_mode:
                                activeClassification.parse_plan?.default_processing_mode || processingMode,
                              requested_route: checkpointRoute,
                              review_mode_selection: reviewModeCardToSelection(reviewModeCard),
                              objective: reviewObjective.trim() || undefined,
                            })
                            if (!updated) return
                            setRun(updated)
                            if (updated.processing_mode) {
                              setProcessingMode(updated.processing_mode)
                            }
                          }
                          parseAutoStartedRef.current = false
                          resetParsePreviewState({ bumpSession: false })
                          setStep(3)
                        } catch (err) {
                          setError(err instanceof Error ? err.message : '保存进度失败')
                        } finally {
                          setBusy(false)
                        }
                      })()
                    }}
                    className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-brand px-5 text-[12px] font-medium text-white disabled:opacity-50"
                  >
                    下一步
                    <ChevronRight className="h-4 w-4" aria-hidden />
                  </button>
                </div>
              </>
            )}
          </section>
        ) : null}

        {step === 3 ? (
          <section
            className="flex flex-1 flex-col rounded-xl border border-border/15 bg-surface p-5 shadow-soft sm:p-6"
            data-testid="super-agent-wizard-step-3"
          >
            <div className="mb-4 flex items-center gap-2">
              <Search className="h-5 w-5 text-primaryAccent" aria-hidden />
              <div>
                <h2 className="text-base font-semibold text-primary">文档解析</h2>
                <p className="text-[11px] text-muted">
                  本步主任务是确认解析结果：先在对照工作台核对，再判定审查链路。
                </p>
              </div>
            </div>

            <ParseAdmissionSummary
              summary={parseAdmissionSummary}
              inProgress={showParseLoading || parseBusy}
            />

            <div className="mb-2 text-[11px] font-medium text-muted">解析对照工作台</div>

            <ParsePreviewPanel
              preview={parsePreview}
              files={files}
              parseBusy={parseBusy}
              loading={showParseLoading}
              parseProgress={parseProgress}
              parseLines={parseLines}
              showManualStart={showParseStartCta || Boolean(error)}
              onStartParse={() => {
                parseAutoStartedRef.current = true
                void runParsePreview()
              }}
              onReparse={() => {
                parseAutoStartedRef.current = true
                parseForceReparseRef.current = true
                resetParsePreviewState()
                void runParsePreview()
              }}
            />

            {parsePreview && postParsePlanClassification ? (
              <PostParseReviewPlanSection
                classification={postParsePlanClassification}
                reviewModeCard={reviewModeCard}
                requestedRoute={requestedRoute}
                onReviewModeCardChange={handleReviewModeCardChange}
                onAdaptiveRouterOverride={handleAdaptiveRouterOverride}
              />
            ) : null}

            <div className="mt-4 mb-4">
              <button
                type="button"
                onClick={() => setParseConfigOpen((v) => !v)}
                className="flex w-full items-center gap-2 text-[11px] font-medium text-muted"
                data-testid="super-agent-parse-config-toggle"
              >
                {parseConfigOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                识别与解析配置
              </button>
              {parseConfigOpen ? (
                <div className="mt-3 space-y-4" data-testid="super-agent-parse-config-panel">
                  {parsePreview?.structure_summary ? (
                    <div
                      className="rounded-xl border border-border/10 bg-background/70 p-4 text-[12px]"
                      data-testid="super-agent-structure-summary"
                    >
                      <div className="mb-2 text-[11px] font-medium text-muted">结构化详情</div>
                      <div className="space-y-1 text-primary">
                        <p>
                          章节节点：{parsePreview.structure_summary.section_count} · 证据条目：
                          {parsePreview.structure_summary.evidence_count}
                        </p>
                        {parsePreview.structure_summary.structure_ready ? (
                          <p className="text-[11px] text-positive">结构化产物已就绪。</p>
                        ) : (
                          <p className="text-[11px] text-muted">结构化预览生成中或尚未完成。</p>
                        )}
                      </div>
                      {parsePreview.structure_summary.top_sections?.length ? (
                        <ul className="mt-2 space-y-1 text-[11px] text-muted">
                          {parsePreview.structure_summary.top_sections.map((section, index) => (
                            <li key={section.section_id || `${section.level}-${section.title}-${index}`}>
                              {'·'.repeat(Math.max(1, section.level))} {section.title}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : null}

                  {classification ? (
                    <div className="rounded-xl border border-border/10 bg-background/70 p-4 text-[12px]">
                      <div className="mb-2 text-[11px] font-medium text-muted">步骤 2 识别配置</div>
                      <div className="space-y-2 text-primary">
                        <p>
                          审查场景：
                          {ROUTE_LABELS[reviewPlan?.route || resolveCheckpointRoute(reviewModeCard, requestedRoute)]
                            || reviewPlan?.route
                            || requestedRoute}
                        </p>
                        <p>
                          解析模式：
                          {PROCESSING_MODE_LABELS[parsePlan?.default_processing_mode || processingMode]
                            || parsePlan?.default_processing_mode
                            || processingMode}
                          {parsePlan?.files?.length ? ` · ${parsePlan.files.length} 份材料分级解析` : ''}
                        </p>
                        {reviewPlan?.required_tools?.length ? (
                          <p className="text-[11px] text-muted">
                            所需能力：{reviewPlan.required_tools.join('、')}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  ) : null}

                  <label className="block rounded-xl border border-border/10 bg-background/70 p-4">
                    <span className="text-[10px] font-medium text-muted">覆盖解析模式</span>
                    <select
                      value={processingMode}
                      onChange={(e) => handleProcessingModeChange(e.target.value)}
                      className="mt-2 w-full rounded-lg border border-border/25 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
                    >
                      <option value="OPTIMAL">{PROCESSING_MODE_LABELS.OPTIMAL}</option>
                      <option value="HIGH_ACCURACY">{PROCESSING_MODE_LABELS.HIGH_ACCURACY}</option>
                      <option value="HIGH_SPEED">{PROCESSING_MODE_LABELS.HIGH_SPEED}</option>
                    </select>
                    <p className="mt-2 text-[10px] text-muted/60">仅在需要时使用；默认沿用步骤 2 识别出的方案。</p>
                  </label>
                </div>
              ) : null}
            </div>

            <div className="mt-6 flex flex-wrap justify-between gap-2">
              {run?.status === 'completed' || run?.status === 'limited' ? (
                <button
                  type="button"
                  onClick={() => {
                    void navigateToWizardStep(5, { persistCheckpoint: false })
                  }}
                  className="inline-flex min-h-10 items-center justify-center rounded-lg border border-border/20 bg-background px-4 text-[12px] font-medium text-primary"
                >
                  ← 返回结果
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    void navigateToWizardStep(2)
                  }}
                  className="inline-flex min-h-10 items-center justify-center rounded-lg border border-border/20 bg-background px-4 text-[12px] font-medium text-primary"
                >
                  ← 上一步
                </button>
              )}
              <button
                type="button"
                disabled={
                  parseBusy
                  || !parsePreview
                  || busy
                  || (parsePreview?.structure_summary != null && !parsePreview.structure_summary.structure_ready)
                }
                data-testid="super-agent-confirm-parse-cta"
                onClick={() => {
                  void (async () => {
                    try {
                      if (run?.run_id && canPersistWizardCheckpoint(run)) {
                        setBusy(true)
                        const updated = await persistWizardCheckpoint({
                          wizard_step: 4,
                          parse_preview: parsePreview ?? undefined,
                          processing_mode: processingMode,
                          requested_route: resolveReviewStartRoute(
                            reviewModeCard,
                            requestedRoute,
                            classification,
                            true,
                          ),
                          review_mode_selection: reviewModeCardToSelection(reviewModeCard),
                          classification: postParsePlanClassification ?? classification ?? undefined,
                          objective: reviewObjective.trim() || undefined,
                        })
                        setBusy(false)
                        if (!updated) return
                      }
                      await handleStartReview()
                    } catch (err) {
                      setError(err instanceof Error ? err.message : '启动审查失败')
                      setBusy(false)
                    }
                  })()
                }}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-brand px-5 text-[12px] font-medium text-white disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Sparkles className="h-4 w-4" aria-hidden />}
                {confirmReviewCtaLabel}
              </button>
            </div>
          </section>
        ) : null}

        {step === 4 && run ? (
          <section className="flex min-h-[560px] flex-1 flex-col rounded-xl border border-border/15 bg-surface p-5 shadow-soft sm:p-6">
            <div className="mb-4 flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primaryAccent" aria-hidden />
              <div>
                <h2 className="text-base font-semibold text-primary">文档审查</h2>
                <p className="text-[11px] text-muted">正在执行智能审查，请稍候…</p>
              </div>
            </div>
            <SuperAgentProcessingView
              run={run}
              classification={classification}
              isRunning={busy || run.status === 'running'}
              onResume={() => void (loadFailedRunId ? handleReloadRun() : handleResumeRun())}
              resumeBusy={busy}
            />
            {(run.status === 'interrupted' || run.status === 'failed')
            && (parsePreview || run.parse_preview) ? (
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => {
                    void navigateToWizardStep(3, { restoreParsePreview: true, persistCheckpoint: false })
                  }}
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border/20 bg-background px-4 text-[12px] font-medium text-primary"
                >
                  <Search className="h-4 w-4" aria-hidden />
                  ← 返回解析
                </button>
              </div>
            ) : null}
          </section>
        ) : null}

        {step === 5 && run ? (
          <SuperAgentResultStep
            run={run}
            classification={classification}
            loadFailedRunId={loadFailedRunId}
            busy={busy}
            parsePreview={parsePreview}
            onReloadRun={handleReloadRun}
            onExport={handleExport}
            onStartReview={handleStartReview}
            onViewParsePreview={() => navigateToWizardStep(3, { restoreParsePreview: true, persistCheckpoint: false })}
            onResetWizard={resetWizard}
          />
        ) : null}
      </div>
    </div>
  )
}
