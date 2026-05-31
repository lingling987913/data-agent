'use client'

import { useMemo, useState } from 'react'
import ActionEmptyState from '@/features/review-plus-v2/components/workbench/ActionEmptyState'
import ResultSummaryBar from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import { resolveTraceMatrixRowId } from '@/features/review-plus-v2/utils/aeroDesignerWorkbenchUtils'
import { SEVERITY_LABELS } from '@/features/review-plus-v2/types'

interface TraceLink {
  link_id: string
  source_id: string
  target_id: string
  link_type: string
  status: string
  confidence?: number
  rationale?: string
}

interface ReviewItem {
  review_item_id: string
  item_type: string
  severity: string
  status?: string
  title: string
  description: string
  recommendation?: string
  source_artifact_ids?: string[]
  target_artifact_ids?: string[]
  evidence_chain?: Array<{
    artifact_id?: string
    source_file?: string
    section?: string
    summary?: string
  }>
  evidence_chain_summary?: string
  source_quote?: string
}

interface TraceabilityResult {
  summary?: {
    requirement_count?: number
    top_requirement_count?: number
    decomposed_requirement_count?: number
    design_item_count?: number
    verification_claim_count?: number
    review_item_count?: number
    trace_link_count?: number
    decomposed_count?: number
    design_closed_count?: number
    verified_count?: number
    closure_gap_count?: number
    design_closure_coverage?: number
    verification_coverage?: number
  }
  matrix_rows?: Array<Record<string, unknown>>
  trace_links?: TraceLink[]
  review_items?: ReviewItem[]
  gate_status?: string
  gate_summary?: string
  blocking_reasons?: string[]
  limited_scope?: string[]
  missing_materials?: string[]
}

const TRACE_LINK_TYPE_LABELS: Record<string, string> = {
  decomposes: '分解',
  satisfies: '满足',
  verifies: '验证',
  refines: '细化',
  traces_to: '追溯',
}

const TRACE_LINK_STATUS_LABELS: Record<string, string> = {
  candidate: '候选',
  confirmed: '已确认',
  rejected: '已拒绝',
}

const TRACE_REVIEW_ITEM_LABELS: Record<string, string> = {
  missing_decomposition: '需求分解缺失',
  missing_design_closure: '设计闭合缺失',
  missing_verification: '验证缺失',
  design_item_without_requirement_basis: '设计缺上游依据',
  verification_condition_gap: '验证工况覆盖不足',
  decomposed_requirement_without_traceability: '分解需求不可追溯',
}

const TRACE_REVIEW_STATUS_LABELS: Record<string, string> = {
  open: '待处理',
  confirmed: '已确认',
  resolved: '已解决',
  closed: '已关闭',
}

const TRACE_SEVERITY_CLASSES: Record<string, string> = {
  critical: 'border-destructive/20 bg-destructive/5 text-destructive',
  major: 'border-warning/20 bg-warning/8 text-warning',
  minor: 'border-info/20 bg-info/8 text-info',
  suggestion: 'border-border/30 bg-muted/10 text-muted',
  info: 'border-border/30 bg-muted/10 text-muted',
}

type ViewMode = 'matrix' | 'items'

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const text = String(value ?? '').trim()
    if (text) return text
  }
  return '—'
}

function rowArtifact(row: Record<string, unknown>, key: string): Record<string, unknown> {
  return asRecord(row[key])
}

function rowArtifactId(artifact: Record<string, unknown>, ...fallback: unknown[]): string {
  return firstText(artifact.artifact_id, artifact.requirement_id, artifact.design_item_id, artifact.verification_id, artifact.id, ...fallback)
}

function rowArtifactText(artifact: Record<string, unknown>, ...fallback: unknown[]): string {
  return firstText(artifact.text, artifact.title, artifact.summary, artifact.description, ...fallback)
}

function sourceDocuments(row: Record<string, unknown>): string {
  const docs = row.source_documents
  if (Array.isArray(docs)) return docs.map((item) => String(item)).filter(Boolean).join(' / ') || '—'
  return firstText(docs, row.source_file, row.material_name)
}

export default function ReviewPlusTraceabilityTab({
  result,
  onConfirmTraceLink,
  onRejectTraceLink,
  onOpenEvidenceCompare,
  defaultViewMode = 'items',
}: {
  result?: Record<string, unknown>
  onConfirmTraceLink?: (linkId: string, rationale?: string) => Promise<void>
  onRejectTraceLink?: (linkId: string, rationale: string) => Promise<void>
  onOpenEvidenceCompare?: (row: Record<string, unknown>) => void
  defaultViewMode?: ViewMode
}) {
  const [viewMode, setViewMode] = useState<ViewMode>(defaultViewMode)
  const [itemTypeFilter, setItemTypeFilter] = useState('all')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [activeRowId, setActiveRowId] = useState<string | undefined>()
  const [actingLinkId, setActingLinkId] = useState('')
  const [actionError, setActionError] = useState('')

  const data = result as TraceabilityResult | undefined
  const summary = data?.summary || {}
  const matrixRows = Array.isArray(data?.matrix_rows) ? (data!.matrix_rows as unknown[]) : []
  const traceLinks = data?.trace_links || []
  const reviewItems = data?.review_items || []

  const itemTypesInResult = useMemo(() => {
    const types = new Set(reviewItems.map((item) => item.item_type).filter(Boolean))
    return Array.from(types)
  }, [reviewItems])

  const severitiesInResult = useMemo(() => {
    const sevs = new Set(reviewItems.map((item) => item.severity).filter(Boolean))
    return Array.from(sevs)
  }, [reviewItems])

  const statusesInResult = useMemo(() => {
    const stats = new Set(reviewItems.map((item) => item.status || 'open').filter(Boolean))
    return Array.from(stats)
  }, [reviewItems])

  const filteredReviewItems = useMemo(() => {
    return reviewItems.filter((item) => (
      (itemTypeFilter === 'all' || item.item_type === itemTypeFilter)
      && (severityFilter === 'all' || item.severity === severityFilter)
      && (statusFilter === 'all' || (item.status || 'open') === statusFilter)
    ))
  }, [reviewItems, itemTypeFilter, severityFilter, statusFilter])

  if (!data || !Object.keys(data).length) {
    return (
      <ActionEmptyState
        title="暂无追溯结果"
        description="审查流程将构建需求—设计—验证追溯矩阵，用于核对需求闭环与验证覆盖。"
        hint="完成追溯构建步骤后，可在此查看矩阵摘要与链路统计。"
      />
    )
  }

  const gateTone: 'danger' | 'warning' | 'success' | 'default' | 'brand' =
    data.gate_status === 'blocked' ? 'danger'
    : ['limited', 'limited_pass'].includes(String(data.gate_status)) ? 'warning'
    : data.gate_status === 'pass_with_note' ? 'warning'
    : 'success'

  const linkedCount = traceLinks.filter((l) => l.status === 'confirmed').length
  const gapCount = (summary.closure_gap_count || 0) + reviewItems.filter((i) => i.status === 'open').length

  const handleConfirmTraceLink = async (linkId: string) => {
    if (!onConfirmTraceLink || actingLinkId) return
    try {
      setActingLinkId(linkId)
      setActionError('')
      await onConfirmTraceLink(linkId)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '确认追溯链路失败')
    } finally {
      setActingLinkId('')
    }
  }

  const handleRejectTraceLink = async (linkId: string) => {
    if (!onRejectTraceLink || actingLinkId) return
    const rationale = window.prompt('请输入拒绝该追溯链路的原因')?.trim() || ''
    if (!rationale) return
    try {
      setActingLinkId(linkId)
      setActionError('')
      await onRejectTraceLink(linkId, rationale)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '拒绝追溯链路失败')
    } finally {
      setActingLinkId('')
    }
  }

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      <ResultSummaryBar
        items={[
          { label: '准入', value: data.gate_status || '—', tone: gateTone },
          { label: '需求', value: Number(summary.requirement_count || 0), tone: 'brand' },
          { label: '追溯链', value: traceLinks.length, tone: 'default' },
          { label: '已确认', value: linkedCount, tone: 'success' },
          { label: '缺口', value: gapCount, tone: gapCount > 0 ? 'danger' : 'success' },
        ]}
        hint={data.gate_summary || '基于九步链路生成四层需求闭环矩阵。'}
      />

      <div className="rounded-2xl border border-border/25 bg-surface p-3 shadow-soft">
        <div className="mb-2 text-[11px] font-medium text-primary">跨文档一致性概览</div>
        <div className="grid gap-2 text-[10px] sm:grid-cols-2 xl:grid-cols-5">
          {[
            { label: '总需求', value: Number(summary.requirement_count || 0), tone: 'text-primaryAccent' },
            { label: '已分解', value: Number(summary.decomposed_count || 0), tone: 'text-positive' },
            { label: '已设计闭合', value: Number(summary.design_closed_count || 0), tone: 'text-positive' },
            { label: '已验证', value: Number(summary.verified_count || 0), tone: 'text-positive' },
            { label: '缺口', value: Number(summary.closure_gap_count || 0), tone: Number(summary.closure_gap_count || 0) > 0 ? 'text-warning' : 'text-muted' },
          ].map((item) => (
            <div key={item.label} className="rounded-xl border border-border/20 bg-background p-2">
              <div className="text-muted">{item.label}</div>
              <div className={`mt-1 text-base font-medium ${item.tone}`}>{item.value}</div>
            </div>
          ))}
        </div>
      </div>

      {(data.blocking_reasons?.length || data.limited_scope?.length || data.missing_materials?.length) ? (
        <div className="aq-soft-panel rounded-xl p-4">
          <h3 className="aq-section-title">准入检查</h3>
          <div className="mt-2 grid gap-2 text-[11px] md:grid-cols-3">
            <div className="rounded-lg border border-border/20 bg-muted/5 p-3">
              <div className="mb-1 text-[10px] font-medium text-muted">审查提示</div>
              {(data.blocking_reasons || []).length ? data.blocking_reasons!.map((item) => <p key={item} className="text-destructive">{item}</p>) : <p className="text-muted">无</p>}
            </div>
            <div className="rounded-lg border border-border/20 bg-muted/5 p-3">
              <div className="mb-1 text-[10px] font-medium text-muted">受限范围</div>
              {(data.limited_scope || []).length ? data.limited_scope!.map((item) => <p key={item} className="text-amber-700">{item}</p>) : <p className="text-muted">无</p>}
            </div>
            <div className="rounded-lg border border-border/20 bg-muted/5 p-3">
              <div className="mb-1 text-[10px] font-medium text-muted">缺失材料</div>
              {(data.missing_materials || []).length ? data.missing_materials!.map((item) => <p key={item} className="text-primary">{item}</p>) : <p className="text-muted">无</p>}
            </div>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 rounded-2xl border border-border/20 bg-surface p-1 shadow-soft">
        {[
          { key: 'matrix' as ViewMode, label: '闭环矩阵', count: matrixRows.length },
          { key: 'items' as ViewMode, label: '审查项', count: reviewItems.length },
        ].map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setViewMode(item.key)}
            className={`rounded-xl px-3 py-1.5 text-[11px] font-medium transition-colors ${
              viewMode === item.key
                ? 'bg-primaryAccent/10 text-primaryAccent'
                : 'text-muted hover:bg-muted/8 hover:text-primary'
            }`}
          >
            {item.label}
            <span className="ml-1 text-[10px] opacity-70">{item.count}</span>
          </button>
        ))}
      </div>

      {actionError ? (
        <div className="rounded-xl border border-destructive/20 bg-destructive/5 px-3 py-2 text-[11px] text-destructive">
          {actionError}
        </div>
      ) : null}

      {traceLinks.length ? (
        <div className="aq-soft-panel rounded-xl p-4">
          <h3 className="aq-section-title">追溯链路确认</h3>
          <p className="mt-1 text-[11px] text-muted">确认或拒绝候选链路后，系统会重新计算闭环矩阵与缺口项。</p>
          <div className="mt-3 space-y-2">
            {traceLinks.slice(0, 80).map((link) => {
              const isFinal = link.status === 'confirmed' || link.status === 'rejected'
              const busy = actingLinkId === link.link_id
              return (
                <div key={link.link_id} className="flex flex-col gap-2 rounded-lg border border-border/20 bg-background px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 text-[11px]">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-primary">{link.source_id} → {link.target_id}</span>
                      <span className="rounded-full border border-border/25 bg-muted/5 px-2 py-0.5 text-[9px] text-muted">
                        {TRACE_LINK_TYPE_LABELS[link.link_type] || link.link_type}
                      </span>
                      <span className="rounded-full border border-border/25 bg-muted/5 px-2 py-0.5 text-[9px] text-muted">
                        {TRACE_LINK_STATUS_LABELS[link.status] || link.status}
                      </span>
                      {link.confidence != null ? <span className="text-[9px] text-muted">置信度 {Math.round(link.confidence * 100)}%</span> : null}
                    </div>
                    {link.rationale ? <p className="mt-1 text-[10px] text-muted">理由: {link.rationale}</p> : null}
                  </div>
                  <div className="flex shrink-0 gap-1.5">
                    <button
                      type="button"
                      disabled={isFinal || busy || !onConfirmTraceLink}
                      onClick={() => void handleConfirmTraceLink(link.link_id)}
                      className="rounded-lg border border-positive/25 px-3 py-1.5 text-[10px] font-medium text-positive hover:bg-positive/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {busy ? '处理中...' : '确认'}
                    </button>
                    <button
                      type="button"
                      disabled={isFinal || busy || !onRejectTraceLink}
                      onClick={() => void handleRejectTraceLink(link.link_id)}
                      className="rounded-lg border border-destructive/25 px-3 py-1.5 text-[10px] font-medium text-destructive hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      拒绝
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ) : null}

      {viewMode === 'matrix' && (
        <div className="aq-soft-panel rounded-xl p-4">
          <h3 className="aq-section-title">需求闭环矩阵</h3>
          <div className="mt-3 overflow-auto rounded-lg border border-border/20">
            <table className="min-w-[1320px] w-full text-left text-[11px]">
              <thead className="bg-muted/5 text-[10px] text-muted">
                <tr>
                  <th className="px-3 py-2">上级需求</th>
                  <th className="px-3 py-2">分解需求</th>
                  <th className="px-3 py-2">设计实现项</th>
                  <th className="px-3 py-2">验证依据</th>
                  <th className="px-3 py-2">来源文档</th>
                  <th className="px-3 py-2">闭合状态</th>
                  <th className="px-3 py-2">链路确认</th>
                  <th className="px-3 py-2">操作</th>
                </tr>
              </thead>
              <tbody>
                {matrixRows.slice(0, 200).map((row, index) => {
                  const rowData = row as Record<string, unknown>
                  const requirement = rowArtifact(rowData, 'requirement')
                  const decomposedRequirement = rowArtifact(rowData, 'decomposed_requirement')
                  const designItem = rowArtifact(rowData, 'design_item')
                  const verificationClaim = rowArtifact(rowData, 'verification_claim')
                  const topId = rowArtifactId(requirement, rowData.top_requirement_id)
                  const topText = rowArtifactText(requirement, rowData.top_requirement_text)
                  const decomposedId = rowArtifactId(decomposedRequirement, rowData.decomposed_requirement_id)
                  const decomposedText = rowArtifactText(decomposedRequirement, rowData.decomposed_requirement_text)
                  const designId = rowArtifactId(designItem, rowData.design_item_id)
                  const designText = rowArtifactText(designItem, rowData.design_item_text)
                  const verificationId = rowArtifactId(verificationClaim, rowData.verification_id)
                  const verificationText = rowArtifactText(verificationClaim, rowData.verification_text)
                  const closureStatus = String(rowData.closure_status || rowData.status || '')
                  const rowId = resolveTraceMatrixRowId(rowData)
                  const isActive = activeRowId === rowId
                  const evRef = String(requirement?.source_evidence_id || rowData.source_evidence_id || '')
                  const hasEvidence = Boolean(evRef)
                  return (
                    <tr
                      key={rowId || index}
                      className={`border-t border-border/10 align-top cursor-pointer hover:bg-muted/10 transition-colors ${
                        isActive ? 'bg-primaryAccent/10 font-medium' : ''
                      }`}
                      onClick={() => setActiveRowId(rowId)}
                    >
                      <td className="px-3 py-2 text-primary">
                        {topId}
                        {topText !== '—' ? <p className="mt-1 text-[10px] text-muted line-clamp-2">{topText}</p> : null}
                      </td>
                      <td className="px-3 py-2 text-primary">
                        {decomposedId}
                        {decomposedText !== '—' ? <p className="mt-1 text-[10px] text-muted line-clamp-2">{decomposedText}</p> : null}
                      </td>
                      <td className="px-3 py-2 text-primary">
                        {designId}
                        {designText !== '—' ? <p className="mt-1 text-[10px] text-muted line-clamp-2">{designText}</p> : null}
                      </td>
                      <td className="px-3 py-2 text-primary">
                        {verificationId}
                        {verificationText !== '—' ? <p className="mt-1 text-[10px] text-muted line-clamp-2">{verificationText}</p> : null}
                      </td>
                      <td className="px-3 py-2 text-[10px] leading-relaxed text-muted">
                        {sourceDocuments(rowData)}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`rounded-full px-2 py-0.5 text-[10px] ${
                          closureStatus === 'closed' ? 'bg-positive/15 text-positive'
                          : closureStatus === 'open_issue' ? 'bg-warning/15 text-warning'
                          : 'bg-muted/10 text-muted'
                        }`}>
                          {closureStatus === 'closed' ? '已闭合'
                          : closureStatus === 'open_issue' ? '存在问题'
                          : '未闭合'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-[10px] text-muted">
                        {String(rowData.link_count || '0')} 条链路
                      </td>
                      <td className="px-3 py-2">
                        {hasEvidence ? (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              onOpenEvidenceCompare?.(rowData)
                            }}
                            className="rounded-lg border border-border/25 px-2 py-1 text-[9px] text-primaryAccent hover:border-brand/40"
                          >
                            对照原文
                          </button>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
                {!matrixRows.length ? (
                  <tr>
                    <td colSpan={8} className="border-t border-border/10 px-3 py-8 text-center text-muted">
                      当前尚未形成需求闭环矩阵，请确认送审包角色后重新生成。
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {viewMode === 'items' && (
        <div className="aq-soft-panel rounded-xl p-4">
          <h3 className="aq-section-title">跨文档审查项</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            <select
              value={itemTypeFilter}
              onChange={(e) => setItemTypeFilter(e.target.value)}
              className="rounded-xl border border-border/25 bg-surface px-3 py-1.5 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
            >
              <option value="all">全部类型</option>
              {itemTypesInResult.map((type) => (
                <option key={type} value={type}>{TRACE_REVIEW_ITEM_LABELS[type] || type}</option>
              ))}
            </select>
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="rounded-xl border border-border/25 bg-surface px-3 py-1.5 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
            >
              <option value="all">全部严重度</option>
              {severitiesInResult.map((severity) => (
                <option key={severity} value={severity}>{SEVERITY_LABELS[severity] || severity}</option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-xl border border-border/25 bg-surface px-3 py-1.5 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
            >
              <option value="all">全部状态</option>
              {statusesInResult.map((status) => (
                <option key={status} value={status}>{TRACE_REVIEW_STATUS_LABELS[status] || status}</option>
              ))}
            </select>
          </div>
          <div className="mt-3 space-y-2">
            {filteredReviewItems.length ? filteredReviewItems.map((item) => (
              <details key={item.review_item_id} className="group rounded-lg border border-border/20 bg-background p-3">
                <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2">
                  <span className={`rounded border px-1.5 py-0.5 text-[9px] ${TRACE_SEVERITY_CLASSES[item.severity] || 'border-border/30 bg-muted/10 text-muted'}`}>
                    {SEVERITY_LABELS[item.severity] || item.severity}
                  </span>
                  <span className="text-[11px] font-medium text-primary">{TRACE_REVIEW_ITEM_LABELS[item.item_type] || item.title}</span>
                  <span className="rounded-full border border-border/25 bg-muted/5 px-2 py-0.5 text-[9px] text-muted">
                    {TRACE_REVIEW_STATUS_LABELS[item.status || 'open'] || item.status || '待处理'}
                  </span>
                  <span className="text-[10px] text-muted">{[...(item.source_artifact_ids || []), ...(item.target_artifact_ids || [])].join(' / ')}</span>
                </summary>
                <p className="mt-2 text-[11px] leading-relaxed text-primary/80">{item.description}</p>
                {item.recommendation && <p className="mt-1 text-[10px] leading-relaxed text-muted">建议: {item.recommendation}</p>}
                {(item.evidence_chain || []).length ? (
                  <div className="mt-3 rounded-xl border border-border/20 bg-surface p-2">
                    <div className="mb-2 text-[10px] font-medium text-primary">跨文档证据链</div>
                    <div className="space-y-1.5">
                      {(item.evidence_chain || []).map((entry, index) => (
                        <div key={`${item.review_item_id}-evidence-${index}`} className="rounded-lg border border-border/15 bg-background px-2 py-1.5">
                          <div className="flex flex-wrap items-center gap-1.5 text-[9px] text-muted">
                            <span className="rounded-full bg-primaryAccent/8 px-1.5 py-0.5 text-primaryAccent">
                              {entry.artifact_id || `证据 ${index + 1}`}
                            </span>
                            <span>{entry.source_file || '未标注材料'}</span>
                            <span>{entry.section}</span>
                          </div>
                          <p className="mt-1 text-[10px] leading-relaxed text-muted">{entry.summary || '该证据已关联到审查项。'}</p>
                        </div>
                      ))}
                    </div>
                    {item.evidence_chain_summary ? <p className="mt-2 text-[9px] text-muted">{item.evidence_chain_summary}</p> : null}
                  </div>
                ) : item.source_quote ? (
                  <p className="mt-2 rounded-md bg-muted/5 px-2 py-1.5 text-[10px] leading-relaxed text-muted">证据: {item.source_quote}</p>
                ) : null}
                <p className="mt-3 text-[10px] text-muted">
                  如需人工确认或拒绝追溯关系，请在上方“追溯链路确认”区处理候选链路。
                </p>
              </details>
            )) : <p className="text-[11px] text-muted">当前筛选条件下没有跨文档审查项。</p>}
          </div>
        </div>
      )}
    </div>
  )
}
