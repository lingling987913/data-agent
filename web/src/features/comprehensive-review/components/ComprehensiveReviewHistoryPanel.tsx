'use client'

import Link from 'next/link'
import { ArrowUpRight, Loader2, Plus, RefreshCw } from 'lucide-react'
import type { SuperAgentRun } from '@/features/super-agent/types'
import { TaskRowDeleteButton } from '@/features/shared/components/TaskRowDeleteButton'
import { buildSuperAgentRunUrl } from '@/features/super-agent/utils/superAgentWizardRecovery'
import { AGENT_RUN_STATUS_LABELS, ROUTE_LABELS } from '@/lib/aeroTerminology'
import { cn } from '@/lib/utils'

function relativeTime(isoStr: string): string {
  if (!isoStr) return ''
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return new Date(isoStr).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

function statusTone(status: string): string {
  if (status === 'completed') return 'border-positive/25 bg-positive/10 text-positive'
  if (status === 'limited') return 'border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]'
  if (status === 'failed') return 'border-destructive/25 bg-destructive/10 text-destructive'
  if (status === 'interrupted') return 'border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]'
  if (status === 'running') return 'border-primaryAccent/25 bg-primaryAccent/10 text-primaryAccent'
  return 'border-border/20 bg-surface text-muted'
}

function statusDot(status: string): string {
  if (status === 'completed') return 'bg-positive'
  if (status === 'failed') return 'bg-destructive'
  if (status === 'limited' || status === 'interrupted') return 'bg-[rgb(var(--color-sa-gold))]'
  if (status === 'running') return 'bg-primaryAccent'
  return 'bg-muted/50'
}

interface Props {
  runs: SuperAgentRun[]
  selectedRunId: string
  loading: boolean
  refreshing: boolean
  deletingRunId?: string
  creatingTask?: boolean
  onSelect: (run: SuperAgentRun) => void
  onDelete: (run: SuperAgentRun) => void
  onRefresh: () => void
  onNewTask: () => void
}

function HistoryRunRow({
  run,
  selected,
  deleting,
  onSelect,
  onDelete,
}: {
  run: SuperAgentRun
  selected: boolean
  deleting: boolean
  onSelect: (run: SuperAgentRun) => void
  onDelete: (run: SuperAgentRun) => void
}) {
  const route = run.route_decision?.route || run.requested_route
  const displayName = run.name || run.run_id
  return (
    <div
      aria-current={selected ? 'true' : undefined}
      className={cn(
        'relative flex items-start gap-1 rounded-xl border transition',
        selected
          ? 'z-[1] border-primaryAccent/55 border-l-[3px] border-l-primaryAccent bg-primaryAccent/10 shadow-soft ring-1 ring-primaryAccent/30'
          : 'border-border/15 bg-background shadow-soft hover:border-primaryAccent/25 hover:bg-background-secondary/40',
      )}
    >
      <button
        type="button"
        onClick={() => onSelect(run)}
        aria-label={selected ? `${displayName}（当前任务）` : displayName}
        className="min-w-0 flex-1 px-3 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 shrink-0 rounded-full ${statusDot(run.status)}`} />
          <span
            className={cn(
              'min-w-0 flex-1 truncate text-[12px]',
              selected ? 'font-semibold text-primaryAccent' : 'font-medium text-primary',
            )}
          >
            {displayName}
          </span>
          {selected ? (
            <span className="shrink-0 rounded-full border border-primaryAccent/30 bg-primaryAccent/15 px-1.5 py-0.5 text-[9px] font-medium text-primaryAccent">
              当前
            </span>
          ) : null}
          <span className="shrink-0 text-[10px] text-muted/45">{relativeTime(run.updated_at || run.created_at)}</span>
        </div>
        <p className="mt-1.5 line-clamp-2 text-[10px] leading-relaxed text-muted">{run.objective || '未填写审查目标'}</p>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
          <span className={`rounded-full border px-2 py-0.5 ${statusTone(run.status)}`}>
            {AGENT_RUN_STATUS_LABELS[run.status] || run.status}
          </span>
          <span className="rounded-full border border-border/15 bg-surface px-2 py-0.5 text-muted">
            {ROUTE_LABELS[route] || route}
          </span>
        </div>
      </button>
      <div className="flex shrink-0 flex-col items-center gap-0.5 py-2 pr-2">
        <Link
          href={buildSuperAgentRunUrl(run.run_id)}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => event.stopPropagation()}
          title="在智能审查中查看详情"
          className="inline-flex h-8 items-center gap-0.5 rounded-lg px-1.5 text-[10px] font-medium text-primaryAccent transition-colors hover:bg-primaryAccent/10 hover:underline"
        >
          详情
          <ArrowUpRight className="h-3 w-3 shrink-0" aria-hidden />
        </Link>
        <TaskRowDeleteButton deleting={deleting} onDelete={() => onDelete(run)} />
      </div>
    </div>
  )
}

export default function ComprehensiveReviewHistoryPanel({
  runs,
  selectedRunId,
  loading,
  refreshing,
  deletingRunId = '',
  creatingTask = false,
  onSelect,
  onDelete,
  onRefresh,
  onNewTask,
}: Props) {
  return (
    <aside className="flex min-h-[620px] flex-col rounded-2xl border border-border/15 bg-surface shadow-soft lg:sticky lg:top-5 lg:max-h-[calc(100vh-96px)]">
      <div className="border-b border-border/15 px-4 py-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-primary">历史任务</h2>
            <p className="mt-1 text-[10px] leading-relaxed text-muted">包含综合审查与智能审查任务，切换页面后可在此恢复或删除。</p>
          </div>
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border/15 bg-background text-primary hover:bg-background-secondary disabled:opacity-60"
              title="刷新列表"
            >
              {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
            </button>
            <button
              type="button"
              onClick={onNewTask}
              disabled={creatingTask}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-primaryAccent/20 bg-primaryAccent/10 text-primaryAccent hover:bg-primaryAccent/15 disabled:cursor-not-allowed disabled:opacity-60"
              title="新建任务"
            >
              {creatingTask ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Plus className="h-3.5 w-3.5" aria-hidden />}
            </button>
          </div>
        </div>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-[12px] text-muted">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            加载历史任务...
          </div>
        ) : runs.length ? (
          runs.map((run) => (
            <HistoryRunRow
              key={run.run_id}
              run={run}
              selected={run.run_id === selectedRunId}
              deleting={deletingRunId === run.run_id}
              onSelect={onSelect}
              onDelete={onDelete}
            />
          ))
        ) : (
          <div className="rounded-xl border border-dashed border-border/20 bg-background/70 px-4 py-8 text-center">
            <p className="text-[12px] font-medium text-primary">暂无历史任务</p>
            <p className="mt-1 text-[10px] text-muted">发起审查任务后会出现在这里。</p>
          </div>
        )}
      </div>
    </aside>
  )
}
