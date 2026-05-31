/**
 * 通用工作流可视化类型定义
 *
 * 这些类型由后端 WorkflowGraph 结构驱动，适用于任意工作流的 DAG 可视化。
 * 前端不应硬编码任何特定工作流拓扑，所有类型定义应保持通用。
 */

export type WorkflowStepStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'awaiting_confirm'
  | 'blocked'
  | 'skipped'
  | 'failed'
  | 'interrupted'

export interface WorkflowGraphNode {
  node_id: string
  step_key: string
  label: string
  subtitle?: string
  node_type: string
  layout_hint?: string
  icon?: string
  parent_node_id?: string
  status: WorkflowStepStatus
  agent_ids: string[]
  agent_run_ids: string[]
  started_at?: string | null
  completed_at?: string | null
  blocked_reason: string
  output_summary?: string
}

export interface WorkflowGraphEdge {
  edge_id: string
  source: string
  target: string
}

export interface WorkflowGraph {
  title?: string
  description?: string
  nodes: WorkflowGraphNode[]
  edges: WorkflowGraphEdge[]
}

export const STEP_STATUS_LABELS: Record<WorkflowStepStatus, string> = {
  pending: '待执行',
  running: '运行中',
  completed: '已完成',
  awaiting_confirm: '待确认',
  blocked: '未放行',
  skipped: '已跳过',
  failed: '已失败',
  interrupted: '已中断',
}

export const STEP_STATUS_COLORS: Record<WorkflowStepStatus, string> = {
  pending: 'bg-surface text-muted',
  running: 'bg-blue-50 text-blue-600',
  completed: 'bg-emerald-50 text-emerald-600',
  awaiting_confirm: 'bg-amber-50 text-amber-600',
  blocked: 'bg-red-50 text-red-600',
  skipped: 'bg-surface/60 text-muted/80',
  failed: 'bg-red-100 text-red-700',
  interrupted: 'bg-amber-50 text-amber-600',
}
