import {
  formatDurationMs,
  resolveGncStepLabel,
  type GncFlowStepProjection,
} from '@/features/unified-review-workbench/constants/gncWorkflowSteps'
import type { UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export interface GncFlowStepDetailModel {
  stepKey: string
  label: string
  status: string
  statusLabel: string
  durationLabel: string
  relatedTab: UnifiedWorkbenchTabKey
  relatedTabLabel: string
  error?: string
  summary?: string
  metricsLines: string[]
  stepIndex: number
  isCurrent: boolean
}

const TAB_LABELS: Partial<Record<UnifiedWorkbenchTabKey, string>> = {
  overview: '总览',
  evidences: '证据',
  committee: '委员会',
  rid: 'RID',
  decision: '总师裁定',
  arbitration: '人工仲裁',
  minutes: '纪要',
  report: '报告',
  flow: '流程',
}

function statusLabel(status: string): string {
  if (status === 'completed') return '已完成'
  if (status === 'running') return '进行中'
  if (status === 'failed') return '失败'
  return '待执行'
}

function formatMetricLine(key: string, value: unknown): string {
  if (value == null || value === '') return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return `${key}: ${String(value)}`
  }
  if (Array.isArray(value)) return `${key}: ${value.length} 项`
  if (typeof value === 'object') return `${key}: ${Object.keys(value as object).length} 字段`
  return ''
}

export function canOpenRelatedTab(
  tab: UnifiedWorkbenchTabKey,
  visibleTabs: readonly string[],
): boolean {
  if (tab === 'overview' || tab === 'flow') return false
  return visibleTabs.includes(tab)
}

export function resolveGncFlowStepRelatedTab(step: GncFlowStepProjection): UnifiedWorkbenchTabKey {
  const tab = String(step.related_tab || 'overview').trim() as UnifiedWorkbenchTabKey
  return tab || 'overview'
}

export function buildGncFlowStepDetail(
  step: GncFlowStepProjection,
  index: number,
): GncFlowStepDetailModel {
  const stepKey = String(step.step_key || '')
  const status = String(step.status || 'pending')
  const relatedTab = resolveGncFlowStepRelatedTab(step)
  const metrics = step.metrics && typeof step.metrics === 'object' && !Array.isArray(step.metrics)
    ? step.metrics as Record<string, unknown>
    : {}
  const metricsLines = Object.entries(metrics)
    .map(([key, value]) => formatMetricLine(key, value))
    .filter(Boolean)
  const summary = String(step.summary || step.subtitle || '').trim() || undefined

  return {
    stepKey,
    label: String(step.label || resolveGncStepLabel(stepKey)),
    status,
    statusLabel: statusLabel(status),
    durationLabel: formatDurationMs(step.duration_ms),
    relatedTab,
    relatedTabLabel: TAB_LABELS[relatedTab] || relatedTab,
    error: String(step.error || '').trim() || undefined,
    summary,
    metricsLines,
    stepIndex: index,
    isCurrent: Boolean(step.is_current || status === 'running'),
  }
}
