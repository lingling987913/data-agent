'use client'

import { Loader2, Trash2, X } from 'lucide-react'
import { AGENT_RUN_STATUS_LABELS } from '@/lib/aeroTerminology'
import type { SuperAgentRun } from '@/features/super-agent/types'

interface Props {
  run: SuperAgentRun | null
  open: boolean
  deleting?: boolean
  onCancel: () => void
  onConfirm: (force: boolean) => void
}

export default function DeleteTaskConfirmDialog({
  run,
  open,
  deleting = false,
  onCancel,
  onConfirm,
}: Props) {
  if (!open || !run) return null

  const isRunning = run.status === 'running'
  const statusLabel = AGENT_RUN_STATUS_LABELS[run.status] || run.status

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-task-title"
        className="w-full max-w-md rounded-2xl border border-border/20 bg-background shadow-soft"
      >
        <div className="flex items-start justify-between border-b border-border/15 px-5 py-4">
          <div>
            <h3 id="delete-task-title" className="text-sm font-semibold text-primary">删除任务</h3>
            <p className="mt-1 text-[11px] leading-relaxed text-muted">
              将同时删除综合审查与智能审查中的该任务及关联数据，不可恢复。
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={deleting}
            className="rounded-lg p-1 text-muted hover:bg-surface hover:text-primary disabled:opacity-50"
            aria-label="关闭"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <div className="space-y-3 px-5 py-4">
          <div className="rounded-xl border border-border/15 bg-surface px-3 py-3">
            <div className="truncate text-[13px] font-medium text-primary">{run.name || run.run_id}</div>
            <div className="mt-1 font-mono text-[10px] text-muted">{run.run_id}</div>
            <div className="mt-2 inline-flex rounded-full border border-border/15 bg-background px-2 py-0.5 text-[10px] text-muted">
              状态：{statusLabel}
            </div>
          </div>
          {isRunning ? (
            <p className="text-[12px] leading-relaxed text-[rgb(var(--color-sa-gold))]">
              该任务正在执行中。确认删除将强制停止并清理本地存储的所有关联数据。
            </p>
          ) : (
            <p className="text-[12px] leading-relaxed text-muted">
              删除后，左侧历史列表与智能审查页面的同一 runid 深链都将失效。
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-border/15 px-5 py-4">
          <button
            type="button"
            onClick={onCancel}
            disabled={deleting}
            className="rounded-lg border border-border/20 bg-background px-4 py-2 text-[12px] font-medium text-primary hover:bg-surface disabled:opacity-60"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => onConfirm(isRunning)}
            disabled={deleting}
            className="inline-flex items-center gap-2 rounded-lg bg-destructive px-4 py-2 text-[12px] font-medium text-white hover:opacity-95 disabled:opacity-60"
          >
            {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Trash2 className="h-3.5 w-3.5" aria-hidden />}
            {isRunning ? '强制删除' : '确认删除'}
          </button>
        </div>
      </div>
    </div>
  )
}
