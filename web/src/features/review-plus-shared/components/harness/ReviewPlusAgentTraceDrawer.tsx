'use client'

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useIsMobile } from '@aqua/ui-core'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-shared/types'
import {
  buildAgentTraceDetailSections,
  formatAgentIdLabel,
  getOrderedHarnessTraceAgentIds,
  getDelegatedSpecialists,
} from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'
import { formatElapsedMs } from '@/lib/aeroTerminology'
import { cn } from '@/lib/utils'

const COMPACT_LAYOUT_MEDIA_QUERY = '(max-width: 1279px)'

interface Props {
  task: ReviewPlusTaskDetail
  agentId: string
  open: boolean
  onClose: () => void
  onSelectAgentId?: (agentId: string) => void
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h4 className="text-[10px] font-medium text-muted">{title}</h4>
      <div className="rounded-lg border border-border/20 bg-background px-3 py-2 text-[10px] leading-relaxed text-primary/85">
        {children}
      </div>
    </section>
  )
}

export default function ReviewPlusAgentTraceDrawer({
  task,
  agentId,
  open,
  onClose,
  onSelectAgentId,
}: Props) {
  const [mounted, setMounted] = useState(false)
  const isMobile = useIsMobile()
  const [isCompactLayout, setIsCompactLayout] = useState(false)

  useEffect(() => { setMounted(true) }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mediaQuery = window.matchMedia(COMPACT_LAYOUT_MEDIA_QUERY)
    const update = () => setIsCompactLayout(mediaQuery.matches)
    update()
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', update)
      return () => mediaQuery.removeEventListener('change', update)
    }
    mediaQuery.addListener(update)
    return () => mediaQuery.removeListener(update)
  }, [])

  const agentIds = useMemo(() => getOrderedHarnessTraceAgentIds(task), [task])
  const detail = useMemo(() => buildAgentTraceDetailSections(task, agentId), [task, agentId])
  const delegated = useMemo(() => getDelegatedSpecialists(task, agentId), [task, agentId])
  const runIndex = agentIds.indexOf(agentId)
  const hasPrev = runIndex > 0
  const hasNext = runIndex >= 0 && runIndex < agentIds.length - 1
  const shouldUseBottomDrawer = isMobile || isCompactLayout

  if (!mounted || !open || !agentId) return null

  const trace = detail.trace
  const statusOk = trace?.status === 'completed'

  const drawerPanel = (
    <div
      className={cn(
        'flex flex-col bg-surface/95 shadow-2xl backdrop-blur-xl',
        shouldUseBottomDrawer
          ? 'fixed inset-x-0 bottom-0 top-[max(5rem,env(safe-area-inset-top)+3.5rem)] z-[10010] rounded-t-3xl border-t border-border/15'
          : 'fixed inset-y-0 right-0 z-[10020] w-[400px] max-w-[48%] border-l border-border/15',
      )}
      data-testid="review-plus-agent-trace-drawer"
      role="dialog"
      aria-labelledby="review-plus-trace-drawer-title"
    >
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-border/15 px-4 py-3">
        <div className="min-w-0">
          <h3 id="review-plus-trace-drawer-title" className="text-[13px] font-medium text-primary">
            审查环节详情
          </h3>
          <p className="mt-0.5 truncate text-[10px] text-muted">{detail.label}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {hasPrev && onSelectAgentId ? (
            <button
              type="button"
              onClick={() => onSelectAgentId(agentIds[runIndex - 1]!)}
              className="rounded-lg px-2 py-1 text-[10px] text-muted hover:bg-muted/10"
            >
              上一条
            </button>
          ) : null}
          {hasNext && onSelectAgentId ? (
            <button
              type="button"
              onClick={() => onSelectAgentId(agentIds[runIndex + 1]!)}
              className="rounded-lg px-2 py-1 text-[10px] text-muted hover:bg-muted/10"
            >
              下一条
            </button>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭审查环节详情"
            className="rounded-lg px-2 py-1 text-[11px] text-muted hover:bg-muted/10"
          >
            关闭
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={`rounded-full border px-2 py-0.5 text-[9px] font-medium ${statusOk ? 'border-positive/20 bg-positive/8 text-positive' : 'border-destructive/20 bg-destructive/8 text-destructive'}`}>
            {trace ? (statusOk ? '已完成' : '失败') : '无轨迹'}
          </span>
          {detail.isCore ? (
            <span className="rounded-full border border-primaryAccent/25 bg-primaryAccent/10 px-2 py-0.5 text-[9px] text-primaryAccent">
              核心环节
            </span>
          ) : null}
          {typeof trace?.elapsed_ms === 'number' ? (
            <span className="text-[9px] tabular-nums text-muted">{formatElapsedMs(trace.elapsed_ms)}</span>
          ) : null}
        </div>

        {detail.selectionReason ? (
          <DetailSection title="选中原因">
            <p>{detail.selectionReason}</p>
          </DetailSection>
        ) : null}

        {detail.signals.length > 0 ? (
          <DetailSection title="匹配信号">
            <div className="flex flex-wrap gap-1">
              {detail.signals.map((sig) => (
                <span key={sig} className="rounded-full border border-border/20 px-1.5 py-0.5 text-[9px] text-muted">
                  {sig}
                </span>
              ))}
            </div>
          </DetailSection>
        ) : null}

        {delegated.length > 0 ? (
          <DetailSection title="总师委派专家 (Delegate Specialists)">
            <ul className="space-y-2.5">
              {delegated.map((spec) => (
                <li key={spec.agent_id} className="rounded-md border border-border/10 bg-background/40 p-2 text-[10px] leading-relaxed text-primary/80">
                  <div className="flex flex-wrap items-center gap-1.5 mb-1">
                    <span className="font-semibold text-primary">
                      {spec.agent_name}
                    </span>
                    {spec.required ? (
                      <span className="rounded bg-muted/15 px-1.5 py-0.2 text-[8px] text-muted">
                        必选
                      </span>
                    ) : (
                      <span className="rounded border border-primaryAccent/15 bg-primaryAccent/5 px-1.5 py-0.2 text-[8px] text-primaryAccent font-medium">
                        动态组队
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-muted text-[9px]">
                    <span className="font-semibold text-primary/70">专业职责：</span>{spec.role}
                  </p>
                  {spec.reason ? (
                    <p className="mt-0.5 text-muted/80 text-[9px]">
                      <span className="font-semibold text-primary/70">决策理由：</span>{spec.reason}
                    </p>
                  ) : null}
                  {spec.matched_signals?.length > 0 ? (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {spec.matched_signals.map((sig) => (
                        <span
                          key={`${spec.agent_id}-${sig}`}
                          className="rounded bg-muted/5 border border-border/10 px-1.5 py-0.2 text-[8px] text-muted/80"
                        >
                          {sig}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </DetailSection>
        ) : null}

        {trace?.error_message || trace?.error_code ? (
          <DetailSection title="失败信息">
            <p className="text-destructive">
              {[trace.error_code, trace.error_message].filter(Boolean).join('：')}
            </p>
          </DetailSection>
        ) : null}

        {detail.inputLines.length > 0 ? (
          <DetailSection title="输入摘要">
            <ul className="space-y-0.5">
              {detail.inputLines.map((line, i) => (
                <li key={`in-${i}`}>{line}</li>
              ))}
            </ul>
          </DetailSection>
        ) : null}

        {detail.outputLines.length > 0 ? (
          <DetailSection title="输出摘要">
            <ul className="space-y-0.5">
              {[...new Set(detail.outputLines)].map((line, i) => (
                <li key={`out-${i}`}>{line}</li>
              ))}
            </ul>
          </DetailSection>
        ) : null}

        {!trace ? (
          <p className="text-[10px] text-muted">
            未找到 {formatAgentIdLabel(agentId)} 的执行轨迹，可能尚未运行或已被重试替换。
          </p>
        ) : null}
      </div>
    </div>
  )

  if (shouldUseBottomDrawer) {
    return createPortal(
      <>
        <button
          type="button"
          aria-label="关闭审查环节详情"
          onClick={onClose}
          className="fixed inset-0 z-[10009] bg-black/20 backdrop-blur-[1px]"
        />
        {drawerPanel}
      </>,
      document.body,
    )
  }

  return createPortal(drawerPanel, document.body)
}
