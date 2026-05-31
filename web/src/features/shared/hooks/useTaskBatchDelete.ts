'use client'

import { useCallback, useMemo, useState } from 'react'

export function isDirectDeletableStatus(status: string, directStatuses: readonly string[]) {
  return directStatuses.includes(status)
}

export function useTaskBatchDelete<T>({
  tasks,
  getTaskId,
  getTaskStatus,
  directDeleteStatuses,
  deleteTask,
  closeTabsForTaskId,
  onRefresh,
  taskLabel = '任务',
}: {
  tasks: T[]
  getTaskId: (task: T) => string
  getTaskStatus: (task: T) => string
  directDeleteStatuses: readonly string[]
  deleteTask: (task: T, force: boolean) => Promise<void>
  closeTabsForTaskId: (taskId: string) => void
  onRefresh: () => Promise<void>
  taskLabel?: string
}) {
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [includeProtectedDelete, setIncludeProtectedDelete] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)

  const allTaskIds = useMemo(() => tasks.map(getTaskId), [tasks, getTaskId])
  const allSelected = allTaskIds.length > 0 && allTaskIds.every((id) => selectedIds.includes(id))

  const selectedTasks = useMemo(
    () => tasks.filter((task) => selectedIds.includes(getTaskId(task))),
    [tasks, selectedIds, getTaskId],
  )

  const selectedSafeCount = useMemo(
    () => selectedTasks.filter((task) => isDirectDeletableStatus(getTaskStatus(task), directDeleteStatuses)).length,
    [selectedTasks, getTaskStatus, directDeleteStatuses],
  )
  const selectedProtectedCount = selectedTasks.length - selectedSafeCount

  const selectionSummary = useMemo(() => {
    if (selectedIds.length === 0) return `勾选${taskLabel}后可批量删除`
    if (selectedProtectedCount === 0) return `已选 ${selectedIds.length} 项，可直接删除`
    if (selectedSafeCount === 0) {
      return includeProtectedDelete
        ? `已选 ${selectedIds.length} 项，将按彻底删除处理`
        : `已选 ${selectedIds.length} 项，均为执行中任务`
    }
    return includeProtectedDelete
      ? `已选 ${selectedIds.length} 项，其中 ${selectedProtectedCount} 项将彻底删除`
      : `已选 ${selectedIds.length} 项，执行中任务未勾选时将跳过`
  }, [includeProtectedDelete, selectedIds.length, selectedProtectedCount, selectedSafeCount, taskLabel])

  const batchActionLabel = useMemo(() => {
    if (batchDeleting) return '删除中...'
    if (selectedIds.length === 0) return '删除所选'
    if (selectedProtectedCount > 0 && includeProtectedDelete) return `彻底删除 (${selectedIds.length})`
    if (selectedSafeCount > 0) return `删除所选 (${selectedSafeCount})`
    return '删除所选'
  }, [batchDeleting, includeProtectedDelete, selectedIds.length, selectedProtectedCount, selectedSafeCount])

  const toggleSelect = useCallback((taskId: string) => {
    setSelectedIds((prev) => (
      prev.includes(taskId) ? prev.filter((id) => id !== taskId) : [...prev, taskId]
    ))
  }, [])

  const toggleSelectAll = useCallback(() => {
    setSelectedIds(allSelected ? [] : allTaskIds)
  }, [allSelected, allTaskIds])

  const clearSelection = useCallback(() => {
    setSelectedIds([])
  }, [])

  const handleBatchDelete = useCallback(async () => {
    const safeTasks = selectedTasks.filter((task) =>
      isDirectDeletableStatus(getTaskStatus(task), directDeleteStatuses),
    )
    const blockedTasks = selectedTasks.filter((task) =>
      !isDirectDeletableStatus(getTaskStatus(task), directDeleteStatuses),
    )
    const targetTasks = [...safeTasks, ...(includeProtectedDelete ? blockedTasks : [])]

    if (targetTasks.length === 0) {
      window.alert(
        blockedTasks.length > 0
          ? '所选任务均处于执行中。请勾选「含执行中任务也彻底删除」后再试。'
          : '请先选择要删除的任务。',
      )
      return
    }

    const confirmed = window.confirm(
      `确认批量删除 ${targetTasks.length} 个${taskLabel}吗？${blockedTasks.length > 0 && !includeProtectedDelete ? `其中 ${blockedTasks.length} 个执行中任务将跳过。` : ''}${includeProtectedDelete && blockedTasks.length > 0 ? ' 执行中任务将彻底删除。' : ''}此操作不可恢复。`,
    )
    if (!confirmed) return

    setBatchDeleting(true)
    let success = 0
    let failed = 0

    for (const task of targetTasks) {
      const force = !isDirectDeletableStatus(getTaskStatus(task), directDeleteStatuses)
      try {
        await deleteTask(task, force)
        closeTabsForTaskId(getTaskId(task))
        success += 1
      } catch (error) {
        failed += 1
        console.error('[TaskBatchDelete] 删除失败:', getTaskId(task), error)
      }
    }

    setSelectedIds([])
    await onRefresh()
    setBatchDeleting(false)

    const skipped = includeProtectedDelete ? 0 : blockedTasks.length
    window.alert(
      failed > 0
        ? `批量删除完成：成功 ${success} 个，失败 ${failed} 个${skipped > 0 ? `，跳过 ${skipped} 个` : ''}。`
        : `已删除 ${success} 个${taskLabel}${skipped > 0 ? `，跳过 ${skipped} 个执行中任务` : ''}。`,
    )
  }, [
    closeTabsForTaskId,
    deleteTask,
    directDeleteStatuses,
    getTaskId,
    getTaskStatus,
    includeProtectedDelete,
    onRefresh,
    selectedTasks,
    taskLabel,
  ])

  return {
    selectedIds,
    includeProtectedDelete,
    setIncludeProtectedDelete,
    batchDeleting,
    allSelected,
    selectionSummary,
    batchActionLabel,
    toggleSelect,
    toggleSelectAll,
    clearSelection,
    handleBatchDelete,
    isSelected: (id: string) => selectedIds.includes(id),
    hasSelection: selectedIds.length > 0,
  }
}
