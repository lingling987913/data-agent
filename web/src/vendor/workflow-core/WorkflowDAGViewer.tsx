'use client'

/**
 * WorkflowDAGViewer — 通用工作流 DAG 可视化组件
 *
 * 基于 @xyflow/react + @dagrejs/dagre，从后端 WorkflowGraph 自动布局并渲染。
 * 支持任意工作流拓扑：串行、并行、fan-out/fan-in、嵌套子流程。
 *
 * ✅ Dagre 自动布局   ✅ 节点类型注册   ✅ 分组框自动生成
 * ✅ Portal 全屏       ✅ ESC 退出       ✅ HITL 控制面板
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { WorkflowGraph, WorkflowStepStatus } from './workflowTypes'
import { STEP_STATUS_LABELS } from './workflowTypes'
import {
    ReactFlow,
    Background,
    Controls,
    MiniMap,
    useNodesState,
    useEdgesState,
    useReactFlow,
    type Node,
    type Edge,
    type NodeTypes,
    type NodeProps,
    MarkerType,
    BackgroundVariant,
    Position,
    Handle,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Graph, layout as dagreLayout } from '@dagrejs/dagre'
import type { GraphLabel } from '@dagrejs/dagre'
import { useIsMobile } from './useIsMobile'

type XYPosition = { x: number; y: number }
type LayoutMode = 'auto' | 'manual'
export type AutoLayoutVariant = 'vertical' | 'compact' | 'horizontal'
export type LayoutVariantPreference = AutoLayoutVariant | 'auto'

const RESPONSIVE_LAYOUT_RATIO = 1.2

/** 根据容器宽高比选择横/纵向 Dagre 布局。 */
export function resolveResponsiveLayoutVariant(
    width: number,
    height: number,
    fallback: AutoLayoutVariant = 'vertical',
): AutoLayoutVariant {
    if (width <= 0 || height <= 0) return fallback
    return width > height * RESPONSIVE_LAYOUT_RATIO ? 'horizontal' : 'vertical'
}

const LAYOUT_STORAGE_PREFIX = 'aq:workflow-dag-layout:'

export function isHorizontalWorkflowLayout(layoutVariant: AutoLayoutVariant): boolean {
    return layoutVariant === 'horizontal'
}

/** 布局方向与节点排列一致：横向走左右 handle，纵向/紧凑走上下 handle。 */
export function resolveWorkflowEdgeHandles(layoutVariant: AutoLayoutVariant): {
    sourceHandle: string
    targetHandle: string
} {
    return isHorizontalWorkflowLayout(layoutVariant)
        ? { sourceHandle: 's-right', targetHandle: 't-left' }
        : { sourceHandle: 's-bottom', targetHandle: 't-top' }
}

/** React Flow 边类型：smoothstep 正交折线，避免跨容器斜线穿越 */
export const WORKFLOW_DAG_EDGE_TYPE = 'smoothstep' as const

const AUTO_LAYOUT_OPTIONS: Record<AutoLayoutVariant, {
    label: string
    graph: GraphLabel
}> = {
    vertical: {
        label: '纵向标准',
        graph: { rankdir: 'TB', nodesep: 40, ranksep: 60, marginx: 40, marginy: 40 } as GraphLabel,
    },
    compact: {
        label: '纵向紧凑',
        graph: { rankdir: 'TB', nodesep: 24, ranksep: 42, marginx: 28, marginy: 28 } as GraphLabel,
    },
    horizontal: {
        label: '横向展开',
        graph: { rankdir: 'LR', nodesep: 34, ranksep: 72, marginx: 40, marginy: 40 } as GraphLabel,
    },
}

function buildLayoutStorageKey(graph: WorkflowGraph, mode: 'blueprint' | 'live') {
    const nodeIds = (graph.nodes || []).map(n => n.node_id).sort().join('|')
    return `${LAYOUT_STORAGE_PREFIX}${mode}:${graph.title || 'workflow'}:${nodeIds}`
}

// ══════════════════════════════════════════
//  状态样式
// ══════════════════════════════════════════

/** 节点样式：优先使用主题 CSS 变量，适配深色/浅色主题 */
const SC: Record<WorkflowStepStatus, { border: string; bg: string; text: string; badge: string; glow: string }> = {
    pending: {
        border: 'rgb(var(--color-border) / 0.45)',
        bg: 'rgb(var(--color-surface))',
        text: 'rgb(var(--color-muted))',
        badge: 'rgb(var(--color-background-secondary))',
        glow: '',
    },
    running: {
        border: 'rgb(var(--color-primary-accent))',
        bg: 'rgb(var(--color-primary-accent) / 0.12)',
        text: 'rgb(var(--color-primary-accent))',
        badge: 'rgb(var(--color-primary-accent) / 0.18)',
        glow: '0 0 14px rgb(var(--color-primary-accent) / 0.25)',
    },
    completed: {
        border: 'rgb(var(--color-positive) / 0.55)',
        bg: 'rgb(var(--color-positive) / 0.12)',
        text: 'rgb(var(--color-positive))',
        badge: 'rgb(var(--color-positive) / 0.18)',
        glow: '',
    },
    awaiting_confirm: {
        border: 'rgb(var(--color-domain-brand) / 0.65)',
        bg: 'rgb(var(--color-domain-brand) / 0.12)',
        text: 'rgb(var(--color-domain-brand))',
        badge: 'rgb(var(--color-domain-brand) / 0.18)',
        glow: '0 0 14px rgb(var(--color-domain-brand) / 0.22)',
    },
    blocked: {
        border: 'rgb(var(--color-destructive) / 0.55)',
        bg: 'rgb(var(--color-destructive) / 0.1)',
        text: 'rgb(var(--color-destructive))',
        badge: 'rgb(var(--color-destructive) / 0.16)',
        glow: '0 0 14px rgb(var(--color-destructive) / 0.18)',
    },
    skipped: {
        border: 'rgb(var(--color-border) / 0.35)',
        bg: 'rgb(var(--color-background-secondary) / 0.6)',
        text: 'rgb(var(--color-muted) / 0.8)',
        badge: 'rgb(var(--color-border) / 0.25)',
        glow: '',
    },
    failed: {
        border: 'rgb(var(--color-destructive))',
        bg: 'rgb(var(--color-destructive) / 0.12)',
        text: 'rgb(var(--color-destructive))',
        badge: 'rgb(var(--color-destructive) / 0.2)',
        glow: '0 0 14px rgb(var(--color-destructive) / 0.2)',
    },
    interrupted: {
        border: 'rgb(var(--color-sa-gold) / 0.55)',
        bg: 'rgb(var(--color-sa-gold) / 0.12)',
        text: 'rgb(var(--color-sa-gold))',
        badge: 'rgb(var(--color-sa-gold) / 0.18)',
        glow: '',
    },
}

// ══════════════════════════════════════════
//  节点渲染器: 流程步骤
// ══════════════════════════════════════════

type StepData = {
    nodeId: string
    label: string
    stepKey: string
    icon: string
    status: WorkflowStepStatus
    index: number
    summary: string
    outputSummary: string
    blockingReason: string
    mode: 'blueprint' | 'live'
    active?: boolean
    onConfirm?: (stepKey: string) => void
    onSelectNode?: (nodeId: string) => void
}

function StepNode({ data }: NodeProps<Node<StepData>>) {
    const c = SC[data.status as WorkflowStepStatus] || SC.pending
    const running = data.status === 'running'
    const awaiting = data.status === 'awaiting_confirm'
    const active = Boolean(data.active)
    return (
        <>
            <Handle id="t-left" type="target" position={Position.Left} className="!opacity-0 !w-2 !h-2" />
            <Handle id="t-top"  type="target" position={Position.Top}  className="!opacity-0 !w-2 !h-2" />
            <div className="select-none" onClick={() => data.onSelectNode?.((data.nodeId as string) || (data.stepKey as string))} style={{
                width: 164, padding: '11px 13px', borderRadius: 12,
                border: `2px solid ${active ? 'rgb(var(--color-domain-brand))' : c.border}`, background: active ? 'rgb(var(--color-domain-brand) / 0.14)' : c.bg,
                boxShadow: active ? '0 0 0 3px rgb(var(--color-domain-brand) / 0.22)' : (c.glow || '0 1px 3px rgb(var(--color-border) / 0.12)'),
                cursor: 'pointer', position: 'relative',
            }}>
                <div style={{
                    position: 'absolute', top: -9, left: -9, width: 21, height: 21,
                    borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 9, fontWeight: 700,
                    background: running ? '#2563eb' : awaiting ? '#d97706' : data.status === 'completed' ? '#059669' :
                        (data.status === 'blocked' || data.status === 'failed') ? '#dc2626' : '#d4d4d8',
                    color: (data.status === 'pending' || data.status === 'skipped') ? '#71717a' : '#fff',
                    border: `2px solid ${c.bg}`,
                }}>{(data.index as number) + 1}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                    <span style={{ fontSize: 15 }}>{data.icon as string}</span>
                    <span style={{ fontSize: 11.5, fontWeight: 600, color: c.text }}>{data.label as string}</span>
                </div>
                {(data.mode === 'live' || data.status !== 'pending') && (
                    <div style={{
                        display: 'inline-block', fontSize: 9, padding: '1px 6px', borderRadius: 20,
                        background: c.badge, color: c.text, fontWeight: 500, marginBottom: 2,
                    }}>{(running || awaiting) && '● '}{STEP_STATUS_LABELS[data.status as WorkflowStepStatus]}</div>
                )}
                <p style={{ fontSize: 9, color: '#78716c', lineHeight: 1.35, margin: '2px 0 0',
                    overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                }}>{data.mode === 'live' && data.outputSummary ? `↳ ${data.outputSummary}` : data.summary as string}</p>
                {(data.blockingReason as string) && <p style={{ fontSize: 9, color: '#dc2626', marginTop: 2 }}>⚠ {data.blockingReason as string}</p>}
                {awaiting && data.onConfirm && (
                    <button
                        onClick={(e) => { e.stopPropagation(); (data.onConfirm as (k: string) => void)(data.stepKey as string) }}
                        style={{
                            marginTop: 4, width: '100%', padding: '3px 0', borderRadius: 6,
                            border: '1px solid #f59e0b', background: '#fef3c7', color: '#92400e',
                            fontSize: 9, fontWeight: 600, cursor: 'pointer',
                        }}
                    >✓ 确认并继续</button>
                )}
            </div>
            <Handle id="s-right"  type="source" position={Position.Right}  className="!opacity-0 !w-2 !h-2" />
            <Handle id="s-bottom" type="source" position={Position.Bottom} className="!opacity-0 !w-2 !h-2" />
        </>
    )
}

// ══════════════════════════════════════════
//  节点渲染器: 调度器
// ══════════════════════════════════════════

type DispData = {
    nodeId: string
    label: string
    subtitle?: string
    icon?: string
    status: WorkflowStepStatus
    active?: boolean
    onSelectNode?: (nodeId: string) => void
}

function DispatcherNode({ data }: NodeProps<Node<DispData>>) {
    const c = SC[data.status as WorkflowStepStatus] || SC.pending
    const clickable = Boolean(data.nodeId && data.onSelectNode)
    return (
        <>
            <Handle id="t-left" type="target" position={Position.Left} className="!opacity-0 !w-2 !h-2" />
            <Handle id="t-top" type="target" position={Position.Top} className="!opacity-0 !w-2 !h-2" />
            <div
                className="select-none"
                role={clickable ? 'button' : undefined}
                tabIndex={clickable ? 0 : undefined}
                onClick={clickable ? () => data.onSelectNode?.(data.nodeId as string) : undefined}
                onKeyDown={clickable ? (event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return
                    event.preventDefault()
                    data.onSelectNode?.(data.nodeId as string)
                } : undefined}
                style={{
                width: 142, padding: '12px 14px', borderRadius: 18,
                border: `1.5px solid ${data.active ? '#5B7FD5' : c.border}`, background: data.active ? '#eef4ff' : '#ffffff',
                boxShadow: data.active ? '0 0 0 3px rgba(91,127,213,0.18)' : (c.glow || '0 8px 22px rgba(15,23,42,0.08)'),
                textAlign: 'center', cursor: clickable ? 'pointer' : 'grab',
            }}>
                <div style={{ fontSize: 18, marginBottom: 5 }}>{(data.icon as string) || '🎯'}</div>
                <div style={{ fontSize: 10.5, fontWeight: 700, color: c.text }}>{data.label as string}</div>
                <div style={{ fontSize: 8, color: '#94a3b8', marginTop: 4, lineHeight: 1.4 }}>{(data.subtitle as string) || ''}</div>
            </div>
            <Handle id="s-right" type="source" position={Position.Right} className="!opacity-0 !w-2 !h-2" />
            <Handle id="s-bottom" type="source" position={Position.Bottom} className="!opacity-0 !w-2 !h-2" />
        </>
    )
}

// ══════════════════════════════════════════
//  节点渲染器: 专家 Agent
// ══════════════════════════════════════════

type AgentData = {
    nodeId: string
    label: string
    icon: string
    disc: string
    status: WorkflowStepStatus
    width?: number
    active?: boolean
    agentRunId?: string
    expandable?: boolean
    expanded?: boolean
    onToggleExpand?: () => void
    onSelectNode?: (nodeId: string) => void
    onSelectAgentRun?: (agentRunId: string) => void
}

function SpecialistNode({ data }: NodeProps<Node<AgentData>>) {
    const c = SC[data.status as WorkflowStepStatus] || SC.pending
    const active = Boolean(data.active)
    const expandable = Boolean(data.expandable && data.onToggleExpand)
    const clickable = Boolean((data.agentRunId && data.onSelectAgentRun) || (data.nodeId && data.onSelectNode))
    const selectNode = () => {
        if (data.agentRunId && data.onSelectAgentRun) {
            data.onSelectAgentRun(data.agentRunId as string)
            return
        }
        data.onSelectNode?.(data.nodeId as string)
    }
    return (
        <>
            <Handle id="t-left" type="target" position={Position.Left} className="!opacity-0 !w-2 !h-2" />
            <Handle id="t-top" type="target" position={Position.Top} className="!opacity-0 !w-2 !h-2" />
            <div
                className="select-none"
                role={clickable ? 'button' : undefined}
                tabIndex={clickable ? 0 : undefined}
                onClick={clickable ? selectNode : undefined}
                onKeyDown={clickable ? (event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return
                    event.preventDefault()
                    selectNode()
                } : undefined}
                style={{
                    width: data.width || 110,
                    padding: '7px 8px',
                    borderRadius: 10,
                    border: `1.5px solid ${active ? '#5B7FD5' : c.border}`,
                    background: active ? '#eef4ff' : c.bg,
                    boxShadow: active ? '0 0 0 3px rgba(91,127,213,0.18)' : (c.glow || '0 1px 2px rgba(0,0,0,0.04)'),
                    textAlign: 'center',
                    cursor: clickable ? 'pointer' : 'grab',
                    position: 'relative',
                }}
            >
                {expandable ? (
                    <button
                        type="button"
                        aria-label={data.expanded ? '收起专业组详情' : '展开专业组详情'}
                        title={data.expanded ? '收起专业组详情' : '展开专业组详情'}
                        onClick={(event) => {
                            event.stopPropagation()
                            data.onToggleExpand?.()
                        }}
                        style={{
                            position: 'absolute',
                            top: 4,
                            right: 4,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: 16,
                            height: 16,
                            padding: 0,
                            borderRadius: 4,
                            border: '1px solid rgba(0,0,0,0.08)',
                            background: 'rgba(255,255,255,0.92)',
                            color: '#64748b',
                            cursor: 'pointer',
                            fontSize: 10,
                            lineHeight: 1,
                        }}
                    >
                        {data.expanded ? '▾' : '▸'}
                    </button>
                ) : null}
                <div style={{ fontSize: 16, marginBottom: 1 }}>{data.icon as string}</div>
                <div style={{ fontSize: 10, fontWeight: 600, color: c.text }}>{data.label as string}</div>
                <div style={{ fontSize: 8, color: '#a1a1aa' }}>{data.disc as string}</div>
            </div>
            <Handle id="s-right" type="source" position={Position.Right} className="!opacity-0 !w-2 !h-2" />
            <Handle id="s-bottom" type="source" position={Position.Bottom} className="!opacity-0 !w-2 !h-2" />
        </>
    )
}

// ══════════════════════════════════════════
//  节点渲染器: 分组框 (Cluster)
// ══════════════════════════════════════════

type ClusterData = {
    title: string
    subtitle?: string
    width: number
    height: number
    status: WorkflowStepStatus
    tone?: 'primary' | 'neutral'
}

function ClusterNode({ data }: NodeProps<Node<ClusterData>>) {
    const c = SC[data.status as WorkflowStepStatus] || SC.pending
    const tone = data.tone || 'neutral'
    const palette = tone === 'primary'
        ? {
            border: data.status === 'running' ? c.border : '#93c5fd',
            bg: data.status === 'running' ? 'rgba(239,246,255,0.94)' : 'rgba(248,250,252,0.98)',
            titleBg: data.status === 'running' ? '#dbeafe' : '#eff6ff',
            titleText: data.status === 'running' ? '#1d4ed8' : '#315ea8',
        }
        : {
            border: '#cbd5e1',
            bg: 'rgba(248,250,252,0.96)',
            titleBg: '#f1f5f9',
            titleText: '#475569',
        }
    return (
        <div
            style={{
                width: data.width,
                height: data.height,
                borderRadius: 24,
                border: `1.5px solid ${palette.border}`,
                background: palette.bg,
                boxShadow: c.glow || '0 10px 30px rgba(15,23,42,0.06)',
                padding: '14px 16px',
            }}
        >
            <div
                style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    padding: '4px 10px',
                    borderRadius: 999,
                    background: palette.titleBg,
                    color: palette.titleText,
                    fontSize: 11,
                    fontWeight: 700,
                }}
            >
                {data.title}
            </div>
            {data.subtitle && (
                <div style={{ marginTop: 8, fontSize: 8.5, color: '#64748b', lineHeight: 1.45, maxWidth: data.width - 44 }}>{data.subtitle}</div>
            )}
        </div>
    )
}

// ══════════════════════════════════════════
//  节点渲染器: 汇聚
// ══════════════════════════════════════════

type MergeData = {
    nodeId?: string
    label?: string
    subtitle?: string
    status: WorkflowStepStatus
    active?: boolean
    onSelectNode?: (nodeId: string) => void
}

function MergeNode({ data }: NodeProps<Node<MergeData>>) {
    const c = SC[data.status as WorkflowStepStatus] || SC.pending
    const clickable = Boolean(data.nodeId && data.onSelectNode)
    return (
        <>
            <Handle id="t-left" type="target" position={Position.Left} className="!opacity-0 !w-2 !h-2" />
            <Handle id="t-top" type="target" position={Position.Top} className="!opacity-0 !w-2 !h-2" />
            <div
                role={clickable ? 'button' : undefined}
                tabIndex={clickable ? 0 : undefined}
                onClick={clickable ? () => data.onSelectNode?.(data.nodeId as string) : undefined}
                onKeyDown={clickable ? (event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return
                    event.preventDefault()
                    data.onSelectNode?.(data.nodeId as string)
                } : undefined}
                style={{
                    width: 142, padding: '10px 12px', borderRadius: 16,
                    border: `1.5px solid ${data.active ? '#5B7FD5' : c.border}`, background: data.active ? '#eef4ff' : '#ffffff',
                    boxShadow: data.active ? '0 0 0 3px rgba(91,127,213,0.18)' : (c.glow || '0 8px 22px rgba(15,23,42,0.08)'),
                    textAlign: 'center', cursor: clickable ? 'pointer' : 'grab',
                }}
            >
                <div style={{ fontSize: 16, marginBottom: 4, color: c.text }}>⋁</div>
                <div style={{ fontSize: 10.5, fontWeight: 700, color: c.text }}>{(data.label as string) || '汇合'}</div>
                <div style={{ fontSize: 8, color: '#94a3b8', marginTop: 4, lineHeight: 1.4 }}>{(data.subtitle as string) || ''}</div>
            </div>
            <Handle id="s-right" type="source" position={Position.Right} className="!opacity-0 !w-2 !h-2" />
            <Handle id="s-bottom" type="source" position={Position.Bottom} className="!opacity-0 !w-2 !h-2" />
        </>
    )
}

// ══════════════════════════════════════════
//  节点类型注册表
// ══════════════════════════════════════════

const nodeTypes: NodeTypes = {
    step: StepNode,
    dispatch: DispatcherNode,
    team_lead: SpecialistNode,
    agent: SpecialistNode,
    cluster: ClusterNode,
    merge: MergeNode,
}

// ══════════════════════════════════════════
//  Dagre 自动布局
// ══════════════════════════════════════════

const NODE_DIMENSIONS: Record<string, { width: number; height: number }> = {
    step:       { width: 168, height: 100 },
    dispatch:   { width: 146, height: 90 },
    team_lead:  { width: 168, height: 68 },
    agent:      { width: 154, height: 68 },
    merge:      { width: 146, height: 88 },
}

function isGroupHotStatus(status: WorkflowStepStatus): boolean {
    return status === 'running' || status === 'awaiting_confirm' || status === 'blocked' || status === 'failed'
}

function resolveExpandedTeamLeadId(
    subflowNodes: WorkflowGraph['nodes'],
    teamLeadNodes: WorkflowGraph['nodes'],
    activeNodeId?: string,
): string | undefined {
    if (!teamLeadNodes.length) return undefined

    const activeNode = activeNodeId
        ? subflowNodes.find(n => n.node_id === activeNodeId)
        : undefined
    if (activeNode?.node_type === 'team_lead') return activeNode.node_id
    if (activeNode?.parent_node_id && teamLeadNodes.some(t => t.node_id === activeNode.parent_node_id)) {
        return activeNode.parent_node_id
    }

    const hotTeamLead = teamLeadNodes.find(tl => isGroupHotStatus(tl.status))
    if (hotTeamLead) return hotTeamLead.node_id

    const hotChild = subflowNodes.find(n => n.parent_node_id && isGroupHotStatus(n.status))
    if (hotChild?.parent_node_id && teamLeadNodes.some(t => t.node_id === hotChild.parent_node_id)) {
        return hotChild.parent_node_id
    }

    return undefined
}

function buildDagreLayout(
    graph: WorkflowGraph,
    mode: 'blueprint' | 'live',
    activeNodeId?: string,
    onConfirm?: (stepKey: string) => void,
    onSelectNode?: (nodeId: string) => void,
    onSelectAgentRun?: (agentRunId: string) => void,
    expandedTeamLeadIds: ReadonlySet<string> = new Set(),
    layoutVariant: AutoLayoutVariant = 'vertical',
    onToggleTeamLead?: (teamLeadId: string) => void,
) {
    const g = new Graph({ compound: true })
    const horizontal = isHorizontalWorkflowLayout(layoutVariant)
    const teamLeadNodesPreview = (graph.nodes || []).filter(n => n.node_type === 'team_lead')
    const baseGraphOptions = { ...AUTO_LAYOUT_OPTIONS[layoutVariant].graph }
    if (teamLeadNodesPreview.length > 1) {
        // 并行 lane 在横向布局时上下分叉，纵向布局时左右分叉
        baseGraphOptions.nodesep = (Number(baseGraphOptions.nodesep) || 34) + (horizontal ? 18 : 14)
    }
    g.setGraph(baseGraphOptions)
    g.setDefaultEdgeLabel(() => ({}))
    const edgeHandle = resolveWorkflowEdgeHandles(layoutVariant)

    const graphNodes = graph.nodes || []
    const graphEdges = graph.edges || []

    // ── 识别顶层步骤节点并按类型分组 ──
    const topStepNodes = graphNodes.filter(n => n.node_type === 'step')
    const subflowNodes = graphNodes.filter(n => n.node_type !== 'step')
    const teamLeadNodes = subflowNodes.filter(n => n.node_type === 'team_lead')

    // 收起时隐藏组内 agent；每个专业组独立维护展开状态。
    const hiddenChildNodeIds = new Set<string>()
    teamLeadNodes
        .filter(tl => !expandedTeamLeadIds.has(tl.node_id))
        .forEach((tl) => {
            subflowNodes
                .filter(n => n.parent_node_id === tl.node_id)
                .forEach(n => hiddenChildNodeIds.add(n.node_id))
        })
    const visibleSubflowNodes = subflowNodes.filter(n => !hiddenChildNodeIds.has(n.node_id))
    const visibleGraphNodes = [...topStepNodes, ...visibleSubflowNodes]

    // ── 注册所有节点到 dagre ──
    // 1. 顶层步骤节点
    topStepNodes.forEach((n) => {
        const dim = NODE_DIMENSIONS.step
        g.setNode(n.node_id, { width: dim.width, height: dim.height, label: n.label })
    })

    // 2. 子流程节点
    visibleSubflowNodes.forEach(n => {
        const dim = NODE_DIMENSIONS[n.node_type] || NODE_DIMENSIONS.agent
        g.setNode(n.node_id, { width: dim.width, height: dim.height, label: n.label })
        // 设置父子关系（compound）
        if (n.parent_node_id) {
            const parentIsTopStep = topStepNodes.some(s => s.node_id === n.parent_node_id)
            if (!parentIsTopStep) {
                // 子节点: 父节点不是顶层 step 时才设置 compound parent
                // (dagre compound requires parent to be in graph)
            }
        }
    })

    // ── 注册边到 dagre ──
    const filteredEdges = graphEdges.filter(e => g.hasNode(e.source) && g.hasNode(e.target))
    const virtualEdges: Array<{ source: string; target: string }> = []
    const mergeNodeId = visibleSubflowNodes.find(n => n.node_type === 'merge')?.node_id
    if (mergeNodeId) {
        teamLeadNodes.forEach(tl => {
            if (expandedTeamLeadIds.has(tl.node_id) || !g.hasNode(tl.node_id)) return

            const hiddenChildIds = new Set(
                subflowNodes
                    .filter(n => n.parent_node_id === tl.node_id)
                    .map(n => n.node_id),
            )

            const exitTargets = new Set<string>()
            graphEdges.forEach(e => {
                if (hiddenChildIds.has(e.source) && g.hasNode(e.target) && !hiddenChildIds.has(e.target)) {
                    exitTargets.add(e.target)
                }
            })

            if (exitTargets.size === 0 && mergeNodeId) {
                virtualEdges.push({ source: tl.node_id, target: mergeNodeId })
                return
            }

            exitTargets.forEach((target) => {
                virtualEdges.push({ source: tl.node_id, target })
            })
        })
        if (expandedTeamLeadIds.size === 0) {
            const mergeIncomingSources = filteredEdges
                .filter(e => e.target === mergeNodeId)
                .map(e => e.source)
            const hasNonDispatchMergeFeed = mergeIncomingSources.some((sourceId) => {
                const node = visibleSubflowNodes.find(n => n.node_id === sourceId)
                    || topStepNodes.find(n => n.node_id === sourceId)
                return node && node.node_type !== 'dispatch'
            })
            const hasExplicitDispatchMergeFallback = filteredEdges.some((edge) => {
                if (edge.target !== mergeNodeId) return false
                const sourceNode = visibleSubflowNodes.find(n => n.node_id === edge.source)
                    || topStepNodes.find(n => n.node_id === edge.source)
                return sourceNode?.node_type === 'dispatch'
            })
            // 仅当 view model 已声明 dispatch->merge 兜底边，且尚无 gate/专家汇入时，才补布局边
            if (!hasNonDispatchMergeFeed && hasExplicitDispatchMergeFallback) {
                visibleSubflowNodes
                    .filter(n => n.node_type === 'dispatch')
                    .forEach(dispatch => virtualEdges.push({ source: dispatch.node_id, target: mergeNodeId }))
            }
        }
    }
    const mergedEdges = [
        ...filteredEdges,
        ...virtualEdges.map(e => ({
            source: e.source,
            target: e.target,
            condition: 'on_success',
            label: '',
        })),
    ].filter((edge, idx, arr) =>
        arr.findIndex(x => x.source === edge.source && x.target === edge.target) === idx
    )
    mergedEdges.forEach(e => {
        // 跳过从顶层 step 到子流程节点的边（由布局内部处理）
        if (g.hasNode(e.source) && g.hasNode(e.target)) {
            g.setEdge(e.source, e.target)
        }
    })

    // ── 执行自动布局 ──
    dagreLayout(g)

    // ── 构建 ReactFlow 节点 ──
    const rfNodes: Node[] = []
    const rfEdges: Edge[] = []

    // 找出需要分组框的子流程组
    // 姿态确定专业组: parent = dispatch, node_type = team_lead 且有自己的子节点
    const lateralAgentNodes = visibleSubflowNodes.filter(n =>
        n.node_type === 'agent' && !teamLeadNodes.some(tl => n.parent_node_id === tl.node_id)
        && n.parent_node_id && visibleSubflowNodes.some(d => d.node_id === n.parent_node_id && d.node_type === 'dispatch')
    )

    // 构建分组框
    if (teamLeadNodes.length > 0) {
        teamLeadNodes.forEach(tl => {
            if (!expandedTeamLeadIds.has(tl.node_id)) return
            const children = visibleSubflowNodes.filter(n => n.parent_node_id === tl.node_id)
            if (children.length === 0) return
            const allGroupNodes = [tl, ...children]
            const positions = allGroupNodes.map(n => {
                const pos = g.node(n.node_id)
                const dim = NODE_DIMENSIONS[n.node_type] || NODE_DIMENSIONS.agent
                return pos ? { x: pos.x - dim.width / 2, y: pos.y - dim.height / 2, w: dim.width, h: dim.height } : null
            }).filter(Boolean) as { x: number; y: number; w: number; h: number }[]
            if (positions.length === 0) return
            const minX = Math.min(...positions.map(p => p.x)) - 26
            const minY = Math.min(...positions.map(p => p.y)) - 66
            const maxX = Math.max(...positions.map(p => p.x + p.w)) + 26
            const maxY = Math.max(...positions.map(p => p.y + p.h)) + 26
            rfNodes.push({
                id: `cluster_${tl.node_id}`,
                type: 'cluster',
                position: { x: minX, y: minY },
                zIndex: -1,
                data: {
                    title: tl.label,
                    subtitle: tl.subtitle || '',
                    width: maxX - minX,
                    height: maxY - minY,
                    status: tl.status,
                    tone: 'primary',
                },
                draggable: false,
                selectable: false,
            })
        })
    }

    // 横向审查分组框
    if (lateralAgentNodes.length > 0) {
        const positions = lateralAgentNodes.map(n => {
            const pos = g.node(n.node_id)
            const dim = NODE_DIMENSIONS.agent
            return pos ? { x: pos.x - dim.width / 2, y: pos.y - dim.height / 2, w: dim.width, h: dim.height } : null
        }).filter(Boolean) as { x: number; y: number; w: number; h: number }[]
        if (positions.length > 0) {
            const minX = Math.min(...positions.map(p => p.x)) - 26
            const minY = Math.min(...positions.map(p => p.y)) - 12
            const maxX = Math.max(...positions.map(p => p.x + p.w)) + 26
            const maxY = Math.max(...positions.map(p => p.y + p.h)) + 26
            const dispatchNode = subflowNodes.find(n => n.node_type === 'dispatch')
            rfNodes.push({
                id: 'cluster_lateral_review',
                type: 'cluster',
                position: { x: minX, y: minY },
                zIndex: -1,
                data: {
                    title: '横向审查',
                    subtitle: dispatchNode ? '' : '并行审查环节',
                    width: maxX - minX,
                    height: maxY - minY,
                    status: lateralAgentNodes[0].status,
                    tone: 'neutral',
                },
                draggable: false,
                selectable: false,
            })
        }
    }

    // 渲染步骤节点
    topStepNodes.forEach((n, idx) => {
        const pos = g.node(n.node_id)
        if (!pos) return
        const dim = NODE_DIMENSIONS.step
        rfNodes.push({
            id: n.node_id,
            type: 'step',
            position: { x: pos.x - dim.width / 2, y: pos.y - dim.height / 2 },
            zIndex: 1,
            data: {
                nodeId: n.node_id,
                label: n.label,
                stepKey: n.step_key,
                icon: n.icon || '📌',
                status: n.status,
                index: idx,
                summary: n.subtitle || '',
                outputSummary: n.output_summary || '',
                blockingReason: n.blocked_reason || '',
                mode,
                active: activeNodeId === n.node_id || activeNodeId === n.step_key,
                onConfirm,
                onSelectNode,
            },
        })
    })

    // 渲染子流程节点
    visibleSubflowNodes.forEach(n => {
        const pos = g.node(n.node_id)
        if (!pos) return
        const dim = NODE_DIMENSIONS[n.node_type] || NODE_DIMENSIONS.agent
        const nodeType = n.node_type === 'dispatch' ? 'dispatch'
            : n.node_type === 'merge' ? 'merge'
            : n.node_type === 'team_lead' ? 'team_lead'
            : 'agent'

        if (nodeType === 'dispatch') {
            rfNodes.push({
                id: n.node_id,
                type: 'dispatch',
                position: { x: pos.x - dim.width / 2, y: pos.y - dim.height / 2 },
                zIndex: 1,
                data: {
                    nodeId: n.node_id,
                    label: n.label,
                    subtitle: n.subtitle || '',
                    icon: n.icon || '🎯',
                    status: n.status,
                    active: activeNodeId === n.node_id,
                    onSelectNode,
                },
            })
        } else if (nodeType === 'merge') {
            rfNodes.push({
                id: n.node_id,
                type: 'merge',
                position: { x: pos.x - dim.width / 2, y: pos.y - dim.height / 2 },
                zIndex: 1,
                data: {
                    nodeId: n.node_id,
                    label: n.label,
                    subtitle: n.subtitle || '',
                    status: n.status,
                    active: activeNodeId === n.node_id,
                    onSelectNode,
                },
            })
        } else {
            // team_lead or agent
            const agentRunId = n.agent_run_ids?.[0]
            const isTeamLead = nodeType === 'team_lead'
            rfNodes.push({
                id: n.node_id,
                type: nodeType,
                position: { x: pos.x - dim.width / 2, y: pos.y - dim.height / 2 },
                zIndex: 1,
                data: {
                    nodeId: n.node_id,
                    label: n.label,
                    icon: n.icon || n.label.slice(0, 2) || '审查',
                    disc: n.subtitle || '',
                    status: n.status,
                    width: dim.width,
                    active: activeNodeId === n.node_id,
                    onSelectNode,
                    ...(isTeamLead && onToggleTeamLead ? {
                        expandable: true,
                        expanded: expandedTeamLeadIds.has(n.node_id),
                        onToggleExpand: () => onToggleTeamLead(n.node_id),
                    } : {}),
                    ...(agentRunId && onSelectAgentRun ? { agentRunId, onSelectAgentRun } : {}),
                },
            })
        }
    })

    // 渲染边
    mergedEdges.forEach(e => {
        const srcNode = visibleGraphNodes.find(n => n.node_id === e.source)
        const status: WorkflowStepStatus = srcNode?.status || 'pending'
        const active = status === 'completed' || status === 'running' || status === 'awaiting_confirm'
        rfEdges.push({
            id: `e-${e.source}-${e.target}`,
            source: e.source,
            target: e.target,
            ...edgeHandle,
            type: WORKFLOW_DAG_EDGE_TYPE,
            pathOptions: { borderRadius: 8 },
            markerEnd: { type: MarkerType.ArrowClosed },
            style: {
                stroke: status === 'completed' ? '#34d399' : status === 'awaiting_confirm' ? '#f59e0b' : active ? '#60a5fa' : '#d4d4d8',
                strokeWidth: active ? 2 : 1.5,
                strokeDasharray: status === 'pending' ? '6 3' : undefined,
            },
            animated: status === 'running' || status === 'awaiting_confirm',
        } as Edge)
    })

    return { nodes: rfNodes, edges: rfEdges }
}

// ══════════════════════════════════════════
//  HITL 面板子组件
// ══════════════════════════════════════════

interface HitlPanelProps {
    configurableSteps: { key: string; name: string }[]
    enabledSteps: string[]
    onSave: (steps: string[]) => void | Promise<void>
    onClose: () => void
    isMobile: boolean
}

function HitlPanel({ configurableSteps, enabledSteps, onSave, onClose, isMobile }: HitlPanelProps) {
    const [draft, setDraft] = useState<string[]>(enabledSteps)
    const [saving, setSaving] = useState(false)

    useEffect(() => { setDraft(enabledSteps) }, [enabledSteps])

    const allSelected = configurableSteps.every(s => draft.includes(s.key))
    const dirty = JSON.stringify([...draft].sort()) !== JSON.stringify([...enabledSteps].sort())

    const toggleAll = () => setDraft(allSelected ? [] : configurableSteps.map(s => s.key))
    const toggleStep = (key: string) => setDraft(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key])

    const handleSave = async () => {
        if (!dirty) return
        setSaving(true)
        try { await onSave(draft); onClose() } finally { setSaving(false) }
    }

    return (
        <div
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            className="aq-soft-panel"
            style={{
                position: 'absolute', top: '100%', right: 0, marginTop: 6,
                width: isMobile ? 'min(320px, calc(100vw - 24px))' : 240,
                maxWidth: 'calc(100vw - 24px)',
                maxHeight: isMobile ? 'min(60vh, 420px)' : undefined,
                overflowY: isMobile ? 'auto' : undefined,
                padding: '12px 14px', borderRadius: 12, zIndex: 50,
            }}
        >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: 'rgb(var(--color-text-primary))' }}>人工确认设置</span>
                <button onClick={toggleAll} style={{
                    fontSize: 9, padding: '2px 8px', borderRadius: 4,
                    border: '1px solid rgba(var(--color-border), 0.15)',
                    background: allSelected ? 'rgba(var(--color-primary-accent), 0.1)' : 'rgba(var(--color-surface), 0.8)',
                    color: allSelected ? 'rgb(var(--color-primary-accent))' : 'rgb(var(--color-muted))',
                    cursor: 'pointer', fontWeight: 500,
                }}>{allSelected ? '全不选' : '全选'}</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 8px' }}>
                {configurableSteps.map(s => (
                    <label key={s.key} style={{
                        display: 'flex', alignItems: 'center', gap: 6, padding: '4px 6px',
                        borderRadius: 6, cursor: 'pointer', fontSize: 10,
                        color: 'rgb(var(--color-text-primary))',
                        background: draft.includes(s.key) ? 'rgba(var(--color-primary-accent), 0.08)' : undefined,
                    }}>
                        <input type="checkbox" checked={draft.includes(s.key)}
                            onChange={() => toggleStep(s.key)}
                            style={{ width: 13, height: 13, accentColor: 'rgb(var(--color-primary-accent))' }} />
                        {s.name}
                    </label>
                ))}
            </div>
            <div style={{ marginTop: 10, fontSize: 8, color: 'rgb(var(--color-muted))', lineHeight: 1.4 }}>
                启用后，Agent 执行完该步骤将暂停等待人工确认后再继续。
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 10, paddingTop: 10,
                borderTop: '1px solid rgba(var(--color-border), 0.1)' }}>
                <button
                    onClick={onClose}
                    style={{
                        fontSize: 10, padding: '3px 10px', borderRadius: 5,
                        border: '1px solid rgba(var(--color-border), 0.15)',
                        background: 'transparent', color: 'rgb(var(--color-muted))', cursor: 'pointer',
                    }}>取消</button>
                <button
                    onClick={handleSave}
                    disabled={!dirty || saving}
                    style={{
                        fontSize: 10, padding: '3px 12px', borderRadius: 5, fontWeight: 500,
                        border: 'none',
                        background: dirty ? 'rgb(var(--color-primary-accent))' : 'rgba(var(--color-muted), 0.2)',
                        color: dirty ? '#fff' : 'rgb(var(--color-muted))',
                        cursor: dirty ? 'pointer' : 'default',
                        opacity: saving ? 0.6 : 1,
                    }}>{saving ? '保存中...' : '保存'}</button>
            </div>
        </div>
    )
}

// ══════════════════════════════════════════
//  主组件
// ══════════════════════════════════════════

function FitViewOnLayoutChange({
    layoutVariant,
    layoutMode,
    expandedTeamLeadKey,
}: {
    layoutVariant: AutoLayoutVariant
    layoutMode: LayoutMode
    expandedTeamLeadKey: string
}) {
    const { fitView } = useReactFlow()
    useEffect(() => {
        const timer = window.setTimeout(() => {
            void fitView({ padding: 0.2, duration: 220 })
        }, 0)
        return () => window.clearTimeout(timer)
    }, [fitView, layoutVariant, layoutMode, expandedTeamLeadKey])
    return null
}

export interface WorkflowDAGViewerProps {
    graph: WorkflowGraph
    mode: 'blueprint' | 'live'
    className?: string
    activeNodeId?: string
    title?: string
    description?: string
    // 业务回调
    onSelectNode?: (nodeId: string) => void
    onSelectAgentRun?: (agentRunId: string) => void
    onPaneClick?: () => void
    // HITL
    hitlEnabled?: boolean
    hitlEnabledSteps?: string[]
    hitlConfigurableSteps?: { key: string; name: string }[]
    onHitlConfigChange?: (steps: string[]) => void | Promise<void>
    onConfirmStep?: (stepKey: string) => void
    /** 首次加载 / 容器尚未测量时的 Dagre 布局方向 */
    defaultAutoLayoutVariant?: AutoLayoutVariant
    /** 布局偏好默认值；`auto` 表示随容器宽高自动切换横/纵向 */
    defaultLayoutVariantPreference?: LayoutVariantPreference
    /** 受控布局方向（传入后将禁用响应式自动判定） */
    layoutVariant?: AutoLayoutVariant
    onLayoutVariantChange?: (variant: AutoLayoutVariant) => void
    /** 是否启用响应式横/纵向自动判定（受控模式下无效） */
    enableResponsiveLayout?: boolean
    /** 有效布局方向变化回调（含自动判定结果） */
    onEffectiveLayoutVariantChange?: (variant: AutoLayoutVariant) => void
    /** 限制工具栏可选布局（默认全部；不含 `auto`） */
    allowedLayoutVariants?: AutoLayoutVariant[]
    /** 覆盖 localStorage 布局缓存 key */
    layoutStorageKey?: string
    /** 初始展开的专业组 team_lead node_id 列表（如 GNC AD/AC 子流程） */
    initialExpandedTeamLeadIds?: readonly string[]
}

export default function WorkflowDAGViewer({
    graph,
    mode,
    className,
    activeNodeId,
    title,
    description,
    onSelectNode,
    onSelectAgentRun,
    onPaneClick,
    hitlEnabled,
    hitlEnabledSteps = [],
    hitlConfigurableSteps = [],
    onHitlConfigChange,
    onConfirmStep,
    defaultAutoLayoutVariant = 'vertical',
    defaultLayoutVariantPreference = 'auto',
    layoutVariant: controlledLayoutVariant,
    onLayoutVariantChange,
    enableResponsiveLayout = true,
    onEffectiveLayoutVariantChange,
    allowedLayoutVariants,
    layoutStorageKey: layoutStorageKeyOverride,
    initialExpandedTeamLeadIds,
}: WorkflowDAGViewerProps) {
    const isMobile = useIsMobile()
    const [maximized, setMaximized] = useState(false)
    const [mounted, setMounted] = useState(false)
    const [hitlPanelOpen, setHitlPanelOpen] = useState(false)
    const [layoutMode, setLayoutMode] = useState<LayoutMode>('auto')
    const [layoutVariantPreference, setLayoutVariantPreference] = useState<LayoutVariantPreference>(defaultLayoutVariantPreference)
    const [internalLayoutVariant, setInternalLayoutVariant] = useState<AutoLayoutVariant>(defaultAutoLayoutVariant)
    const [manualPositions, setManualPositions] = useState<Record<string, XYPosition>>({})
    const initialExpandedKey = initialExpandedTeamLeadIds?.slice().sort().join('|') ?? ''
    const [expandedTeamLeadIds, setExpandedTeamLeadIds] = useState<Set<string>>(
        () => new Set(initialExpandedTeamLeadIds ?? []),
    )
    const [containerSize, setContainerSize] = useState({ width: 0, height: 0 })
    const flowCanvasRef = useRef<HTMLDivElement>(null)
    const isControlledLayout = controlledLayoutVariant !== undefined
    const responsiveLayoutEnabled = enableResponsiveLayout && !isControlledLayout
    const effectiveLayoutVariant: AutoLayoutVariant = useMemo(() => {
        if (isControlledLayout) return controlledLayoutVariant
        if (layoutVariantPreference === 'auto') {
            return resolveResponsiveLayoutVariant(containerSize.width, containerSize.height, defaultAutoLayoutVariant)
        }
        return layoutVariantPreference
    }, [
        isControlledLayout,
        controlledLayoutVariant,
        layoutVariantPreference,
        containerSize.width,
        containerSize.height,
        defaultAutoLayoutVariant,
    ])
    const allowedLayoutVariantsKey = allowedLayoutVariants?.join(',') ?? ''
    const selectableLayoutVariants = useMemo(
        () => allowedLayoutVariants?.length
            ? allowedLayoutVariants
            : (Object.keys(AUTO_LAYOUT_OPTIONS) as AutoLayoutVariant[]),
        [allowedLayoutVariantsKey, allowedLayoutVariants],
    )
    const updateLayoutVariantRef = useRef<(variant: AutoLayoutVariant) => void>(() => undefined)
    const hydratedLayoutKeyRef = useRef<string | null>(null)
    const onEffectiveLayoutVariantChangeRef = useRef(onEffectiveLayoutVariantChange)
    onEffectiveLayoutVariantChangeRef.current = onEffectiveLayoutVariantChange

    useEffect(() => {
        onEffectiveLayoutVariantChangeRef.current?.(effectiveLayoutVariant)
    }, [effectiveLayoutVariant])

    useEffect(() => {
        const element = flowCanvasRef.current
        if (!element || !responsiveLayoutEnabled) return

        const updateSize = () => {
            const rect = element.getBoundingClientRect()
            const width = Math.round(rect.width)
            const height = Math.round(rect.height)
            setContainerSize((prev) => (
                prev.width === width && prev.height === height ? prev : { width, height }
            ))
        }

        updateSize()
        const observer = new ResizeObserver(updateSize)
        observer.observe(element)
        return () => observer.disconnect()
    }, [responsiveLayoutEnabled, maximized])

    const teamLeadIds = useMemo(
        () => (graph.nodes || []).filter(n => n.node_type === 'team_lead').map(n => n.node_id),
        [graph.nodes],
    )
    const expandedTeamLeadKey = useMemo(
        () => [...expandedTeamLeadIds].sort().join('|'),
        [expandedTeamLeadIds],
    )

    const toggleTeamLead = useCallback((teamLeadId: string) => {
        setExpandedTeamLeadIds((prev) => {
            const next = new Set(prev)
            if (next.has(teamLeadId)) next.delete(teamLeadId)
            else next.add(teamLeadId)
            return next
        })
    }, [])

    const allTeamGroupsExpanded = teamLeadIds.length > 0 && teamLeadIds.every(id => expandedTeamLeadIds.has(id))

    const toggleAllTeamGroups = useCallback(() => {
        setExpandedTeamLeadIds(allTeamGroupsExpanded ? new Set() : new Set(teamLeadIds))
    }, [allTeamGroupsExpanded, teamLeadIds])

    useEffect(() => {
        if (!initialExpandedKey) return
        setExpandedTeamLeadIds((prev) => {
            const next = new Set(prev)
            for (const id of initialExpandedTeamLeadIds ?? []) {
                if (teamLeadIds.includes(id)) next.add(id)
            }
            if (next.size === prev.size && [...next].every((id) => prev.has(id))) return prev
            return next
        })
    }, [initialExpandedKey, teamLeadIds])

    useEffect(() => {
        if (!teamLeadIds.length) return
        const subflowNodes = (graph.nodes || []).filter(n => n.node_type !== 'step')
        const teamLeadNodes = subflowNodes.filter(n => n.node_type === 'team_lead')
        const autoExpandedId = resolveExpandedTeamLeadId(subflowNodes, teamLeadNodes, activeNodeId)
        if (!autoExpandedId) return
        setExpandedTeamLeadIds((prev) => {
            if (prev.has(autoExpandedId)) return prev
            const next = new Set(prev)
            next.add(autoExpandedId)
            return next
        })
    }, [activeNodeId, graph.nodes, teamLeadIds.length])

    const updateLayoutVariant = useCallback((variant: AutoLayoutVariant) => {
        if (!isControlledLayout) setInternalLayoutVariant(variant)
        onLayoutVariantChange?.(variant)
    }, [isControlledLayout, onLayoutVariantChange])
    updateLayoutVariantRef.current = updateLayoutVariant

    const displayTitle = title || graph.title || '工作流'
    const displayDesc = description || graph.description || ''
    const layoutStorageKey = useMemo(
        () => layoutStorageKeyOverride || `${buildLayoutStorageKey(graph, mode)}:${defaultAutoLayoutVariant}`,
        [defaultAutoLayoutVariant, graph, layoutStorageKeyOverride, mode],
    )

    const onSelectNodeRef = useRef(onSelectNode)
    const onSelectAgentRunRef = useRef(onSelectAgentRun)
    const onConfirmStepRef = useRef(onConfirmStep)
    onSelectNodeRef.current = onSelectNode
    onSelectAgentRunRef.current = onSelectAgentRun
    onConfirmStepRef.current = onConfirmStep

    const layoutResult = useMemo(
        () => buildDagreLayout(
            graph,
            mode,
            activeNodeId,
            (stepKey) => onConfirmStepRef.current?.(stepKey),
            (nodeId) => onSelectNodeRef.current?.(nodeId),
            (agentRunId) => onSelectAgentRunRef.current?.(agentRunId),
            expandedTeamLeadIds,
            effectiveLayoutVariant,
            toggleTeamLead,
        ),
        [graph, mode, activeNodeId, expandedTeamLeadKey, effectiveLayoutVariant, toggleTeamLead],
    )

    const resolvedNodes = useMemo(() => {
        if (layoutMode !== 'manual') return layoutResult.nodes
        return layoutResult.nodes.map(node => {
            if (node.type === 'cluster') return node
            const saved = manualPositions[node.id]
            return saved ? { ...node, position: saved } : node
        })
    }, [layoutResult.nodes, layoutMode, manualPositions])

    const resolvedEdges = layoutResult.edges
    const layoutStructureKey = `${effectiveLayoutVariant}|${layoutMode}|${expandedTeamLeadKey}|${layoutVariantPreference}`

    const [flowNodes, setFlowNodes, onFlowNodesChange] = useNodesState(resolvedNodes)
    const [flowEdges, setFlowEdges, onFlowEdgesChange] = useEdgesState(resolvedEdges)

    useLayoutEffect(() => {
        setFlowNodes(resolvedNodes)
        setFlowEdges(resolvedEdges)
    }, [layoutStructureKey, resolvedNodes, resolvedEdges, setFlowNodes, setFlowEdges])

    useEffect(() => { setMounted(true) }, [])
    useEffect(() => {
        if (hydratedLayoutKeyRef.current === layoutStorageKey) return
        hydratedLayoutKeyRef.current = layoutStorageKey

        const allowedVariants = allowedLayoutVariants?.length
            ? allowedLayoutVariants
            : (Object.keys(AUTO_LAYOUT_OPTIONS) as AutoLayoutVariant[])

        try {
            const raw = window.localStorage.getItem(layoutStorageKey)
            if (!raw) {
                setLayoutMode('auto')
                setLayoutVariantPreference(defaultLayoutVariantPreference)
                if (defaultLayoutVariantPreference !== 'auto') {
                    updateLayoutVariantRef.current(defaultLayoutVariantPreference)
                }
                setManualPositions({})
                return
            }
            const parsed = JSON.parse(raw) as {
                mode?: LayoutMode
                variantPreference?: LayoutVariantPreference
                variant?: AutoLayoutVariant
                positions?: Record<string, XYPosition>
            }
            setLayoutMode(parsed.mode === 'manual' ? 'manual' : 'auto')
            const restoredPreference = parsed.variantPreference
                ?? parsed.variant
                ?? defaultLayoutVariantPreference
            const normalizedPreference: LayoutVariantPreference =
                restoredPreference === 'auto' || allowedVariants.includes(restoredPreference)
                    ? restoredPreference
                    : defaultLayoutVariantPreference
            setLayoutVariantPreference(normalizedPreference)
            if (normalizedPreference !== 'auto') {
                updateLayoutVariantRef.current(normalizedPreference)
            }
            setManualPositions(parsed.positions ?? {})
        } catch {
            setLayoutMode('auto')
            setLayoutVariantPreference(defaultLayoutVariantPreference)
            if (defaultLayoutVariantPreference !== 'auto') {
                updateLayoutVariantRef.current(defaultLayoutVariantPreference)
            }
            setManualPositions({})
        }
    }, [allowedLayoutVariants, defaultAutoLayoutVariant, defaultLayoutVariantPreference, layoutStorageKey])

    useEffect(() => {
        const payload = JSON.stringify({
            mode: layoutMode,
            variantPreference: layoutVariantPreference,
            positions: manualPositions,
        })
        window.localStorage.setItem(layoutStorageKey, payload)
    }, [layoutMode, layoutVariantPreference, manualPositions, layoutStorageKey])

    const toggle = useCallback(() => setMaximized(v => !v), [])
    /** 自动 / 手动互斥：切回自动时清除已保存的手动坐标（等同「恢复默认 Dagre 布局」）。 */
    const toggleLayoutMode = useCallback(() => {
        setLayoutMode((prev) => {
            if (prev === 'manual') {
                setManualPositions({})
                return 'auto'
            }
            return 'manual'
        })
    }, [])
    const handleLayoutPreferenceChange = useCallback((preference: LayoutVariantPreference) => {
        setLayoutVariantPreference(preference)
        if (preference !== 'auto') {
            updateLayoutVariant(preference)
        }
        setManualPositions({})
        setLayoutMode('auto')
    }, [updateLayoutVariant])
    const handleNodeDragStop = useCallback((_evt: unknown, node: Node) => {
        if (layoutMode !== 'manual' || node.type === 'cluster') return
        setManualPositions(prev => ({ ...prev, [node.id]: { x: node.position.x, y: node.position.y } }))
    }, [layoutMode])

    useEffect(() => {
        if (!maximized) return
        const h = (e: KeyboardEvent) => { if (e.key === 'Escape') setMaximized(false) }
        window.addEventListener('keydown', h)
        return () => window.removeEventListener('keydown', h)
    }, [maximized])

    const steps = (graph.nodes || []).filter(n => n.node_type === 'step')
    const completedCount = steps.filter(s => s.status === 'completed').length
    const runningStep = steps.find(s => s.status === 'running')
    const awaitingStep = steps.find(s => s.status === 'awaiting_confirm')
    const groupSummary = useMemo(() => {
        const allNodes = graph.nodes || []
        const teamLeads = allNodes.filter(n => n.node_type === 'team_lead')
        const dispatchNodes = allNodes.filter(n => n.node_type === 'dispatch')
        const items: string[] = []

        teamLeads.forEach((lead) => {
            const memberCount = allNodes.filter(n => n.node_type === 'agent' && n.parent_node_id === lead.node_id).length
            items.push(`${lead.label}（${memberCount}个智能体）`)
        })

        dispatchNodes.forEach((dispatch) => {
            const lateralCount = allNodes.filter(n => n.node_type === 'agent' && n.parent_node_id === dispatch.node_id).length
            if (lateralCount > 0) {
                items.push(`${dispatch.label}（${lateralCount}个智能体）`)
            }
        })
        return items
    }, [graph.nodes])

    const displayedNodeIds = useMemo(() => new Set(flowNodes.map(n => n.id)), [flowNodes])
    const safeDisplayedEdges = useMemo(
        () => flowEdges.filter(e => displayedNodeIds.has(e.source) && displayedNodeIds.has(e.target)),
        [flowEdges, displayedNodeIds],
    )

    const hasTeamGroups = teamLeadIds.length > 0

    const canvas = (
        <div
            className={className}
            style={{
                width: '100%',
                height: maximized ? '100dvh' : '100%',
                minHeight: maximized ? undefined : 300,
                display: 'flex',
                flexDirection: 'column',
                background: 'rgb(var(--color-background-secondary))',
            }}
        >
            {/* 顶栏 */}
            <div style={{
                display: 'flex', alignItems: isMobile ? 'flex-start' : 'center', justifyContent: 'space-between',
                flexWrap: 'wrap', rowGap: 8,
                padding: isMobile ? '10px 12px' : '8px 16px', borderBottom: '1px solid rgb(var(--color-border) / 0.2)',
                background: 'rgb(var(--color-surface))', backdropFilter: 'blur(8px)', flexShrink: 0,
                position: 'relative', zIndex: 10,
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', flex: '1 1 260px', minWidth: 0 }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%',
                        background: awaitingStep ? 'rgb(var(--color-domain-brand))' : 'rgb(var(--color-positive))' }} />
                    <span style={{ fontSize: 12, fontWeight: 600, color: 'rgb(var(--color-primary))' }}>
                        {mode === 'live' ? displayTitle : `${displayTitle} · 蓝图`}
                    </span>
                    <span style={{ fontSize: 10, color: 'rgb(var(--color-muted))' }}>
                        {mode === 'live'
                            ? `${completedCount}/${steps.length} 步完成${awaitingStep ? ` · ⏸ 暂停: ${awaitingStep.label}` : runningStep ? ` · 当前: ${runningStep.label}` : ''}`
                            : displayDesc || (layoutMode === 'manual'
                                ? '手动：可拖拽节点，位置本地保存'
                                : layoutVariantPreference === 'auto'
                                    ? `自动：当前${AUTO_LAYOUT_OPTIONS[effectiveLayoutVariant].label}（随容器宽高切换）`
                                    : `固定：${AUTO_LAYOUT_OPTIONS[effectiveLayoutVariant].label}；切手动可调整，切回自动布局将清除手动记录`)}
                    </span>
                    {!isMobile && groupSummary.length > 0 && (
                        <span style={{ fontSize: 10, color: 'rgb(var(--color-muted))' }}>
                            · 专业组规模：{groupSummary.join('，')}
                        </span>
                    )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', justifyContent: isMobile ? 'flex-start' : 'flex-end' }}>
                    {hasTeamGroups ? (
                    <button
                        onClick={toggleAllTeamGroups}
                        style={{
                            display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px',
                            fontSize: 10, color: allTeamGroupsExpanded ? '#355baf' : '#78716c', borderRadius: 6,
                            border: allTeamGroupsExpanded
                                ? '1px solid rgba(91,127,213,0.38)'
                                : '1px solid rgba(0,0,0,0.08)',
                            background: allTeamGroupsExpanded ? 'rgba(91,127,213,0.08)' : 'transparent',
                            cursor: 'pointer',
                        }}
                        title={allTeamGroupsExpanded ? '收起全部专业组详情' : '展开全部专业组详情'}
                    >
                        {allTeamGroupsExpanded ? '收起全部专业组' : '展开全部专业组'}
                    </button>
                    ) : null}
                    <button
                        onClick={toggleLayoutMode}
                        style={{
                            display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px',
                            fontSize: 10,
                            color: layoutMode === 'manual' ? '#355baf' : '#78716c',
                            borderRadius: 6,
                            border: layoutMode === 'manual'
                                ? '1px solid rgba(91,127,213,0.38)'
                                : '1px solid rgba(0,0,0,0.08)',
                            background: layoutMode === 'manual' ? 'rgba(91,127,213,0.08)' : 'transparent',
                            cursor: 'pointer',
                        }}
                        title={
                            layoutMode === 'manual'
                                ? '切回自动布局：按 Dagre 重新排布并清除已保存的手动位置'
                                : '切换手动布局：可拖拽节点，松手后保存位置'
                        }
                    >
                        {layoutMode === 'manual' ? '手动布局' : '自动布局'}
                    </button>
                    <select
                        value={isControlledLayout ? controlledLayoutVariant : layoutVariantPreference}
                        onChange={(event) => handleLayoutPreferenceChange(event.target.value as LayoutVariantPreference)}
                        disabled={layoutMode === 'manual' || isControlledLayout}
                        style={{
                            height: 24,
                            padding: '0 8px',
                            fontSize: 10,
                            color: layoutMode === 'manual' ? '#a1a1aa' : '#78716c',
                            borderRadius: 6,
                            border: '1px solid rgba(0,0,0,0.08)',
                            background: 'transparent',
                            cursor: layoutMode === 'manual' ? 'not-allowed' : 'pointer',
                        }}
                        title={
                            layoutMode === 'manual'
                                ? '切回自动布局后可选择排布方案'
                                : layoutVariantPreference === 'auto'
                                    ? `根据容器宽高自动切换；当前为${AUTO_LAYOUT_OPTIONS[effectiveLayoutVariant].label}`
                                    : '已锁定排布方向；选择「自动（随容器）」可恢复响应式'
                        }
                    >
                        {responsiveLayoutEnabled ? (
                            <option value="auto">自动（随容器）</option>
                        ) : null}
                        {Object.entries(AUTO_LAYOUT_OPTIONS)
                            .filter(([value]) => selectableLayoutVariants.includes(value as AutoLayoutVariant))
                            .map(([value, option]) => (
                            <option key={value} value={value}>{option.label}</option>
                        ))}
                    </select>
                    {/* HITL 控制按钮 */}
                    {hitlEnabled && onHitlConfigChange && hitlConfigurableSteps.length > 0 && (
                        <div style={{ position: 'relative' }}>
                            <button
                                onClick={() => setHitlPanelOpen(v => !v)}
                                className="flex items-center gap-1 rounded-md border transition-colors text-[10px] px-2.5 py-1"
                                style={{
                                    color: hitlEnabledSteps.length > 0
                                        ? 'rgb(var(--color-primary-accent))'
                                        : 'rgb(var(--color-muted))',
                                    borderColor: hitlEnabledSteps.length > 0
                                        ? 'rgba(var(--color-primary-accent), 0.3)'
                                        : 'rgba(var(--color-border), 0.15)',
                                    background: hitlEnabledSteps.length > 0
                                        ? 'rgba(var(--color-primary-accent), 0.08)'
                                        : 'transparent',
                                    cursor: 'pointer',
                                }}
                            >
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                                </svg>
                                人工确认{hitlEnabledSteps.length > 0 ? ` (${hitlEnabledSteps.length})` : ''}
                            </button>
                            {hitlPanelOpen && (
                                <HitlPanel
                                    configurableSteps={hitlConfigurableSteps}
                                    enabledSteps={hitlEnabledSteps}
                                    onSave={onHitlConfigChange}
                                    onClose={() => setHitlPanelOpen(false)}
                                    isMobile={isMobile}
                                />
                            )}
                        </div>
                    )}

                    <button onClick={toggle} style={{
                        display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px',
                        fontSize: 10, color: '#78716c', borderRadius: 6,
                        border: '1px solid rgba(0,0,0,0.08)', background: 'transparent', cursor: 'pointer',
                    }} title={maximized ? '退出全屏 (ESC)' : '最大化查看'}>
                        {maximized
                            ? <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>退出全屏</>
                            : <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>最大化</>
                        }
                    </button>
                </div>
            </div>

            {/* 画布 */}
            <div ref={flowCanvasRef} style={{ flex: 1, position: 'relative' }}>
                <ReactFlow
                    nodes={flowNodes}
                    edges={safeDisplayedEdges}
                    onNodesChange={onFlowNodesChange}
                    onEdgesChange={onFlowEdgesChange}
                    onNodeDragStop={handleNodeDragStop}
                    nodeTypes={nodeTypes}
                    nodesDraggable={layoutMode === 'manual'}
                    nodesConnectable={false}
                    elementsSelectable
                    onPaneClick={onPaneClick}
                    panOnDrag
                    zoomOnScroll
                    fitView
                    fitViewOptions={{ padding: 0.2 }}
                    minZoom={0.3} maxZoom={2.5}
                    proOptions={{ hideAttribution: true }}
                >
                    <FitViewOnLayoutChange
                        layoutVariant={effectiveLayoutVariant}
                        layoutMode={layoutMode}
                        expandedTeamLeadKey={expandedTeamLeadKey}
                    />
                    <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="rgb(var(--color-border) / 0.35)" />
                    <Controls showInteractive={false} position="bottom-right" style={{ borderRadius: 8, border: '1px solid rgba(0,0,0,0.07)' }} />
                    {maximized && !isMobile && <MiniMap position="bottom-left" pannable zoomable style={{ borderRadius: 8, border: '1px solid rgba(0,0,0,0.07)' }} />}
                </ReactFlow>
            </div>
        </div>
    )

    if (maximized && mounted) {
        return (
            <>
                <div style={{ height: 480 }} />
                {createPortal(
                    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgb(var(--color-background))' }}>
                        {canvas}
                    </div>,
                    document.body
                )}
            </>
        )
    }

    return canvas
}
