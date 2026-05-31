'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, ChevronDown, ChevronRight, Loader2, RefreshCw, Route, Sparkles, X } from 'lucide-react'
import {
  WorkflowDAGViewer,
  isHorizontalWorkflowLayout,
  type AutoLayoutVariant,
} from '@aqua/workflow-core'
import type { WorkflowStepStatus } from '@aqua/workflow-core'
import Link from 'next/link'
import { ExternalLink } from 'lucide-react'
import { getReviewPlusDetail } from '@/features/review-plus-v2/api'
import {
  buildSuperAgentWorkbenchHref,
  defaultWorkbenchTabForRun,
  resolveSuperAgentWorkbenchReviewType,
} from '@/features/unified-review-workbench/utils/superAgentWorkbenchLink'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import {
  buildNodeDetail,
  buildNodeDetailPanelModel,
  buildSuperAgentProcessingViewModel,
  buildReviewBusinessStatus,
  getActiveSuperAgentNodeId,
  isPausedStepStatus,
  normalizeSuperAgentCanvasNodeId,
  resolveSuperAgentFlowNodeContext,
  resolveSuperAgentNodeLlmTraces,
  resolveLaneDeepParallelTasks,
  stepStatusDisplayLabel,
  formatChatElapsed,
} from '@/features/super-agent/utils/superAgentProcessingViewModel'
import type {
  SuperAgentFlowNodeContext,
  SuperAgentFlowNodeDetail,
  SuperAgentLlmTraceRecord,
  SuperAgentNodeDetailPanelModel,
  SuperAgentProcessItem,
} from '@/features/super-agent/utils/superAgentProcessingViewModel'
import ExecutionMetricsPanel from '@/features/super-agent/components/ExecutionMetricsPanel'
import ReviewBusinessStatusCard from '@/features/super-agent/components/ReviewBusinessStatusCard'
import SmartCommitteeDiagnosticsCard from '@/features/super-agent/components/SmartCommitteeDiagnosticsCard'
import type { MaterialClassification, SuperAgentRun } from '@/features/super-agent/types'
import { SUPER_AGENT_PROCESSING_TERMS } from '@/lib/aeroTerminology'
import {
  STALE_RUNNING_MS,
  getSuperAgentRunLastActivityMs,
  isSuperAgentRunStale,
  resolveSuperAgentRunPauseContext,
  type SuperAgentRunPauseContext,
} from '@/features/super-agent/utils/superAgentResumeState'
import { cn } from '@/lib/utils'

const SUPER_AGENT_ALLOWED_LAYOUT_VARIANTS: AutoLayoutVariant[] = ['horizontal', 'vertical', 'compact']

function useStaleRunningDetection(run: SuperAgentRun, reviewPlusTask?: ReviewPlusTaskDetail | null): boolean {
  const activityAtRef = useRef(getSuperAgentRunLastActivityMs(run, reviewPlusTask))
  const lastUpdatedAtRef = useRef(run.updated_at)
  const lastReviewPlusUpdatedAtRef = useRef(reviewPlusTask?.updated_at)
  const [isStale, setIsStale] = useState(() => isSuperAgentRunStale(run, Date.now(), STALE_RUNNING_MS, reviewPlusTask))

  useEffect(() => {
    if (
      run.updated_at !== lastUpdatedAtRef.current
      || reviewPlusTask?.updated_at !== lastReviewPlusUpdatedAtRef.current
    ) {
      lastUpdatedAtRef.current = run.updated_at
      lastReviewPlusUpdatedAtRef.current = reviewPlusTask?.updated_at
      activityAtRef.current = getSuperAgentRunLastActivityMs(run, reviewPlusTask)
    }
  }, [run.updated_at, run.created_at, reviewPlusTask?.updated_at])

  useEffect(() => {
    if (run.status !== 'running') {
      setIsStale(false)
      return
    }
    const check = () => {
      setIsStale(isSuperAgentRunStale(run, Date.now(), STALE_RUNNING_MS, reviewPlusTask))
    }
    check()
    const timer = window.setInterval(check, 10_000)
    return () => window.clearInterval(timer)
  }, [run.status, run.updated_at, run.skill_traces, reviewPlusTask?.status, reviewPlusTask?.updated_at])

  return isStale
}

interface Props {
  run: SuperAgentRun
  classification?: MaterialClassification | null
  isRunning?: boolean
  onResume?: () => void
  resumeBusy?: boolean
}

function nodeTone(status: WorkflowStepStatus, pauseContext: SuperAgentRunPauseContext = 'active'): string {
  if (status === 'interrupted' || isPausedStepStatus(status, pauseContext)) {
    return 'border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]'
  }
  switch (status) {
    case 'completed':
      return 'border-positive/25 bg-positive/8 text-positive'
    case 'running':
      return 'border-primaryAccent/35 bg-primaryAccent/10 text-primaryAccent'
    case 'failed':
    case 'blocked':
      return 'border-destructive/25 bg-destructive/10 text-destructive'
    case 'awaiting_confirm':
      return 'border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]'
    default:
      return 'border-border/20 bg-surface text-muted'
  }
}

function statusDot(status: WorkflowStepStatus, pauseContext: SuperAgentRunPauseContext = 'active'): string {
  if (status === 'interrupted' || isPausedStepStatus(status, pauseContext)) return 'bg-[rgb(var(--color-sa-gold))]'
  if (status === 'completed') return 'bg-positive'
  if (status === 'running') return 'animate-pulse bg-primaryAccent'
  if (status === 'failed' || status === 'blocked') return 'bg-destructive'
  if (status === 'awaiting_confirm') return 'bg-[rgb(var(--color-sa-gold))]'
  return 'bg-muted/35'
}

function StatusPill({
  status,
  pauseContext = 'active',
}: {
  status: WorkflowStepStatus
  pauseContext?: SuperAgentRunPauseContext
}) {
  const showSpinner = status === 'running'
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-medium', nodeTone(status, pauseContext))}>
      {showSpinner ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}
      {stepStatusDisplayLabel(status, pauseContext)}
    </span>
  )
}

function ProcessItemCard({
  item,
  defaultOpen = false,
  forceOpen = false,
  selectedProcessItemId = '',
  depth = 0,
  isLast = false,
  pauseContext = 'active',
}: {
  item: SuperAgentProcessItem
  defaultOpen?: boolean
  forceOpen?: boolean
  selectedProcessItemId?: string
  depth?: number
  isLast?: boolean
  pauseContext?: SuperAgentRunPauseContext
}) {
  const hasSelectedChild = Boolean(item.children?.some((child) => child.id === selectedProcessItemId))
  const [open, setOpen] = useState(defaultOpen)

  useEffect(() => {
    if (forceOpen || hasSelectedChild) setOpen(true)
  }, [forceOpen, hasSelectedChild])

  const childCount = item.children?.length || 0
  const childDone = item.children?.filter((child) => child.status === 'completed').length || 0
  const selected = selectedProcessItemId === item.id
  const showLine = depth === 0 && !isLast

  return (
    <div className={cn('relative', depth === 0 ? 'pl-6' : 'pl-4')}>
      {showLine ? <span className="absolute left-[5px] top-5 bottom-[-10px] w-px bg-border/20" aria-hidden /> : null}
      {depth > 0 ? <span className="absolute left-0 top-5 h-px w-4 bg-border/25" aria-hidden /> : null}
      <span className={cn('absolute top-4 size-2.5 rounded-full ring-4 ring-background', depth === 0 ? 'left-0' : '-left-[5px]', statusDot(item.status, pauseContext))} />

      <article
        className={cn(
          'rounded-xl bg-surface/70 transition',
          selected ? 'ring-1 ring-primaryAccent/45' : '',
          depth === 0 ? 'border border-border/15 shadow-sm' : 'border border-border/10',
        )}
      >
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex w-full items-start gap-2 px-3 py-3 text-left"
        >
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className={cn('font-semibold text-primary', depth === 0 ? 'text-[12px]' : 'text-[11px]')}>{item.title}</h3>
              <StatusPill status={item.status} pauseContext={pauseContext} />
              <span className="rounded-full border border-border/15 bg-background px-2 py-0.5 text-[9px] text-muted">
                {item.relation}
              </span>
              {childCount ? (
                <span className="rounded-full border border-primaryAccent/15 bg-primaryAccent/8 px-2 py-0.5 text-[9px] text-primaryAccent">
                  子任务 {childDone}/{childCount}
                </span>
              ) : null}
            </div>
            <p className="mt-1 line-clamp-1 text-[11px] leading-relaxed text-muted">{item.summary}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {item.tags.slice(0, 3).map((tag) => (
                <span key={`${item.id}-${tag}`} className="rounded-full border border-border/15 bg-background/70 px-2 py-0.5 text-[9px] text-muted">
                  {tag}
                </span>
              ))}
            </div>
          </div>
          <span className="mt-0.5 shrink-0 rounded-md p-1 text-muted hover:bg-muted/10">
            {open ? <ChevronDown className="h-4 w-4" aria-hidden /> : <ChevronRight className="h-4 w-4" aria-hidden />}
          </span>
        </button>

        {open ? (
          <div className="px-3 pb-3 pt-0">
            {item.children?.length ? (
              <div className="relative ml-2 mt-1 space-y-2 border-l border-border/20 pl-5">
                {item.children.map((child, index) => (
                  <ProcessItemCard
                    key={child.id}
                    item={child}
                    forceOpen={selectedProcessItemId === child.id}
                    selectedProcessItemId={selectedProcessItemId}
                    depth={depth + 1}
                    isLast={index === (item.children?.length || 0) - 1}
                    pauseContext={pauseContext}
                  />
                ))}
              </div>
            ) : null}

            {item.details.length ? (
              <div className={cn('rounded-lg bg-background/60 px-3 py-2', item.children?.length ? 'mt-3' : 'mt-1')}>
                <div className="text-[9px] font-medium text-muted">详细过程</div>
                <ul className="mt-1 space-y-1">
                  {item.details.map((detail, index) => (
                    <li key={`${item.id}-detail-${index}`} className="text-[10px] leading-relaxed text-primary/85">
                      {detail}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {item.findings.length ? (
              <div className="mt-2 rounded-lg bg-background/60 px-3 py-2">
                <div className="text-[9px] font-medium text-muted">阶段性发现</div>
                <ul className="mt-1 space-y-1">
                  {item.findings.map((finding, index) => (
                    <li key={`${item.id}-finding-${index}`} className="text-[10px] leading-relaxed text-muted">
                      {finding}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </article>
    </div>
  )
}

function findProcessItem(
  processItemId: string | undefined,
  processItems: SuperAgentProcessItem[],
): SuperAgentProcessItem | undefined {
  if (!processItemId) return undefined
  for (const item of processItems) {
    if (item.id === processItemId) return item
    const child = item.children?.find((candidate) => candidate.id === processItemId)
    if (child) return child
  }
  return undefined
}

function traceStatusTone(status: string): string {
  if (status === 'completed') return 'border-positive/25 bg-positive/8 text-positive'
  if (status === 'failed') return 'border-destructive/25 bg-destructive/10 text-destructive'
  if (status === 'running') return 'border-primaryAccent/35 bg-primaryAccent/10 text-primaryAccent'
  if (status === 'skipped') return 'border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]'
  return 'border-border/20 bg-background text-muted'
}

function LlmTraceRecordCard({ record }: { record: SuperAgentLlmTraceRecord }) {
  return (
    <article className="rounded-lg border border-border/15 bg-background/80 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[11px] font-semibold text-primary">{record.agentName}</div>
          {record.toolName ? (
            <div className="mt-0.5 truncate text-[9px] text-muted">
              {SUPER_AGENT_PROCESSING_TERMS.toolCall}：{record.toolName}
            </div>
          ) : null}
        </div>
        <span className={cn('shrink-0 rounded-full border px-1.5 py-0.5 text-[8px] font-medium', traceStatusTone(record.status))}>
          {record.status}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-2 text-[9px] text-muted">
        {record.elapsedMs ? <span>{formatChatElapsed(record.elapsedMs)}</span> : null}
        {record.timestamp ? <span>{record.timestamp}</span> : null}
      </div>
      {record.inputLines.length ? (
        <div className="mt-2">
          <div className="text-[8px] font-medium text-muted">{SUPER_AGENT_PROCESSING_TERMS.inputSummary}</div>
          <ul className="mt-0.5 space-y-0.5">
            {record.inputLines.slice(0, 5).map((line, index) => (
              <li key={`${record.id}-in-${index}`} className="text-[9px] leading-relaxed text-primary/85">{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {record.outputLines.length ? (
        <div className="mt-2">
          <div className="text-[8px] font-medium text-muted">{SUPER_AGENT_PROCESSING_TERMS.outputSummary}</div>
          <ul className="mt-0.5 space-y-0.5">
            {record.outputLines.slice(0, 6).map((line, index) => (
              <li key={`${record.id}-out-${index}`} className="text-[9px] leading-relaxed text-primary/85">{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {record.findings.length ? (
        <div className="mt-2">
          <div className="text-[8px] font-medium text-muted">{SUPER_AGENT_PROCESSING_TERMS.stageFindings}</div>
          <ul className="mt-0.5 space-y-0.5">
            {record.findings.slice(0, 4).map((line, index) => (
              <li key={`${record.id}-finding-${index}`} className="text-[9px] leading-relaxed text-muted">{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {record.evidenceRefs.length ? (
        <div className="mt-2">
          <div className="text-[8px] font-medium text-muted">{SUPER_AGENT_PROCESSING_TERMS.relatedEvidence}</div>
          <div className="mt-0.5 flex flex-wrap gap-1">
            {record.evidenceRefs.slice(0, 6).map((ref) => (
              <span key={`${record.id}-${ref}`} className="rounded border border-border/15 px-1.5 py-0.5 text-[8px] text-muted">
                {ref}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {record.warnings.length ? (
        <ul className="mt-2 space-y-0.5">
          {record.warnings.slice(0, 3).map((warning, index) => (
            <li key={`${record.id}-warn-${index}`} className="rounded bg-[rgb(var(--color-sa-gold))]/10 px-1.5 py-0.5 text-[9px] text-[rgb(var(--color-sa-gold))]">
              {warning}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  )
}

function DetailSectionBlock({
  title,
  lines,
}: {
  title: string
  lines: string[]
}) {
  if (!lines.length) return null
  return (
    <section className="mt-3 rounded-xl border border-border/15 bg-background/70 p-3">
      <div className="text-[9px] font-medium text-muted">{title}</div>
      <ul className="mt-2 space-y-1">
        {lines.map((line, index) => (
          <li key={`${title}-${index}`} className="text-[10px] leading-relaxed text-primary/90">
            {line}
          </li>
        ))}
      </ul>
    </section>
  )
}

function NodeDetailPanel({
  node,
  nodeDetail,
  panelModel,
  processItem,
  llmTraces,
  deepParallelTasks = [],
  open,
  onClose,
  pauseContext = 'active',
}: {
  node: SuperAgentFlowNodeContext | null
  nodeDetail: SuperAgentFlowNodeDetail | null
  panelModel: SuperAgentNodeDetailPanelModel
  processItem?: SuperAgentProcessItem
  llmTraces: SuperAgentLlmTraceRecord[]
  deepParallelTasks?: ReturnType<typeof resolveLaneDeepParallelTasks>
  open: boolean
  onClose: () => void
  pauseContext?: SuperAgentRunPauseContext
}) {
  if (!node) return null

  const displayStatus = nodeDetail?.status || node.status
  const hasDiagnostics = panelModel.diagnosticSections.length > 0
    || llmTraces.length > 0
    || Boolean(processItem)

  return (
    <div
      className={cn(
        'absolute inset-y-0 right-0 z-20 flex h-full max-h-full w-[320px] max-w-[82%] flex-col border-l border-border/15 bg-surface/95 shadow-2xl backdrop-blur transition-transform duration-200',
        open ? 'translate-x-0' : 'translate-x-full pointer-events-none',
      )}
      aria-hidden={!open}
    >
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-border/15 px-3">
        <div className="min-w-0">
          <div className="truncate text-[12px] font-semibold text-primary">节点详情</div>
          <div className="truncate text-[9px] text-muted">{nodeDetail?.label || node.label}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭节点详情"
          className="flex size-7 items-center justify-center rounded-md text-muted hover:bg-muted/10 hover:text-primary"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <div className="rounded-xl border border-border/15 bg-background/70 p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-primary">{nodeDetail?.label || node.label}</div>
              <p className="mt-1 text-[10px] leading-relaxed text-muted">{node.subtitle || '暂无节点摘要'}</p>
            </div>
            <StatusPill status={displayStatus} pauseContext={pauseContext} />
          </div>
        </div>

        <DetailSectionBlock
          title="业务摘要"
          lines={panelModel.businessSummary.length ? panelModel.businessSummary : [node.subtitle || '暂无业务摘要']}
        />

        {panelModel.reviewSections.map((section) => (
          <DetailSectionBlock key={`review-${section.title}`} title={section.title} lines={section.lines} />
        ))}

        {panelModel.phaseSections.map((section) => (
          <DetailSectionBlock key={`phase-${section.title}`} title={section.title} lines={section.lines} />
        ))}

        {deepParallelTasks.length ? (
          <section className="mt-3 rounded-xl border border-border/15 bg-background/70 p-3">
            <div className="text-[9px] font-medium text-muted">并行子任务</div>
            <ul className="mt-2 space-y-2">
              {deepParallelTasks.map((task) => (
                <li key={task.id} className="rounded-lg border border-border/15 bg-background/80 px-2.5 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-semibold text-primary">{task.label}</span>
                    <StatusPill status={task.status} pauseContext={pauseContext} />
                  </div>
                  <p className="mt-1 text-[9px] leading-relaxed text-muted">{task.summary}</p>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {hasDiagnostics ? (
          <details className="mt-3 rounded-xl border border-border/15 bg-background/50 p-3">
            <summary className="cursor-pointer text-[9px] font-medium text-muted">诊断信息</summary>
            <div className="mt-2 space-y-2">
              {panelModel.diagnosticSections.map((section) => (
                <div key={`diag-${section.title}`}>
                  <div className="text-[8px] font-medium text-muted">{section.title}</div>
                  <ul className="mt-1 space-y-0.5">
                    {section.lines.map((line, index) => (
                      <li key={`${section.title}-${index}`} className="text-[9px] leading-relaxed text-muted">
                        {line}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}

              <div>
                <div className="text-[8px] font-medium text-muted">{SUPER_AGENT_PROCESSING_TERMS.llmTraceTitle}</div>
                {llmTraces.length ? (
                  <div className="mt-2 space-y-2">
                    {llmTraces.map((record) => (
                      <LlmTraceRecordCard key={record.id} record={record} />
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-[10px] leading-relaxed text-muted">
                    {SUPER_AGENT_PROCESSING_TERMS.noLlmTrace}
                  </p>
                )}
              </div>

              {processItem ? (
                <div>
                  <div className="text-[8px] font-medium text-muted">{SUPER_AGENT_PROCESSING_TERMS.phaseSummary}</div>
                  <div className="mt-2 space-y-2">
                    <div className="text-[11px] font-semibold text-primary">{processItem.title}</div>
                    <p className="text-[10px] leading-relaxed text-muted">{processItem.summary}</p>
                    {processItem.tags.length ? (
                      <div className="flex flex-wrap gap-1">
                        {processItem.tags.slice(0, 4).map((tag) => (
                          <span key={`${node.nodeId}-${tag}`} className="rounded-full border border-border/15 bg-surface px-2 py-0.5 text-[9px] text-muted">
                            {tag}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          </details>
        ) : null}
      </div>
    </div>
  )
}

function SuperAgentFlowCanvas({
  runId,
  run,
  classification,
  reviewPlusTask,
  workflowGraph,
  flowGraph,
  initialExpandedTeamLeadIds,
  processItems,
  activeNodeId,
  selectedNodeId,
  detailOpen,
  onSelectNode,
  onCloseDetail,
  pauseContext = 'active',
}: {
  runId: string
  run: SuperAgentRun
  classification?: MaterialClassification | null
  reviewPlusTask?: ReviewPlusTaskDetail | null
  workflowGraph: ReturnType<typeof buildSuperAgentProcessingViewModel>['workflowGraph']
  flowGraph: ReturnType<typeof buildSuperAgentProcessingViewModel>['flowGraph']
  initialExpandedTeamLeadIds: ReturnType<typeof buildSuperAgentProcessingViewModel>['initialExpandedTeamLeadIds']
  processItems: SuperAgentProcessItem[]
  activeNodeId: string
  selectedNodeId: string
  detailOpen: boolean
  onSelectNode: (nodeId: string) => void
  onCloseDetail: () => void
  pauseContext?: SuperAgentRunPauseContext
}) {
  const [effectiveLayoutVariant, setEffectiveLayoutVariant] = useState<AutoLayoutVariant>('horizontal')
  const selectedContext = useMemo(
    () => (selectedNodeId ? resolveSuperAgentFlowNodeContext(selectedNodeId, flowGraph) : null),
    [selectedNodeId, flowGraph],
  )
  const selectedProcessItem = findProcessItem(selectedContext?.processItemId, processItems)
  const selectedLlmTraces = useMemo(
    () => (selectedNodeId
      ? resolveSuperAgentNodeLlmTraces(selectedNodeId, run, { classification, reviewPlusTask })
      : []),
    [selectedNodeId, run, classification, reviewPlusTask],
  )
  const selectedNodeDetail = useMemo(
    () => (selectedNodeId
      ? buildNodeDetail(selectedNodeId, run, { classification, reviewPlusTask })
      : null),
    [selectedNodeId, run, classification, reviewPlusTask],
  )
  const selectedPanelModel = useMemo(
    () => buildNodeDetailPanelModel(selectedNodeDetail, selectedContext?.subtitle || ''),
    [selectedNodeDetail, selectedContext?.subtitle],
  )
  const selectedDeepTasks = useMemo(
    () => (selectedNodeId
      ? resolveLaneDeepParallelTasks(selectedNodeId, run, { classification, reviewPlusTask })
      : []),
    [selectedNodeId, run, classification, reviewPlusTask],
  )
  const layoutDirectionLabel = isHorizontalWorkflowLayout(effectiveLayoutVariant) ? '横向主链' : '纵向主链'

  return (
    <div
      className="relative h-full min-h-0 overflow-hidden bg-background"
      data-testid="super-agent-flow-canvas"
      data-layout-variant={effectiveLayoutVariant}
    >
      <WorkflowDAGViewer
        className="h-full min-h-[320px]"
        graph={workflowGraph}
        mode="live"
        activeNodeId={selectedNodeId || activeNodeId}
        onSelectNode={onSelectNode}
        onPaneClick={onCloseDetail}
        defaultAutoLayoutVariant="horizontal"
        defaultLayoutVariantPreference="auto"
        enableResponsiveLayout
        onEffectiveLayoutVariantChange={setEffectiveLayoutVariant}
        allowedLayoutVariants={SUPER_AGENT_ALLOWED_LAYOUT_VARIANTS}
        layoutStorageKey={`super-agent-processing-flow:${runId}`}
        initialExpandedTeamLeadIds={initialExpandedTeamLeadIds}
        title="文档审查执行流程"
        description={`审查准备 → 专项分派 → 并行审查 → 汇合 → 结论 · ${layoutDirectionLabel}`}
      />
      <NodeDetailPanel
        node={selectedContext}
        nodeDetail={selectedNodeDetail}
        panelModel={selectedPanelModel}
        processItem={selectedProcessItem}
        llmTraces={selectedLlmTraces}
        deepParallelTasks={selectedDeepTasks}
        open={detailOpen}
        onClose={onCloseDetail}
        pauseContext={pauseContext}
      />
    </div>
  )
}

export default function SuperAgentProcessingView({
  run,
  classification,
  isRunning = false,
  onResume,
  resumeBusy = false,
}: Props) {
  const [reviewPlusTask, setReviewPlusTask] = useState<ReviewPlusTaskDetail | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [detailOpen, setDetailOpen] = useState(false)
  useEffect(() => {
    const sourceReviewId = run.source_review_id
    const shouldPollReviewPlus =
      Boolean(sourceReviewId) &&
      (isRunning || run.status === 'running')
    const shouldLoadReviewPlus =
      Boolean(sourceReviewId) &&
      (shouldPollReviewPlus || run.status === 'completed' || run.status === 'limited')

    if (!shouldLoadReviewPlus || !sourceReviewId) {
      setReviewPlusTask(null)
      return
    }
    let cancelled = false
    const poll = async () => {
      try {
        const detail = await getReviewPlusDetail(sourceReviewId)
        if (!cancelled) setReviewPlusTask(detail)
      } catch {
        if (!cancelled) setReviewPlusTask(null)
      }
    }
    void poll()
    if (!shouldPollReviewPlus) return () => { cancelled = true }
    const timer = window.setInterval(poll, 2500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [run.source_review_id, run.status, isRunning])

  const isStaleRunning = useStaleRunningDetection(run, reviewPlusTask)
  const pauseContext = resolveSuperAgentRunPauseContext(run, { resumeBusy, isStaleRunning })

  const viewModel = useMemo(
    () => buildSuperAgentProcessingViewModel(run, { classification, reviewPlusTask, pauseContext }),
    [run, classification, reviewPlusTask, pauseContext],
  )

  const activeNodeId = useMemo(
    () => getActiveSuperAgentNodeId(run, reviewPlusTask, pauseContext),
    [run, reviewPlusTask, pauseContext],
  )
  const runningItemId = viewModel.processItems.find(
    (item) => item.status === 'running' || isPausedStepStatus(item.status, pauseContext),
  )?.id
  const selectedContext = selectedNodeId
    ? resolveSuperAgentFlowNodeContext(selectedNodeId, viewModel.flowGraph)
    : null
  const selectedProcessItemId = selectedContext?.processItemId || ''
  const knownNodeIds = useMemo(
    () => new Set(viewModel.workflowGraph.nodes.map((node) => node.node_id)),
    [viewModel.workflowGraph.nodes],
  )

  useEffect(() => {
    if (selectedNodeId && !knownNodeIds.has(selectedNodeId)) {
      setSelectedNodeId('')
      setDetailOpen(false)
    }
  }, [knownNodeIds, selectedNodeId])

  const needsResume =
    run.status === 'interrupted' || run.status === 'failed' || (run.status === 'running' && isStaleRunning)
  const showResumeCta =
    Boolean(onResume) && needsResume && !resumeBusy && (!isRunning || isStaleRunning)
  const resumeLabel = run.status === 'failed' ? '重新续跑' : '继续执行'
  const runningStageDetail = viewModel.currentStage.includes(' · ')
    ? viewModel.currentStage.split(' · ').slice(1).join(' · ')
    : ''
  const reviewPlusWarnings = useMemo(() => {
    const warnings: string[] = []
    const reviewTrace = (run.skill_traces || []).find((trace) => trace.skill_id === 'run_review_plus')
    if (reviewTrace?.warnings?.length) {
      warnings.push(...reviewTrace.warnings.slice(0, 3))
    }
    const fallbackCount = run.structured_bundle?.parser_fallback_logs?.length || 0
    if (fallbackCount > 0) {
      warnings.push(`解析/LLM 分块出现 ${fallbackCount} 次降级回退，部分结果可能不完整`)
    }
    for (const item of run.trace_report?.degradation_summary || []) {
      if (item && !warnings.includes(item)) warnings.push(item)
    }
    return warnings.slice(0, 4)
  }, [run.skill_traces, run.structured_bundle?.parser_fallback_logs, run.trace_report?.degradation_summary])
  const reviewBusinessStatus = useMemo(
    () => buildReviewBusinessStatus(viewModel, run, reviewPlusWarnings),
    [viewModel, run, reviewPlusWarnings],
  )
  const workbenchHref = buildSuperAgentWorkbenchHref(run, { tab: defaultWorkbenchTabForRun(run) })
  const workbenchReviewType = resolveSuperAgentWorkbenchReviewType(run)
  const headerTitle = resumeBusy
    ? '正在续跑…'
    : run.status === 'failed'
      ? '审查执行失败'
      : run.status === 'interrupted'
        ? '审查已中断'
        : isStaleRunning
          ? '审查可能已停滞'
          : isRunning || run.status === 'running'
            ? runningStageDetail
              ? viewModel.currentStage
              : '审查进行中'
            : '审查流程回放'
  const resumeHint = run.status === 'failed'
    ? (run.error || '审查执行失败，可手动续跑恢复进度。')
    : run.status === 'interrupted'
      ? (run.error || '审查任务已中断，可继续执行以恢复进度。')
      : isStaleRunning
        ? (run.error || '进度长时间未更新，如任务已中断可尝试继续执行。')
        : run.status === 'running' && runningStageDetail
          ? `当前步骤：${runningStageDetail}。Review-Plus 委托步骤可能需 20–40 分钟，请耐心等待。`
          : ''

  return (
    <div className="flex min-h-[480px] flex-1 flex-col overflow-hidden" data-testid="super-agent-processing-view">
      <div className="mb-3 shrink-0 space-y-2">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            {resumeBusy ? (
              <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primaryAccent" aria-hidden />
            ) : isStaleRunning || (needsResume && !isRunning) ? (
              <RefreshCw className="h-4 w-4 shrink-0 text-[rgb(var(--color-sa-gold))]" aria-hidden />
            ) : isRunning || run.status === 'running' ? (
              <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primaryAccent" aria-hidden />
            ) : (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-positive" aria-hidden />
            )}
            <h2 className="text-base font-semibold text-primary">{headerTitle}</h2>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {showResumeCta ? (
              <button
                type="button"
                data-testid="super-agent-resume-cta"
                onClick={onResume}
                className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg bg-brand px-3.5 text-[11px] font-medium text-white shadow-sm"
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                {resumeLabel}
              </button>
            ) : null}
            <span className="rounded-full border border-primaryAccent/25 bg-primaryAccent/10 px-2.5 py-1 text-[10px] font-medium tabular-nums text-primaryAccent">
              {viewModel.progress}%
            </span>
            <span className="hidden max-w-[140px] truncate rounded-full border border-border/20 bg-background px-2.5 py-1 text-[10px] text-muted sm:inline">
              {viewModel.currentStage}
            </span>
            {workbenchHref ? (
              <Link
                href={workbenchHref}
                className="inline-flex items-center gap-1 rounded-lg border border-border/20 bg-background px-2 py-1 text-[10px] font-medium text-primaryAccent hover:bg-primaryAccent/5"
                title={workbenchReviewType === 'gnc' ? '打开 GNC 统一审查工作台' : '打开统一审查工作台'}
              >
                {workbenchReviewType === 'gnc' ? 'GNC 工作台' : '统一工作台'}
                <ExternalLink className="h-3 w-3" aria-hidden />
              </Link>
            ) : null}
          </div>
        </div>
        {resumeHint ? (
          <p
            className={cn(
              'text-[10px] leading-relaxed',
              showResumeCta ? 'text-[rgb(var(--color-sa-gold))]' : 'text-muted',
            )}
            data-testid="super-agent-resume-hint"
          >
            {resumeHint}
          </p>
        ) : (
          <p className="text-[10px] text-muted sm:hidden">当前：{viewModel.currentStage}</p>
        )}
        {reviewPlusWarnings.length && (run.status === 'running' || isRunning) ? (
          <div
            className="rounded-lg border border-[rgb(var(--color-sa-gold))]/25 bg-[rgb(var(--color-sa-gold))]/8 px-3 py-2 text-[10px] leading-relaxed text-[rgb(var(--color-sa-gold))]"
            data-testid="super-agent-review-plus-warnings"
          >
            {reviewPlusWarnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        ) : null}
      </div>

      <ReviewBusinessStatusCard
        status={reviewBusinessStatus}
        isRunning={isRunning || run.status === 'running'}
      />

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
        <section className="flex min-h-[320px] min-w-0 flex-col overflow-hidden rounded-xl border border-border/15 bg-background">
          <div className="flex shrink-0 items-center gap-2 border-b border-border/10 px-4 py-2.5">
            <Sparkles className="h-4 w-4 text-primaryAccent" aria-hidden />
            <span className="text-[12px] font-medium text-primary">处理过程</span>
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
            <div className="rounded-xl border border-primaryAccent/15 bg-primaryAccent/[0.05] px-3 py-2">
              <div className="flex items-center gap-2 text-[11px] font-medium text-primary">
                <Sparkles className="h-3.5 w-3.5 text-primaryAccent" aria-hidden />
                正在研究审查任务
              </div>
              <p className="mt-1 text-[10px] leading-relaxed text-muted">
                展示智能体执行轨迹、工具调用与阶段性审查输出。
              </p>
            </div>
            {viewModel.processItems.map((item, index) => (
              <ProcessItemCard
                key={item.id}
                item={item}
                defaultOpen={item.id === runningItemId}
                forceOpen={selectedProcessItemId === item.id}
                selectedProcessItemId={selectedProcessItemId}
                isLast={index === viewModel.processItems.length - 1}
                pauseContext={pauseContext}
              />
            ))}
          </div>
        </section>

        <section className="flex min-h-[320px] min-w-0 flex-col overflow-hidden rounded-xl border border-border/15 bg-background">
          <div className="flex shrink-0 items-center gap-2 border-b border-border/10 px-4 py-2.5">
            <Route className="h-4 w-4 text-primaryAccent" aria-hidden />
            <span className="text-[12px] font-medium text-primary">结构关系图</span>
          </div>
          <div className="min-h-0 flex-1">
            <SuperAgentFlowCanvas
              runId={run.run_id || 'draft'}
              run={run}
              classification={classification}
              reviewPlusTask={reviewPlusTask}
              workflowGraph={viewModel.workflowGraph}
              flowGraph={viewModel.flowGraph}
              initialExpandedTeamLeadIds={viewModel.initialExpandedTeamLeadIds}
              processItems={viewModel.processItems}
              activeNodeId={activeNodeId}
              selectedNodeId={selectedNodeId}
              detailOpen={detailOpen}
              onSelectNode={(nodeId) => {
                const normalizedNodeId = normalizeSuperAgentCanvasNodeId(nodeId)
                setSelectedNodeId(normalizedNodeId)
                setDetailOpen(true)
              }}
              onCloseDetail={() => setDetailOpen(false)}
              pauseContext={pauseContext}
            />
          </div>
        </section>
      </div>

      {run.execution_metrics_snapshot?.quality_scores && run.status !== 'running' ? (
        <details className="mt-3 shrink-0 rounded-xl border border-border/15 bg-background p-4">
          <summary className="cursor-pointer text-[11px] font-medium text-primary">
            质量评分与调度诊断（技术细节）
          </summary>
          <div className="mt-3 space-y-3">
            <ExecutionMetricsPanel
              snapshot={run.execution_metrics_snapshot}
              qualityReport={run.quality_report}
              testId="super-agent-processing-execution-metrics"
            />
            <SmartCommitteeDiagnosticsCard
              run={run}
              classification={classification ?? undefined}
              testId="super-agent-processing-smart-diagnostics"
            />
          </div>
        </details>
      ) : run.status !== 'running' ? (
        <details className="mt-3 shrink-0 rounded-xl border border-border/15 bg-background p-4">
          <summary className="cursor-pointer text-[11px] font-medium text-primary">
            调度诊断（技术细节）
          </summary>
          <div className="mt-3">
            <SmartCommitteeDiagnosticsCard
              run={run}
              classification={classification ?? undefined}
              testId="super-agent-processing-smart-diagnostics"
            />
          </div>
        </details>
      ) : null}

    </div>
  )
}
