'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Eye, X } from 'lucide-react'
import { toast } from 'sonner'
import { useIsMobile } from '@aqua/ui-core'
import {
  confirmReviewPlusTraceLink,
  rejectReviewPlusTraceLink,
} from '@/features/review-plus-v2/api'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { MATERIAL_ROLE_LABELS } from '@/features/review-plus-v2/types'
import {
  findMatchingTraceLink,
  type WorkbenchSelection,
} from '@/features/review-plus-v2/utils/aeroDesignerWorkbenchUtils'

interface ReviewPlusEvidenceCompareOverlayProps {
  task: ReviewPlusTaskDetail
  reviewId: string
  selection: WorkbenchSelection
  onClose: () => void
  onRefresh: () => void | Promise<void>
}

function scrollToHighlight(viewport: 'left' | 'right', lineNo: number) {
  window.setTimeout(() => {
    const el = document.getElementById(`evidence-line-${viewport}-${lineNo}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, 120)
}

function resolveOverlayTitle(selection: WorkbenchSelection): string {
  switch (selection.source) {
    case 'coverage':
      return `覆盖矩阵 · ${selection.checkItemId || '检查项'}`
    case 'finding':
      return `审查记录 · ${selection.findingId || '条目'}`
    case 'traceability':
      return `需求闭环 · ${selection.traceRowId || '追溯项'}`
    case 'cross_doc':
      return `跨文档 · ${selection.crossDocItemId || '问题'}`
    default:
      return '证据原文对照'
  }
}

export default function ReviewPlusEvidenceCompareOverlay({
  task,
  reviewId,
  selection,
  onClose,
  onRefresh,
}: ReviewPlusEvidenceCompareOverlayProps) {
  const isMobile = useIsMobile()
  const [docLeftName, setDocLeftName] = useState('')
  const [docRightName, setDocRightName] = useState('')
  const [mobilePane, setMobilePane] = useState<'left' | 'right'>('left')
  const [hitlCollapsed, setHitlCollapsed] = useState(false)
  const [hitlRationale, setHitlRationale] = useState('')
  const [submittingHitl, setSubmittingHitl] = useState(false)

  useEffect(() => {
    if (!task?.materials?.length) return
    const taskBooks = task.materials.filter((m) => m.role === 'task_book')
    const subjectDocs = task.materials.filter((m) => m.role === 'subject_report' || m.role === 'subject_document')

    const leftHighlight = selection.highlights.find((item) => item.viewport === 'left')
    const rightHighlight = selection.highlights.find((item) => item.viewport === 'right')

    setDocLeftName(leftHighlight?.materialName || taskBooks[0]?.name || task.materials[0].name)
    setDocRightName(
      rightHighlight?.materialName || subjectDocs[0]?.name || task.materials[1]?.name || task.materials[0].name,
    )

    if (leftHighlight) scrollToHighlight('left', leftHighlight.lineNo)
    if (rightHighlight) scrollToHighlight('right', rightHighlight.lineNo)
  }, [selection, task.materials])

  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    },
    [onClose],
  )

  useEffect(() => {
    document.addEventListener('keydown', handleKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.body.style.overflow = ''
    }
  }, [handleKey])

  const leftMaterialContent = useMemo(() => {
    const mat = task.materials.find((m) => m.name === docLeftName)
    return mat?.content || '暂无内容 · 材料尚未成功结构化解析'
  }, [task.materials, docLeftName])

  const rightMaterialContent = useMemo(() => {
    const mat = task.materials.find((m) => m.name === docRightName)
    return mat?.content || '暂无内容 · 材料尚未成功结构化解析'
  }, [task.materials, docRightName])

  const canSubmitHitl = Boolean(selection.pendingTraceLinkId || findMatchingTraceLink(task, selection))
  const showHitl = canSubmitHitl || selection.requiresHumanConfirmation

  const handleHitlConfirm = async () => {
    const matchedLink = selection.pendingTraceLinkId
      ? { link_id: selection.pendingTraceLinkId }
      : findMatchingTraceLink(task, selection)

    if (!matchedLink?.link_id) {
      if (selection.requiresHumanConfirmation) {
        toast.info('该条目需人工复核。当前仅完成证据定位，请先在需求闭环 Tab 处理候选链路。')
      } else {
        toast.info('当前证据点未匹配待确认追溯链路，已完成原文定位。')
      }
      return
    }

    setSubmittingHitl(true)
    try {
      await confirmReviewPlusTraceLink(
        reviewId,
        matchedLink.link_id,
        { rationale: hitlRationale || '设计师人工确认追溯链路自恰闭合' },
      )
      toast.success('追溯链路已确认')
      setHitlRationale('')
      onClose()
      await onRefresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '确认审签失败')
    } finally {
      setSubmittingHitl(false)
    }
  }

  const handleHitlReject = async () => {
    if (!hitlRationale.trim()) {
      toast.error('驳回或标记不满足时，请填写整改建议。')
      return
    }

    const matchedLink = selection.pendingTraceLinkId
      ? { link_id: selection.pendingTraceLinkId }
      : findMatchingTraceLink(task, selection)

    if (!matchedLink?.link_id) {
      toast.info('当前证据点未匹配待确认追溯链路，无法提交驳回。请先在需求闭环 Tab 处理候选链路。')
      return
    }

    setSubmittingHitl(true)
    try {
      await rejectReviewPlusTraceLink(reviewId, matchedLink.link_id, { rationale: hitlRationale })
      toast.success('追溯链路已驳回')
      setHitlRationale('')
      onClose()
      await onRefresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '驳回审签失败')
    } finally {
      setSubmittingHitl(false)
    }
  }

  const renderNumberedLines = (text: string, viewportId: 'left' | 'right', activeMatName: string) => {
    return text.split('\n').map((lineText, index) => {
      const lineNo = index + 1
      const isHighlighted = selection.highlights.some(
        (item) => item.materialName === activeMatName && item.lineNo === lineNo && item.viewport === viewportId,
      )

      return (
        <div
          key={lineNo}
          id={`evidence-line-${viewportId}-${lineNo}`}
          className={`flex items-start border-l-2 py-0.5 font-mono text-[11px] leading-relaxed transition-colors hover:bg-muted/15 ${
            isHighlighted
              ? 'border-warning bg-warning/15 font-medium text-primary'
              : 'border-transparent text-primary/85'
          }`}
        >
          <span className="mr-3 w-10 shrink-0 border-r border-border/10 pr-2 text-right text-[9px] tabular-nums text-muted/40">
            {lineNo}
          </span>
          <span className="flex-1 whitespace-pre-wrap break-all px-1 select-text">
            {lineText || ' '}
          </span>
        </div>
      )
    })
  }

  const renderDocPane = (side: 'left' | 'right') => {
    const docName = side === 'left' ? docLeftName : docRightName
    const setDocName = side === 'left' ? setDocLeftName : setDocRightName
    const content = side === 'left' ? leftMaterialContent : rightMaterialContent

    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 border-b border-border/10 bg-background/50 px-3 py-2">
          <select
            value={docName}
            onChange={(e) => setDocName(e.target.value)}
            className="w-full cursor-pointer truncate border-none bg-transparent text-[11px] font-medium text-primary outline-none"
            aria-label={side === 'left' ? '选择左侧对比文档' : '选择右侧对比文档'}
          >
            {task.materials.map((m) => (
              <option key={m.name} value={m.name}>
                [{MATERIAL_ROLE_LABELS[m.role] || m.role}] {m.name}
              </option>
            ))}
          </select>
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-background-secondary/40 p-2">
          {renderNumberedLines(content, side, docName)}
        </div>
      </div>
    )
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-2 sm:p-4"
      onClick={onClose}
      data-testid="review-plus-evidence-compare-overlay"
    >
      <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" />

      <div
        className="relative flex h-[92vh] w-[95vw] max-w-[1600px] flex-col overflow-hidden rounded-2xl border border-border/20 bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border/15 bg-surface px-4 py-3 sm:px-5">
          <div className="flex min-w-0 items-center gap-2">
            <Eye className="size-4 shrink-0 text-brand" />
            <div className="min-w-0">
              <h2 className="truncate text-[13px] font-medium text-primary">{resolveOverlayTitle(selection)}</h2>
              <p className="text-[10px] text-muted">
                已定位 {selection.highlights.length} 处证据
                {selection.requiresHumanConfirmation ? ' · 待人工确认' : ''}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-xl text-muted transition-colors hover:bg-muted/10 hover:text-primary"
            aria-label="关闭证据对照"
          >
            <X className="size-4" />
          </button>
        </div>

        {selection.quote ? (
          <div className="shrink-0 border-b border-border/10 bg-warning/8 px-4 py-2 sm:px-5">
            <p className="font-mono text-[10px] leading-relaxed text-primary line-clamp-3">{selection.quote}</p>
          </div>
        ) : null}

        {isMobile ? (
          <div className="flex shrink-0 gap-1 border-b border-border/10 px-3 py-2">
            {(['left', 'right'] as const).map((pane) => (
              <button
                key={pane}
                type="button"
                onClick={() => setMobilePane(pane)}
                className={`rounded-xl px-3 py-1.5 text-[10px] font-medium transition-colors ${
                  mobilePane === pane
                    ? 'bg-primaryAccent/10 text-primaryAccent'
                    : 'text-muted hover:bg-muted/10'
                }`}
              >
                {pane === 'left' ? '任务书 / 检查依据' : '被审材料'}
              </button>
            ))}
          </div>
        ) : null}

        <div className={`min-h-0 flex-1 overflow-hidden ${isMobile ? '' : 'flex divide-x divide-border/15'}`}>
          {isMobile ? renderDocPane(mobilePane) : (
            <>
              {renderDocPane('left')}
              {renderDocPane('right')}
            </>
          )}
        </div>

        {showHitl ? (
          <div className="shrink-0 border-t border-border/25 bg-background-secondary/10">
            <button
              type="button"
              onClick={() => setHitlCollapsed((prev) => !prev)}
              className="flex w-full items-center justify-between px-4 py-2 text-[10px] font-medium text-primary"
            >
              <span>人工审签 (HITL)</span>
              {hitlCollapsed ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
            </button>

            {!hitlCollapsed ? (
              <div className="space-y-3 px-4 pb-4">
                <textarea
                  id="evidence-hitl-rationale"
                  value={hitlRationale}
                  onChange={(e) => setHitlRationale(e.target.value)}
                  placeholder="请输入审签依据或整改建议（驳回时必须填写）"
                  rows={2}
                  className="w-full resize-none rounded-lg border border-border/25 bg-background p-2 text-[10px] leading-relaxed text-primary outline-none focus:border-brand/40"
                />

                {!canSubmitHitl ? (
                  <p className="text-[9px] leading-relaxed text-muted">
                    当前仅完成证据定位。若需审签，请先在需求闭环 Tab 处理候选链路，或选择带待确认标记的符合性条目。
                  </p>
                ) : null}

                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void handleHitlReject()}
                    disabled={submittingHitl || !canSubmitHitl}
                    className="flex-1 rounded-lg border border-destructive/25 px-3 py-2 text-[10px] font-medium text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-50"
                  >
                    驳回链路
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleHitlConfirm()}
                    disabled={submittingHitl || !canSubmitHitl}
                    className="flex-1 rounded-lg bg-brand px-3 py-2 text-[10px] font-medium text-white transition-colors hover:bg-brand/90 disabled:opacity-50"
                  >
                    {submittingHitl ? '处理中...' : '确认链路'}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
