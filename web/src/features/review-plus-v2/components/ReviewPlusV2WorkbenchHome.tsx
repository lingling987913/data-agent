'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { GATEKEEPING_TERMS, REVIEW_PLUS_TERMS } from '@/lib/aeroTerminology'
import {
  LoadingState,
  ResponsivePageActions,
  StatusBadge,
  useIsMobile,
} from '@aqua/ui-core'
import type { ResponsiveActionItem } from '@aqua/ui-core'
import { createReviewPlus, deleteReviewPlus, listReviewPlus } from '@/features/review-plus-v2/api'
import type { ReviewPlusTaskSummary } from '@/features/review-plus-v2/types'
import { STATUS_LABELS } from '@/features/review-plus-v2/types'
import { buildReviewPlusV2WorkbenchHref } from '@/features/review-plus-v2/tabNavigation'
import {
  resolveReviewPlusTaskActionHint,
  resolveReviewPlusWorkbenchOpenTab,
} from '@/features/review-plus-v2/utils/reviewPlusUx'
import { reviewPlusTaskStatusTone } from '@/features/review-plus-shared/utils/reviewPlusStatusTone'
import { TaskRowDeleteButton } from '@/features/shared/components/TaskRowDeleteButton'
import { TaskListBatchBar } from '@/features/shared/components/TaskListBatchBar'
import { TaskRowSelectCheckbox } from '@/features/shared/components/TaskRowSelectCheckbox'
import { useTaskBatchDelete } from '@/features/shared/hooks/useTaskBatchDelete'

const RUNNING_STATUSES = ['classifying', 'structuring', 'rule_extracting', 'mapping', 'reviewing', 'reporting', 'traceability_building', 'parsing', 'gatekeeping'] as const
const PREPARING_STATUSES = ['draft', 'materials_uploaded', 'parsed', 'classified', 'scenario_detected', 'ready', 'limited_pass'] as const
const BLOCKED_STATUSES = ['failed', 'blocked'] as const
const DIRECT_DELETE_STATUSES = [...PREPARING_STATUSES, ...BLOCKED_STATUSES, 'completed'] as const

function relativeTime(isoStr: string): string {
  if (!isoStr) return ''
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return new Date(isoStr).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

function taskActionHint(task: ReviewPlusTaskSummary): string {
  return resolveReviewPlusTaskActionHint(task)
}

function statusDotClass(status: string): string {
  if ((RUNNING_STATUSES as readonly string[]).includes(status)) {
    return 'bg-primaryAccent'
  }
  if (status === 'draft') return 'bg-border/50'
  if ((PREPARING_STATUSES as readonly string[]).includes(status)) return 'bg-brand/50'
  if (status === 'failed' || status === 'blocked') return 'bg-warning'
  if (status === 'completed') return 'bg-positive'
  return 'bg-muted/40'
}

function StatInline({ label, value, accent, danger }: { label: string; value: number; accent?: boolean; danger?: boolean }) {
  return (
    <div className="rounded-xl border border-border/10 bg-surface/70 px-3 py-2 sm:border-0 sm:bg-transparent sm:px-0 sm:py-0">
      <div className="flex items-baseline gap-2">
        <span className={`text-base font-medium tabular-nums ${danger ? 'text-destructive' : accent ? 'text-primaryAccent' : 'text-primary'}`}>
          {value}
        </span>
        <span className="text-[10px] text-muted/60">{label}</span>
      </div>
    </div>
  )
}

function TaskRow({
  task,
  onSelect,
  onDelete,
  deleting,
  selected,
  onToggleSelect,
  muted,
  isMobile,
}: {
  task: ReviewPlusTaskSummary
  onSelect: (task: ReviewPlusTaskSummary) => void
  onDelete: (task: ReviewPlusTaskSummary) => void
  deleting?: boolean
  selected?: boolean
  onToggleSelect?: () => void
  muted?: boolean
  isMobile?: boolean
}) {
  const status = String(task.status || 'draft')
  const hint = taskActionHint(task)

  return (
    <div
      className={`group flex items-stretch rounded-xl border border-transparent bg-surface shadow-soft transition-all hover:border-primaryAccent/20 hover:shadow-medium ${muted ? 'opacity-55 hover:opacity-80' : ''} ${selected ? 'border-primaryAccent/20 bg-primaryAccent/5' : ''}`}
      data-testid={`review-plus-v2-task-${task.review_plus_id}`}
    >
      {onToggleSelect ? (
        <TaskRowSelectCheckbox
          checked={Boolean(selected)}
          onToggle={onToggleSelect}
          label={`选择任务 ${task.name}`}
        />
      ) : null}
      <button
        type="button"
        onClick={() => onSelect(task)}
        className="min-w-0 flex-1 px-4 py-3 text-left"
      >
      <div className={`gap-3 ${isMobile ? 'space-y-2' : 'flex items-center'}`}>
        <div className={`flex min-w-0 items-center gap-3 ${isMobile ? '' : 'flex-1'}`}>
          <span className={`size-2 shrink-0 rounded-full ${statusDotClass(status)}`} aria-hidden />
          <span className="min-w-0 truncate text-[12px] font-medium text-primary group-hover:text-primaryAccent">
            {task.name}
          </span>
        </div>
        <div className={`flex items-center gap-2 ${isMobile ? 'justify-between' : 'ml-auto shrink-0'}`}>
          <StatusBadge tone={reviewPlusTaskStatusTone(status)}>
            {STATUS_LABELS[status] || status}
          </StatusBadge>
          <span className={`shrink-0 text-[10px] tabular-nums text-muted/40 ${isMobile ? '' : 'w-16 text-right'}`}>
            {relativeTime(task.updated_at)}
          </span>
        </div>
      </div>
      <p className={`mt-1 text-[10px] text-muted/60 ${isMobile ? '' : 'ml-5'}`}>
        下一步：{hint}
      </p>
      </button>
      <div className="flex shrink-0 items-center border-l border-border/10 px-1">
        <TaskRowDeleteButton deleting={deleting} onDelete={() => onDelete(task)} />
      </div>
    </div>
  )
}

export default function ReviewPlusV2WorkbenchHome() {
  const router = useRouter()
  const isMobile = useIsMobile()

  const [tasks, setTasks] = useState<ReviewPlusTaskSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [listError, setListError] = useState('')

  const fetchTasks = useCallback(async () => {
    try {
      setLoading(true)
      const data = await listReviewPlus({ page: 1, size: 50 })
      setTasks(data.items || [])
      setListError('')
    } catch (err) {
      setListError(err instanceof Error ? err.message : '审查任务列表加载失败')
      setTasks([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchTasks()
  }, [fetchTasks])

  const openTaskByStatus = useCallback((task: ReviewPlusTaskSummary) => {
    const tab = resolveReviewPlusWorkbenchOpenTab(task)
    router.push(buildReviewPlusV2WorkbenchHref(task.review_plus_id, { tab }))
  }, [router])

  const handleDelete = useCallback(async (task: ReviewPlusTaskSummary) => {
    const status = String(task.status || 'draft')
    const canDeleteDirectly = DIRECT_DELETE_STATUSES.includes(status as typeof DIRECT_DELETE_STATUSES[number])
    const confirmed = window.confirm(
      canDeleteDirectly
        ? `确认删除审查任务「${task.name}」吗？此操作将清理任务数据与上传文件，且不可恢复。`
        : `任务「${task.name}」当前正在执行审查流程。是否执行彻底删除？这会强制停止并清理本地存储。`,
    )
    if (!confirmed) return
    try {
      setDeletingId(task.review_plus_id)
      await deleteReviewPlus(task.review_plus_id, { force: !canDeleteDirectly })
      await fetchTasks()
    } catch (error) {
      console.error('[ReviewPlusV2Home] 删除任务失败:', error)
      const message = error instanceof Error ? error.message : '删除失败，请稍后重试。'
      window.alert(message.startsWith('API error') ? `删除失败：${message}` : message)
    } finally {
      setDeletingId(null)
    }
  }, [fetchTasks])

  const closeTabsForTaskId = useCallback((_taskId: string) => {
    // URL 驱动导航，无需关闭 Tab
  }, [])

  const batchDelete = useTaskBatchDelete({
    tasks,
    getTaskId: (task) => task.review_plus_id,
    getTaskStatus: (task) => String(task.status || 'draft'),
    directDeleteStatuses: DIRECT_DELETE_STATUSES,
    deleteTask: async (task, force) => {
      await deleteReviewPlus(task.review_plus_id, { force })
    },
    closeTabsForTaskId,
    onRefresh: fetchTasks,
    taskLabel: '审查任务',
  })

  const handleCreate = useCallback(async (nameOverride?: string) => {
    const name = (nameOverride ?? newName).trim()
    if (!name) return
    try {
      setCreating(true)
      const task = await createReviewPlus({ name })
      setNewName('')
      await fetchTasks()
      router.push(buildReviewPlusV2WorkbenchHref(task.review_plus_id, { tab: 'materials' }))
    } catch (error) {
      console.error('[ReviewPlusV2Home] 创建任务失败:', error)
    } finally {
      setCreating(false)
    }
  }, [fetchTasks, newName, router])

  const activeTasks = tasks.filter((t) => (RUNNING_STATUSES as readonly string[]).includes(String(t.status || '')))
  const blockedCount = tasks.filter((t) => (BLOCKED_STATUSES as readonly string[]).includes(String(t.status || ''))).length
  const completedCount = tasks.filter((t) => String(t.status || '') === 'completed').length

  const groups = useMemo(() => {
    const reviewing = tasks.filter((t) =>
      (RUNNING_STATUSES as readonly string[]).includes(String(t.status || '')),
    )
    const preparing = tasks.filter((t) =>
      (PREPARING_STATUSES as readonly string[]).includes(String(t.status || '')),
    )
    const blocked = tasks.filter((t) => (BLOCKED_STATUSES as readonly string[]).includes(String(t.status || '')))
    const closed = tasks.filter((t) => String(t.status || '') === 'completed')
    const knownTaskIds = new Set([...reviewing, ...preparing, ...blocked, ...closed].map((task) => task.review_plus_id))
    const other = tasks.filter((task) => !knownTaskIds.has(task.review_plus_id))
    const result: Array<{ key: string; label: string; dot: string; items: ReviewPlusTaskSummary[]; muted?: boolean }> = []
    if (reviewing.length) result.push({ key: 'reviewing', label: '审查中', dot: 'bg-primaryAccent', items: reviewing })
    if (preparing.length) result.push({ key: 'preparing', label: '准备中', dot: 'bg-brand/50', items: preparing })
    if (blocked.length) result.push({ key: 'blocked', label: '需处理', dot: 'bg-warning', items: blocked })
    if (closed.length) result.push({ key: 'closed', label: '已完成', dot: 'bg-muted/30', items: closed, muted: true })
    if (other.length) result.push({ key: 'other', label: '其他状态', dot: 'bg-muted/40', items: other })
    return result
  }, [tasks])

  const defaultName = `${REVIEW_PLUS_TERMS.defaultName} ${new Date().toLocaleDateString('zh-CN')}`

  const primaryAction = useMemo<ResponsiveActionItem>(() => ({
    key: 'create-review-plus-v2',
    label: creating ? '创建中...' : '+ 新建审查',
    onClick: () => {
      const name = newName.trim() || defaultName
      void handleCreate(name)
    },
    disabled: creating,
  }), [creating, defaultName, handleCreate, newName])

  const secondaryActions = useMemo<ResponsiveActionItem[]>(() => [{
    key: 'refresh',
    label: loading ? '刷新中...' : '刷新列表',
    onClick: fetchTasks,
    disabled: loading,
  }], [fetchTasks, loading])

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-3 py-4 sm:px-6 sm:py-5">
        <div className={`gap-4 ${isMobile ? 'space-y-4' : 'flex items-start justify-between'}`}>
          <div className="min-w-0">
            <h1 className="text-lg font-medium text-primary">{REVIEW_PLUS_TERMS.workbench}</h1>
            <p className="mt-1 max-w-xl text-[11px] leading-relaxed text-muted">
              上传文件组送审包，完成齐套性准入、符合性审查与追溯闭环。
            </p>
          </div>
          <ResponsivePageActions
            className="shrink-0"
            primaryAction={primaryAction}
            secondaryActions={secondaryActions}
          />
        </div>

        {listError ? (
          <div className="mt-4 rounded-xl border border-destructive/20 bg-destructive/8 px-4 py-3 text-[11px] text-destructive">
            {listError}
          </div>
        ) : null}

        <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border/10 pt-4 sm:flex sm:flex-wrap sm:gap-6">
          <StatInline label="全部任务" value={tasks.length} />
          <StatInline label="进行中" value={activeTasks.length} accent />
          <StatInline label="需处理" value={blockedCount} danger={blockedCount > 0} />
          <StatInline label="已完成" value={completedCount} />
        </div>

        <section className="mt-4 rounded-xl border border-border/20 bg-surface px-4 py-3 shadow-soft">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="min-w-0 flex-1" htmlFor="review-plus-v2-task-name">
              <span className="text-[10px] font-medium text-muted">新建任务</span>
              <input
                id="review-plus-v2-task-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="例如：蓬莱一号飞轮产品保证审查"
                className="mt-1.5 w-full rounded-xl border border-border/30 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-brand/40"
                data-testid="review-plus-v2-create-name"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void handleCreate()
                }}
              />
            </label>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={creating}
                className="inline-flex min-h-9 items-center justify-center rounded-xl bg-brand px-4 text-[11px] font-medium text-white disabled:opacity-50 motion-safe:active:scale-[0.98]"
                data-testid="review-plus-v2-create-submit"
              >
                {creating ? '创建中...' : '创建并进入'}
              </button>
              <button
                type="button"
                onClick={() => void handleCreate(defaultName)}
                disabled={creating}
                className="text-[11px] text-primaryAccent hover:underline disabled:opacity-50"
              >
                使用默认名称
              </button>
            </div>
          </div>
        </section>

        <section className="mt-6">
          {loading ? (
            <LoadingState rows={4} />
          ) : tasks.length === 0 ? (
            <div className="rounded-xl border border-border/20 bg-surface px-6 py-10 text-center shadow-soft">
              <p className="text-sm font-medium text-primary">暂无审查任务</p>
              <p className="mx-auto mt-1.5 max-w-sm text-[11px] leading-relaxed text-muted/70">
                填写任务名称并创建，上传检查需求、检查单、任务书与被审报告后即可启动审查。
              </p>
            </div>
          ) : (
            <div className="space-y-5">
              <TaskListBatchBar
                allSelected={batchDelete.allSelected}
                selectionSummary={batchDelete.selectionSummary}
                batchActionLabel={batchDelete.batchActionLabel}
                batchDeleting={batchDelete.batchDeleting}
                hasSelection={batchDelete.hasSelection}
                includeProtectedDelete={batchDelete.includeProtectedDelete}
                onToggleSelectAll={batchDelete.toggleSelectAll}
                onIncludeProtectedChange={batchDelete.setIncludeProtectedDelete}
                onBatchDelete={() => void batchDelete.handleBatchDelete()}
                forceDeleteLabel="含审查执行任务也彻底删除"
              />
              {groups.map((group) => (
                <div key={group.key}>
                  <div className="mb-2 flex items-center gap-2 px-1">
                    <span className={`size-1.5 rounded-full ${group.dot}`} aria-hidden />
                    <span className="text-[11px] font-medium text-muted/70">{group.label}</span>
                    <span className="text-[10px] text-muted/35">{group.items.length}</span>
                  </div>
                  <div className="space-y-1.5">
                    {group.items.map((task) => (
                      <TaskRow
                        key={task.review_plus_id}
                        task={task}
                        onSelect={openTaskByStatus}
                        onDelete={handleDelete}
                        deleting={deletingId === task.review_plus_id}
                        selected={batchDelete.isSelected(task.review_plus_id)}
                        onToggleSelect={() => batchDelete.toggleSelect(task.review_plus_id)}
                        muted={group.muted}
                        isMobile={isMobile}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
